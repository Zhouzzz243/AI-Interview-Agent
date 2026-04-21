"""
会话状态存储模块 - 基于 Redis Hash 的持久化会话管理，Redis CRUD（增删改查 SessionState）

【Java 类比】
- 类似 Spring Session + Redis Session Repository
- 或者类似 @SessionScope Bean 的实现
- 职责：面试过程中的所有状态持久化

【核心功能】
1. 创建/获取/删除会话
2. 更新当前阶段 (phase)
3. 记录已问过的题目 (asked_internships, asked_projects, asked_eight_parts)
4. 记录各维度得分 (scores)
5. 管理追问配额 (follow_up_budget)
6. 会话过期自动清理 (TTL: 2小时)

【Redis 数据结构】
Key:   session:{session_id}
Type:  Hash
Fields:
  - phase              → 当前阶段 (str)
  - user_id            → 用户ID (str)
  - resume_id          → 简历ID (str)
  - asked_internships  → 已问实习题 [JSON Array]
  - asked_projects      → 已问项目题 [JSON Array]
  - asked_eight_parts  → 已问八股题 {JSON Object}
  - scores             → 各阶段得分 {JSON Object}
  - follow_up_budget   → 追问配额剩余次数 (int)
  - question_count     → 总出题数 (int)
  - created_at         → 创建时间 (ISO格式)
  - last_active        → 最后活跃时间 (ISO格式)

【使用示例】
# 创建会话
await store.create_session("session_123", "user_456", "resume_789")

# 获取会话
session = await store.get_session("session_123")

# 更新阶段
await store.update_phase("session_123", InterviewPhase.INTERNSHIP_QA)

# 记录已问的实习题
await store.add_asked_question("session_123", "internship", "q1")

# 记录得分
await store.add_score("session_123", "internship", 85)
"""

import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Union

from app.infrastructure.config import get_settings
from app.infrastructure.logger import get_logger
from app.infrastructure.redis_client import RedisClient
from app.api.schemas import InterviewPhase

logger = get_logger(__name__)


