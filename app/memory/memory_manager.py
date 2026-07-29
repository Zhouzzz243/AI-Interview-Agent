"""
记忆管理器 - 统一入口，封装所有会话操作

【Java 类比】
- 类似 @Service 注解的 MemoryService
- 或者类似 Facade 模式的统一接口
- 职责：整合 SessionStore + ShortTermMemory，提供一站式记忆管理

【核心设计】
MemoryManager 是整个 Memory 层的"门面"，对外提供统一的API：
- 对内协调 SessionStore（持久化）和 ShortTermMemory（上下文）
- 对外隐藏底层复杂性，只暴露业务语义清晰的方法

【双层协作机制】
┌─────────────────────────────────────────────┐
│              MemoryManager (门面)            │
│                                             │
│  ┌───────────────────┐  ┌────────────────┐ │
│  │ SessionStore      │  │ ShortTermMemory│ │
│  │ (Redis 持久化)    │  │ (内存 上下文)   │ │
│  │                   │  │                │ │
│  │ • phase           │  │ • messages[]   │ │
│  │ • scores          │  │ • system_prompt│ │
│  │ • asked_questions │  │ • token控制    │ │
│  │ • followup_budget │  │ • 窗口裁剪     │ │
│  └───────────────────┘  └────────────────┘ │
│                                             │
│  【数据同步】                                │
│  写操作 → 同时更新 Redis + 内存             │
│  读操作 → 优先读内存（快），没有则读Redis    │
└─────────────────────────────────────────────┘

【使用示例】
manager = get_memory_manager()

# 创建会话（同时初始化两层）
await manager.create_session("session_123", "user_456", "resume_789")

# 记录对话（同时更新上下文和历史）
await manager.record_message("session_123", "user", "HashMap底层是...")

# 获取LLM调用所需的完整上下文
messages = await manager.get_context_for_llm("session_123")
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from app.infrastructure.logger import get_logger
from app.memory.session_store import SessionStore, get_session_store
from app.memory.short_term_memory import (
    ShortTermMemory,
    ShortTermMemoryManager,
    get_short_term_memory_manager
)
from app.api.schemas import InterviewPhase

logger = get_logger(__name__)


class MemoryManager:
    """
    记忆管理器核心类
    
    【Java 类比】
    ```java
    @Service
    public class MemoryFacadeServiceImpl implements MemoryFacadeService {
        @Autowired
        private SessionStore sessionStore;
        @Autowired
        private ShortTermMemoryManager memoryManager;
        
        // 统一入口，内部协调两个组件
        public void createSession(String sessionId, String userId) {
            sessionStore.createSession(sessionId, userId);
            memoryManager.createMemory(sessionId);
        }
    }
    ```
    
    【核心方法分类】
    1. 会话生命周期: create/get/delete/exists
    2. 阶段管理: update_phase/get_phase
    3. 对话记录: record_user_message/record_assistant_message
    4. 题目记录: record_asked_question/get_asked_questions
    5. 得分管理: record_score/get_scores/get_average_scores
    6. 追问配额: consume_followup_budget/get_remaining_budget
    7. LLM上下文: get_context_for_llm/update_system_prompt
    8. 统计信息: get_session_summary
    """

    def __init__(self):
        self._session_store: SessionStore = get_session_store()
        self._memory_manager: ShortTermMemoryManager = get_short_term_memory_manager()

    # ══════════════════════════════════════════════
    # 会话生命周期管理
    # ══════════════════════════════════════════════

    async def create_session(
        self,
        session_id: str,
        user_id: str,
        resume_id: str,
        initial_system_prompt: Optional[str] = None,
        phase: InterviewPhase = InterviewPhase.SELF_INTRO
    ) -> bool:
        """
        创建新会话（同时初始化两层记忆）
        
        【执行流程】
        1. 在 Redis 中创建会话状态（持久化）
        2. 在内存中创建短期记忆实例（上下文窗口）
        
        【参数】initial_system_prompt: 初始系统提示词
        
        【返回值】True=成功, False=失败
        """
        redis_success = await self._session_store.create_session(
            session_id=session_id,
            user_id=user_id,
            resume_id=resume_id,
            phase=phase
        )
        
        if not redis_success:
            logger.error("create_session_redis_failed", session_id=session_id)
            return False
            
        self._memory_manager.create_memory(
            session_id=session_id,
            system_prompt=initial_system_prompt
        )
        
        logger.info(
            "memory_session_created",
            session_id=session_id,
            user_id=user_id,
            has_system_prompt=bool(initial_system_prompt)
        )
        
        return True

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取完整会话信息（从 Redis）"""
        return await self._session_store.get_session(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """删除会话（同时清理两层）"""
        redis_success = await self._session_store.delete_session(session_id)
        self._memory_manager.remove_memory(session_id)
        
        if redis_success:
            logger.info("memory_session_deleted", session_id=session_id)
            
        return redis_success

    async def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return await self._session_store.exists(session_id)

    # ══════════════════════════════════════════════
    # 阶段管理
    # ══════════════════════════════════════════════

    async def update_phase(
        self,
        session_id: str,
        new_phase: InterviewPhase,
        new_system_prompt: Optional[str] = None
    ) -> bool:
        """
        更新当前阶段（可选更新系统提示词）
        
        【使用场景】阶段切换时调用
        例如：自我介绍完成 → 切换到实习深挖 + 更新提示词
        """
        success = await self._session_store.update_phase(session_id, new_phase)
        
        if success and new_system_prompt:
            memory = self._memory_manager.get_memory(session_id)
            if memory:
                memory.update_system_prompt(new_system_prompt)
                
        return success

    async def get_phase(self, session_id: str) -> Optional[InterviewPhase]:
        """获取当前阶段"""
        return await self._session_store.get_phase(session_id)

    # ══════════════════════════════════════════════
    # 对话消息管理（双层同步！）
    # ══════════════════════════════════════════════

    async def record_user_message(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        记录用户消息（同时更新两层）
        
        【执行流程】
        1. 添加到短期记忆（用于构建 LLM 上下文）
        2. 存储到 Redis 历史记录（用于持久化和回溯）
        
        【参数】metadata 可包含：当前阶段、题目类型等
        """
        memory = self._memory_manager.get_or_create(session_id)
        memory.add_user_message(content, metadata)
        
        redis_success = await self._session_store.add_chat_message(
            session_id=session_id,
            role="user",
            content=content,
            metadata=metadata
        )
        
        return redis_success

    async def record_assistant_message(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """记录 AI 回复消息（同时更新两层）"""
        memory = self._memory_manager.get_or_create(session_id)
        memory.add_assistant_message(content, metadata)
        
        redis_success = await self._session_store.add_chat_message(
            session_id=session_id,
            role="assistant",
            content=content,
            metadata=metadata
        )
        
        return redis_success

    # ══════════════════════════════════════════════
    # LLM 上下文获取（最常用！）
    # ══════════════════════════════════════════════

    async def get_context_for_llm(self, session_id: str) -> List[Dict[str, str]]:
        """
        获取用于 LLM 调用的完整上下文
        
        【返回值】符合 SDK 要求的消息列表
        [
            {"role": "system", "content": "你是面试官..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            ...
        ]
        
        【注意】这是最常用的方法！每次调用 LLM 前都要用它
        """
        memory = self._memory_manager.get_memory(session_id)
        
        if not memory:
            logger.warning("no_short_term_memory", session_id=session_id)
            
            history = await self._session_store.get_chat_history(session_id, limit=10)
            
            messages = []
            for msg in history:
                messages.append({
                    "role": msg.get("role"),
                    "content": msg.get("content", "")
                })
                
            return messages
            
        return memory.get_messages_for_llm()

    async def update_system_prompt(
        self,
        session_id: str,
        new_prompt: str
    ) -> None:
        """更新系统提示词（如切换阶段时）"""
        memory = self._memory_manager.get_memory(session_id)
        if memory:
            memory.update_system_prompt(new_prompt)

    def get_last_user_content(self, session_id: str) -> Optional[str]:
        """
        获取最后一条用户输入内容
        
        【用途】评分时获取候选人的最新回答
        """
        memory = self._memory_manager.get_memory(session_id)
        if memory:
            last_msg = memory.get_last_user_message()
            return last_msg.content if last_msg else None
        return None

    # ══════════════════════════════════════════════
    # 题目记录管理
    # ══════════════════════════════════════════════

    async def record_asked_question(
        self,
        session_id: str,
        category: str,
        question_id: str
    ) -> bool:
        """记录已问过的题目"""
        return await self._session_store.add_asked_question(
            session_id, category, question_id
        )

    async def get_asked_questions(
        self,
        session_id: str,
        category: Optional[str] = None
    ):
        """获取已问过的题目列表"""
        return await self._session_store.get_asked_questions(session_id, category)

    # ══════════════════════════════════════════════
    # 得分管理
    # ══════════════════════════════════════════════

    async def record_score(
        self,
        session_id: str,
        dimension: str,
        score: int
    ) -> bool:
        """记录某维度得分"""
        return await self._session_store.add_score(session_id, dimension, score)

    async def get_all_scores(self, session_id: str) -> Optional[Dict[str, List[int]]]:
        """获取所有维度的得分记录"""
        return await self._session_store.get_scores(session_id)

    async def get_average_scores(self, session_id: str) -> Dict[str, float]:
        """计算各维度平均分"""
        return await self._session_store.get_average_scores(session_id)

    # ══════════════════════════════════════════════
    # 追问配额管理
    # ══════════════════════════════════════════════

    async def consume_followup_budget(self, session_id: str) -> int:
        """
        消耗一次追问配额
        
        【返回值】剩余配额数量
        - >= 0 : 还可以追问
        - < 0  : 配额用完
        """
        return await self._session_store.decrement_followup_budget(session_id)

    async def get_remaining_followups(self, session_id: str) -> int:
        """获取剩余追问配额"""
        return await self._session_store.get_followup_budget(session_id)

    # ══════════════════════════════════════════════
    # 统计与摘要
    # ══════════════════════════════════════════════

    async def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话摘要（合并两层信息）
        
        【返回值示例】
        {
            "phase": "eight_part_qa",
            "duration_minutes": 25.5,
            "total_questions": 8,
            "average_score": 79.3,
            "remaining_followups": 3,
            "context_messages": 15,
            "estimated_tokens": 2800,
            "user_id": "user_456"
        }
        """
        redis_stats = await self._session_store.get_session_stats(session_id)
        
        if not redis_stats:
            return None
            
        memory = self._memory_manager.get_memory(session_id)
        memory_stats = memory.get_stats() if memory else None
        
        summary = {
            **redis_stats,
            "context_messages": memory_stats.total_messages if memory_stats else 0,
            "context_rounds": memory_stats.window_size if memory_stats else 0,
            "estimated_tokens": memory_stats.estimated_tokens if memory_stats else 0
        }
        
        return summary

    async def get_question_count(self, session_id: str) -> int:
        """获取总出题数"""
        return await self._session_store.get_question_count(session_id)

    async def get_chat_history(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """获取对话历史（从 Redis）"""
        return await self._session_store.get_chat_history(session_id, limit)

    # ══════════════════════════════════════════════
    # 批量会话状态更新（Facade 方法）
    # ══════════════════════════════════════════════

    async def update_session_state(
        self,
        session_id: str,
        **fields
    ) -> bool:
        """
        批量更新会话状态字段

        【设计意图】
        封装 SessionStore.update_fields，避免外部直接
        self._memory_manager._session_store.update_fields(...)
        违反 Demeter 法则。

        【常用字段】phase, follow_up_budget, question_count, last_active, status
        """
        return await self._session_store.update_fields(session_id, fields)

    async def update_session_field(
        self,
        session_id: str,
        field: str,
        value: Any
    ) -> bool:
        """
        更新单个会话状态字段

        【设计意图】
        同 update_session_state，单字段版本的便捷方法。
        """
        return await self._session_store.update_field(session_id, field, value)

    def get_last_assistant_message(self, session_id: str) -> Optional[str]:
        """
        获取最后一条 AI 回复内容

        【设计意图】
        封装 ShortTermMemoryManager 的内部访问，
        避免 Orchestrator 直接 self._memory_manager._memory_manager.get_memory(...)
        违反 Demeter 法则。

        【用途】评分时需要知道"上一道题是什么"
        """
        memory = self._memory_manager.get_memory(session_id)
        if memory:
            last_msg = memory.get_last_assistant_message()
            if last_msg:
                return last_msg.content
        return None


_memory_manager_instance: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """
    获取全局单例
    
    【Java 类比】类似 @Bean(Singleton) 或 @Autowired 注入
    整个应用共享一个 MemoryManager 实例
    """
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager()
    return _memory_manager_instance


def reset_memory_manager():
    """重置单例（测试用）"""
    global _memory_manager_instance
    _memory_manager_instance = None
    reset_session_store()
    try:
        from app.memory.short_term_memory import reset_memory_manager as _stm_reset
        _stm_reset()
    except:
        pass