class SessionStore:
    """
    会话状态存储核心类

    【Java 类比】
    ```java
    @Service
    public class SessionStoreService {
        @Autowired
        private StringRedisTemplate redisTemplate;

        public void createSession(String sessionId, String userId) {
            // 使用 Hash 结构存储会话
            redisTemplate.opsForHash().putAll(sessionId, initialData);
            // 设置 TTL
            redisTemplate.expire(sessionId, 2, TimeUnit.HOURS);
        }
    }
    ```

    【设计原则】
    1. 所有操作都是异步的 (async/await)
    2. 自动处理 JSON 序列化/反序列化
    3. 每次写入自动刷新 TTL（续期机制）
    4. 提供完整的 CRUD 操作
    """

    def __init__(self):
        self._redis = RedisClient()
        self._settings = get_settings()

        # Key 前缀
        self._key_prefix = "session:"
        
        # 默认 TTL（秒）= 2小时
        self._default_ttl = self._settings.redis.session_ttl

    def _get_key(self, session_id: str) -> str:
        """生成完整的 Redis Key"""
        return f"{self._key_prefix}{session_id}"

    # ══════════════════════════════════════════════
    # 会话生命周期管理
    # ══════════════════════════════════════════════

    async def create_session(
        self,
        session_id: str,
        user_id: str,
        resume_id: str,
        phase: InterviewPhase = InterviewPhase.SELF_INTRO
    ) -> bool:
        """
        创建新会话
        
        【参数说明】
        - session_id: 会话唯一标识（通常由 Java 端生成 UUID）
        - user_id: 用户 ID
        - resume_id: 已解析的简历 ID
        - phase: 初始阶段（默认为自我介绍）

        【返回值】True=创建成功, False=创建失败（如已存在或Redis不可用）

        【初始化数据】
        {
            "phase": "self_introduction",
            "user_id": "user_xxx",
            "resume_id": "resume_yyy",
            "asked_internships": "[]",
            "asked_projects": "[]",
            "asked_eight_parts": "{}",
            "scores": "{}",
            "follow_up_budget": "5",
            "question_count": "0",
            "created_at": "2026-04-15T10:30:00+08:00",
            "last_active": "2026-04-15T10:30:00+08:00"
        }

        【调用时机】
        Java 端调用 Python /api/interview/start 时触发
        """
        key = self._get_key(session_id)
        
        now = datetime.now(timezone.utc).isoformat()
        
        initial_data = {
            "phase": phase.value,
            "user_id": user_id,
            "resume_id": resume_id,
            "asked_internships": [],
            "asked_projects": [],
            "asked_eight_parts": {},
            "scores": {
                "internship": [],
                "project": [],
                "eight_part": [],
                "self_intro": []
            },
            "follow_up_budget": self._settings.interview.followup_budget,
            "question_count": 0,
            "created_at": now,
            "last_active": now,
            "chat_history": []
        }

        try:
            result = await self._redis.hset(key, initial_data)
            
            if result:
                await self._refresh_ttl(key)
                logger.info(
                    "session_created",
                    session_id=session_id,
                    user_id=user_id,
                    resume_id=resume_id
                )
            
            return result
            
        except Exception as e:
            logger.error("session_create_failed", session_id=session_id, error=str(e))
            return False

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取完整会话数据
        
        【返回值】
        - 成功：包含所有字段的字典
        - 失败/不存在：None

        【返回数据结构】
        {
            "phase": "internship_qa",
            "user_id": "user_456",
            "resume_id": "resume_789",
            "asked_internships": ["q1", "q2"],
            "asked_projects": ["q3"],
            "asked_eight_parts": {"javase": 2, "jvm": 1},
            "scores": {"internship": [85, 78], ...},
            "follow_up_budget": 3,
            "question_count": 5,
            ...
        }
        """
        key = self._get_key(session_id)
        
        data = await self._redis.hgetall(key)
        
        if not data:
            logger.warning("session_not_found", session_id=session_id)
            return None
            
        return data

    async def delete_session(self, session_id: str) -> bool:
        """删除会话（面试结束时调用）"""
        key = self._get_key(session_id)
        
        result = await self._redis.delete(key)
        
        if result:
            logger.info("session_deleted", session_id=session_id)
            
        return result > 0

    async def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        key = self._get_key(session_id)
        return await self._redis.exists(key)

    # ══════════════════════════════════════════════
    # 阶段管理
    # ══════════════════════════════════════════════

    async def update_phase(self, session_id: str, new_phase: InterviewPhase) -> bool:
        """
        更新当前阶段
        
        【使用场景】
        - 自我介绍完成 → 切换到 INTERNSHIP_QA
        - 实习深挖完成 → 切换到 PROJECT_QA
        - 八股问答平均分 < 70 → 切换到 CHAT_MODE
        """
        key = self._get_key(session_id)
        
        success = await self._redis.hset(key, {"phase": new_phase.value})
        
        if success:
            await self._refresh_ttl(key)
            await self._update_last_active(key)
            logger.info(
                "session_phase_updated",
                session_id=session_id,
                new_phase=new_phase.value
            )
        
        return success

    async def get_phase(self, session_id: str) -> Optional[InterviewPhase]:
        """获取当前阶段"""
        key = self._get_key(session_id)
        
        phase_value = await self._redis.hget(key, "phase")
        
        if not phase_value:
            return None
            
        try:
            return InterviewPhase(phase_value)
        except ValueError:
            logger.error("invalid_phase_value", session_id=session_id, value=phase_value)
            return None

    # ══════════════════════════════════════════════
    # 题目记录管理
    # ══════════════════════════════════════════════

    async def add_asked_question(
        self,
        session_id: str,
        category: str,
        question_id: str
    ) -> bool:
        """
        记录已问过的题目
        
        【参数说明】
        - category: 题目分类 ("internship" | "project" | "eight_part")
        - question_id: 题目唯一标识

        【内部逻辑】
        - internship/project: 追加到数组末尾 ["q1", "q2"]
        - eight_part: 计数器递增 {"javase": 2, "jvm": 1}

        【用途】防止重复提问、统计覆盖范围
        """
        key = self._get_key(session_id)
        
        try:
            if category in ("internship", "project"):
                field_name = f"asked_{category}s"
                
                existing = await self._redis.hget(key, field_name, default=[])
                questions_list = existing if isinstance(existing, list) else []
                
                if question_id in questions_list:
                    logger.warning("duplicate_question", session_id=session_id, question_id=question_id)
                    return True
                
                questions_list.append(question_id)
                
                await self._redis.hset(key, {field_name: questions_list})
                
            elif category == "eight_part":
                sub_category = question_id.split("_")[0] if "_" in question_id else question_id
                
                existing = await self._redis.hget(key, "asked_eight_parts", default={})
                counts_dict = existing if isinstance(existing, dict) else {}
                
                current_count = counts_dict.get(sub_category, 0)
                counts_dict[sub_category] = current_count + 1
                
                await self._redis.hset(key, {"asked_eight_parts": counts_dict})
                
            else:
                logger.error("invalid_question_category", category=category)
                return False
                
            await self._increment_question_count(key)
            await self._refresh_ttl(key)
            await self._update_last_active(key)
            
            return True
            
        except Exception as e:
            logger.error("add_question_failed", session_id=session_id, error=str(e))
            return False

    async def get_asked_questions(
        self,
        session_id: str,
        category: Optional[str] = None
    ) -> Union[List[str], Dict[str, int], None]:
        """
        获取已问过的题目列表
        
        【参数】category=None 时返回所有分类
        """
        key = self._get_key(session_id)
        
        if category and category in ("internship", "project"):
            field_name = f"asked_{category}s"
            data = await self._redis.hget(key, field_name, default=[])
            return data if data else []
            
        elif category == "eight_part":
            data = await self._redis.hget(key, "asked_eight_parts", default={})
            return data if data else {}
            
        else:
            internships = await self._redis.hget(key, "asked_internships", default=[])
            projects = await self._redis.hget(key, "asked_projects", default=[])
            eight_parts = await self._redis.hget(key, "asked_eight_parts", default={})
            
            return {
                "internships": internships if internships else [],
                "projects": projects if projects else [],
                "eight_parts": eight_parts if eight_parts else {}
            }

    # ══════════════════════════════════════════════
    # 得分管理
    # ══════════════════════════════════════════════

    async def add_score(
        self,
        session_id: str,
        dimension: str,
        score: int
    ) -> bool:
        """
        记录某维度的得分
        
        【参数】dimension 可选值:
        - "self_intro": 自我介绍得分
        - "internship": 实习经历得分
        - "project": 项目经验得分
        - "eight_part": 八股文得分
        - "chat": 闲聊模式得分（可选）
        """
        key = self._get_key(session_id)
        
        valid_dimensions = {"self_intro", "internship", "project", "eight_part", "chat"}
        
        if dimension not in valid_dimensions:
            logger.error("invalid_score_dimension", dimension=dimension)
            return False
            
        try:
            existing_scores = await self._redis.hget(key, "scores", default={})
            scores_dict = existing_scores if isinstance(existing_scores, dict) else {}
            
            if dimension not in scores_dict:
                scores_dict[dimension] = []
                
            scores_dict[dimension].append(score)
            
            await self._redis.hset(key, {"scores": scores_dict})
            await self._refresh_ttl(key)
            await self._update_last_active(key)
            
            logger.info(
                "score_recorded",
                session_id=session_id,
                dimension=dimension,
                score=score,
                total=len(scores_dict[dimension])
            )
            
            return True
            
        except Exception as e:
            logger.error("add_score_failed", session_id=session_id, error=str(e))
            return False

    async def get_scores(self, session_id: str) -> Optional[Dict[str, List[int]]]:
        """获取所有维度的得分记录"""
        key = self._get_key(session_id)
        
        data = await self._redis.hget(key, "scores")
        
        if not data:
            return None
            
        return data

    async def get_average_scores(self, session_id: str) -> Dict[str, float]:
        """
        计算各维度平均分
        
        【返回值示例】
        {
            "internship": 81.67,  # (85+78+82)/3
            "project": 80.0,      # (82+78)/2
            "eight_part": 75.0    # (80+75+70)/3
        }
        """
        scores = await self.get_scores(session_id)
        
        if not scores:
            return {}
            
        averages = {}
        
        for dimension, score_list in scores.items():
            if score_list:
                averages[dimension] = round(sum(score_list) / len(score_list), 2)
                
        return averages

    # ══════════════════════════════════════════════
    # 追问配额管理
    # ══════════════════════════════════════════════

    async def decrement_followup_budget(self, session_id: str) -> int:
        """
        消耗一次追问配额
        
        【返回值】剩余配额数量
        - >= 0 : 还可以继续追问
        - < 0  : 配额已用完
        """
        key = self._get_key(session_id)
        
        current = await self._redis.hget(key, "follow_up_budget", default=0)
        budget = int(current) if current else 0
        
        if budget <= 0:
            return -1
            
        new_budget = budget - 1
        await self._redis.hset(key, {"follow_up_budget": new_budget})
        await self._refresh_ttl(key)
        
        logger.info(
            "followup_budget_decremented",
            session_id=session_id,
            remaining=new_budget
        )
        
        return new_budget

    async def get_followup_budget(self, session_id: str) -> int:
        """获取剩余追问配额"""
        key = self._get_key(session_id)
        
        current = await self._redis.hget(key, "follow_up_budget", default=0)
        return int(current) if current else 0

    # ══════════════════════════════════════════════
    # 对话历史管理
    # ══════════════════════════════════════════════

    async def add_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        添加对话消息到历史
        
        【参数】role: "user" | "assistant"
        
        【消息结构】
        {
            "role": "user",
            "content": "...",
            "timestamp": "2026-04-15T10:31:00",
            "metadata": {...}  # 可选（如得分、题目类型等）
        }
        """
        key = self._get_key(session_id)
        
        message = {
            "role": role,
            "content": content[:2000],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        }
        
        try:
            existing = await self._redis.hget(key, "chat_history", default=[])
            history = existing if isinstance(existing, list) else []
            
            history.append(message)
            
            history = history[-50:]
            
            await self._redis.hset(key, {"chat_history": history})
            await self._refresh_ttl(key)
            await self._update_last_active(key)
            
            return True
            
        except Exception as e:
            logger.error("add_chat_message_failed", session_id=session_id, error=str(e))
            return False

    async def get_chat_history(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """获取最近的对话历史"""
        key = self._get_key(session_id)
        
        data = await self._redis.hget(key, "chat_history", default=[])
        
        if not data:
            return []
            
        history = data if isinstance(data, list) else []
        return history[-limit:]

    # ══════════════════════════════════════════════
    # 统计信息
    # ══════════════════════════════════════════════

    async def get_question_count(self, session_id: str) -> int:
        """获取总出题数"""
        key = self._get_key(session_id)
        
        count = await self._redis.hget(key, "question_count", default=0)
        return int(count) if count else 0

    async def _increment_question_count(self, key: str):
        """内部方法：递增题目计数"""
        count = await self._redis.hget(key, "question_count", default=0)
        new_count = (int(count) if count else 0) + 1
        await self._redis.hset(key, {"question_count": new_count})

    async def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话统计摘要
        
        【返回值示例】
        {
            "phase": "eight_part_qa",
            "duration_minutes": 25.5,
            "total_questions": 8,
            "average_score": 79.3,
            "remaining_followups": 3
        }
        """
        session = await self.get_session(session_id)
        
        if not session:
            return None
            
        created_at_str = session.get("created_at")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                duration_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
            except:
                duration_minutes = 0
        else:
            duration_minutes = 0
        
        averages = await self.get_average_scores(session_id)
        all_scores = []
        
        for scores in averages.values():
            all_scores.append(scores)
            
        avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0
        
        return {
            "phase": session.get("phase"),
            "duration_minutes": round(duration_minutes, 1),
            "total_questions": int(session.get("question_count", 0)),
            "average_score": avg_score,
            "remaining_followups": int(session.get("follow_up_budget", 0)),
            "user_id": session.get("user_id"),
            "resume_id": session.get("resume_id")
        }

    # ══════════════════════════════════════════════
    # 内部辅助方法
    # ══════════════════════════════════════════════

    async def _refresh_ttl(self, key: str):
        """刷新 TTL（续期）"""
        await self._redis.expire(key, self._default_ttl)

    async def _update_last_active(self, key: str):
        """更新最后活跃时间"""
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(key, {"last_active": now})


_session_store_instance: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """
    获取全局单例
    
    【Java 类比】类似 @Bean(Singleton)
    """
    global _session_store_instance
    if _session_store_instance is None:
        _session_store_instance = SessionStore()
    return _session_store_instance


def reset_session_store():
    """重置单例（测试用）"""
    global _session_store_instance
    _session_store_instance = None
