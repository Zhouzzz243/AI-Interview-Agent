"""
Redis 客户端模块 - 会话状态与缓存管理

【Java 类比】
- 类似 Spring Data Redis + RedisTemplate 的封装
- 或者类似 @Cacheable 注解的缓存服务
- 职责：存储面试会话状态、对话历史、临时缓存

【Redis 使用场景】
1. 会话状态存储 (SessionState): 面试进度、当前阶段、得分等
2. 对话历史缓存: 最近N轮对话（避免每次查数据库）
3. 限流计数器: API 调用频率控制
4. 分布式锁: 防止并发操作冲突

【数据结构选择】
┌──────────────┬─────────────┬─────────────────────────────────┐
│ 数据类型      │ 用途         │ 示例                            │
├──────────────┼─────────────┼─────────────────────────────────┤
│ String + JSON │ 会话状态     │ session:{id} → SessionState    │
│ Hash         │ 用户信息     │ user:{id} → {name, resume_id}  │
│ List         │ 对话历史     │ history:{session_id} → [msg...] │
│ ZSet         │ 排行榜       │ leaderboard:score → {score, id}│
│ String (TTL) │ 临时缓存     │ cache:llm:{hash} → response    │
└──────────────┴─────────────┴─────────────────────────────────┘

【Python 库说明】
- redis-py: 官方 Python Redis 客户端
- 支持同步和异步模式
- 连接池管理（类似 HikariCP）
"""

import json
import time
from typing import Optional, Any, Dict, List, Union
from datetime import timedelta

import redis

from app.infrastructure.config import get_settings
from app.infrastructure.logger import get_logger

logger = get_logger(__name__)


class RedisClient:
    """
    Redis 客户端核心类

    【Java 类比】
    ```java
    @Service
    public class RedisServiceImpl {
        @Autowired
        private StringRedisTemplate redisTemplate;

        // 类似 Python 的 set_json()
        public void setJson(String key, Object value, long timeout) {
            String json = objectMapper.writeValueAsString(value);
            redisTemplate.opsForValue().set(key, json, timeout, TimeUnit.SECONDS);
        }

        // 类似 Python 的 get_json()
        public <T> T getJson(String key, Class<T> clazz) {
            String json = redisTemplate.opsForValue().get(key);
            return objectMapper.readValue(json, clazz);
        }
    }
    ```

    【核心功能】
    1. set_json() / get_json(): JSON 序列化存取（最常用）
    2. set() / get(): 基本字符串操作
    3. delete(): 删除键
    4. exists(): 检查键是否存在
    5. ttl(): 获取剩余过期时间
    6. incr(): 计数器递增
    """

    def __init__(self):
        settings = get_settings()

        self._host = settings.redis.host
        self._port = settings.redis.port
        self._password = settings.redis.password
        self._db = settings.redis.db
        self._default_ttl = settings.redis.session_ttl

        self._pool = None
        self._redis = None
        self._is_connected = False

        self._init_connection()

    def _init_connection(self):
        """初始化 Redis 连接池"""
        try:
            self._pool = redis.ConnectionPool(
                host=self._host,
                port=self._port,
                password=self._password if self._password else None,
                db=self._db,
                max_connections=10,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )

            self._redis = redis.Redis(connection_pool=self._pool)

            self._redis.ping()
            self._is_connected = True

            logger.info(
                "redis_initialized",
                host=self._host,
                port=self._port,
                db=self._db,
                pool_size=10
            )

        except Exception as e:
            logger.warning(
                "redis_connection_failed",
                error=str(e),
                action="将使用内存模式（开发环境可接受）"
            )
            self._is_connected = False

    def is_available(self) -> bool:
        """检查 Redis 是否可用"""
        return self._is_connected and self._redis is not None

    @property
    def client(self) -> Optional[redis.Redis]:
        """获取原始 Redis 客户端（高级用法）"""
        return self._redis

    # ══════════════════════════════════════════════
    # JSON 序列化操作（最常用）
    # ══════════════════════════════════════════════

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        nx: bool = False
    ) -> bool:
        """
        存储 JSON 数据

        【参数说明】
        - key: Redis 键名
        - value: 任意可序列化的 Python 对象（dict/list/自定义对象）
        - ttl: 过期时间(秒)，None 则使用默认值
        - nx: 是否仅在键不存在时设置（类似 SETNX）

        【Java 类比】
        ```java
        // 类似 redisTemplate.opsForValue().set(key, json, timeout)
        // 但自动处理了 JSON 序列化
        ```

        【使用示例】
        await redis.set_json("session:abc123", session_state_dict, ttl=7200)
        await redis.set_json("cache:user_456", user_info, ttl=300)
        """
        if not self._is_connected:
            logger.warning("redis_unavailable", operation="set_json", key=key)
            return False

        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)

            expire_time = ttl or self._default_ttl

            if nx:
                result = self._redis.set(key, serialized, nx=True, ex=expire_time)
                return result is not None
            else:
                self._redis.setex(key, expire_time, serialized)
                return True

        except Exception as e:
            logger.error("redis_set_failed", key=key, error=str(e))
            return False

    async def get_json(
        self,
        key: str,
        default: Any = None
    ) -> Optional[Any]:
        """
        获取并反序列化 JSON 数据

        【参数说明】
        - key: Redis 键名
        - default: 键不存在时的默认值

        【返回值】
        - 反序列化后的 Python 对象 (dict/list 等)
        - 键不存在时返回 default

        【使用示例】
        state = await redis.get_json("session:abc123")
        if state:
            print(state["current_phase"])  # "project_qa"
        """
        if not self._is_connected:
            logger.warning("redis_unavailable", operation="get_json", key=key)
            return default

        try:
            data = self._redis.get(key)
            if data is None:
                return default

            return json.loads(data)

        except (json.JSONDecodeError, Exception) as e:
            logger.error("redis_get_failed", key=key, error=str(e))
            return default

    # ══════════════════════════════════════════════
    # 基础字符串操作
    # ══════════════════════════════════════════════

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None
    ) -> bool:
        """设置字符串值"""
        if not self._is_connected:
            return False
        try:
            expire_time = ttl or self._default_ttl
            self._redis.setex(key, expire_time, value)
            return True
        except Exception as e:
            logger.error("redis_set_failed", key=key, error=str(e))
            return False

    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取字符串值"""
        if not self._is_connected:
            return default
        try:
            result = self._redis.get(key)
            return result if result else default
        except Exception as e:
            logger.error("redis_get_failed", key=key, error=str(e))
            return default

    # ══════════════════════════════════════════════
    # 删除与存在性检查
    # ══════════════════════════════════════════════

    async def delete(self, *keys: str) -> int:
        """删除一个或多个键"""
        if not self._is_connected or not keys:
            return 0
        try:
            return self._redis.delete(*keys)
        except Exception as e:
            logger.error("redis_delete_failed", keys=list(keys), error=str(e))
            return 0

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not self._is_connected:
            return False
        try:
            return bool(self._redis.exists(key))
        except Exception as e:
            logger.error("redis_exists_failed", key=key, error=str(e))
            return False

    async def ttl(self, key: str) -> int:
        """获取键的剩余过期时间(秒)，-1 表示永不过期，-2 表示不存在"""
        if not self._is_connected:
            return -2
        try:
            return self._redis.ttl(key)
        except Exception as e:
            logger.error("redis_ttl_failed", key=key, error=str(e))
            return -2

    async def expire(self, key: str, seconds: int) -> bool:
        """设置键的过期时间(秒)"""
        if not self._is_connected:
            return False
        try:
            self._redis.expire(key, seconds)
            return True
        except Exception as e:
            logger.error("redis_expire_failed", key=key, error=str(e))
            return False

    # ══════════════════════════════════════════════
    # Hash 操作（用于结构化数据）
    # ══════════════════════════════════════════════

    async def hset(self, name: str, mapping: Dict[str, Any]) -> bool:
        """设置 Hash 字段"""
        if not self._is_connected:
            return False
        try:
            serialized_mapping = {
                k: json.dumps(v, ensure_ascii=False, default=str)
                for k, v in mapping.items()
            }
            self._redis.hset(name, mapping=serialized_mapping)
            return True
        except Exception as e:
            logger.error("redis_hset_failed", name=name, error=str(e))
            return False

    async def hget(self, name: str, key: str, default: Any = None) -> Any:
        """获取 Hash 字段值"""
        if not self._is_connected:
            return default
        try:
            data = self._redis.hget(name, key)
            if data is None:
                return default
            return json.loads(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.error("redis_hget_failed", name=name, key=key, error=str(e))
            return default

    async def hgetall(self, name: str) -> Dict[str, Any]:
        """获取 Hash 所有字段"""
        if not self._is_connected:
            return {}
        try:
            data = self._redis.hgetall(name)
            return {
                k: json.loads(v) if v else None
                for k, v in data.items()
            }
        except Exception as e:
            logger.error("redis_hgetall_failed", name=name, error=str(e))
            return {}

    # ══════════════════════════════════════════════
    # List 操作（用于对话历史）
    # ══════════════════════════════════════════════

    async def lpush(self, name: str, *values: Any) -> int:
        """从左侧压入列表"""
        if not self._is_connected:
            return 0
        try:
            serialized = [json.dumps(v, ensure_ascii=False, default=str) for v in values]
            return self._redis.lpush(name, *serialized)
        except Exception as e:
            logger.error("redis_lpush_failed", name=name, error=str(e))
            return 0

    async def lrange(self, name: str, start: int = 0, end: int = -1) -> List[Any]:
        """获取列表范围元素"""
        if not self._is_connected:
            return []
        try:
            data = self._redis.lrange(name, start, end)
            return [json.loads(item) if item else None for item in data]
        except Exception as e:
            logger.error("redis_lrange_failed", name=name, error=str(e))
            return []

    async def llen(self, name: str) -> int:
        """获取列表长度"""
        if not self._is_connected:
            return 0
        try:
            return self._redis.llen(name)
        except Exception as e:
            logger.error("redis_llen_failed", name=name, error=str(e))
            return 0

    # ══════════════════════════════════════════════
    # 计数器操作
    # ══════════════════════════════════════════════

    async def incr(self, key: str, amount: int = 1) -> int:
        """原子递增计数器"""
        if not self._is_connected:
            return 0
        try:
            if amount == 1:
                return self._redis.incr(key)
            else:
                return self._redis.incrby(key, amount)
        except Exception as e:
            logger.error("redis_incr_failed", key=key, error=str(e))
            return 0

    async def decr(self, key: str, amount: int = 1) -> int:
        """原子递减计数器"""
        if not self._is_connected:
            return 0
        try:
            if amount == 1:
                return self._redis.decr(key)
            else:
                return self._redis.decrby(key, amount)
        except Exception as e:
            logger.error("redis_decr_failed", key=key, error=str(e))
            return 0

    # ══════════════════════════════════════════════
    # 面试会话专用方法（业务层封装）
    # ══════════════════════════════════════════════

    async def save_session_state(
        self,
        session_id: str,
        state: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """
        保存面试会话状态

        【使用示例】
        await redis.save_session_state("sess_abc123", {
            "current_phase": "project_qa",
            "question_count": 5,
            "scores": [85, 78, 92],
            "conversation_history": [...]
        })
        """
        key = f"interview:session:{session_id}"
        return await self.set_json(key, state, ttl or self._default_ttl)

    async def load_session_state(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """加载面试会话状态"""
        key = f"interview:session:{session_id}"
        return await self.get_json(key)

    async def append_conversation_turn(
        self,
        session_id: str,
        turn: Dict[str, Any],
        max_length: int = 20
    ) -> int:
        """
        追加一轮对话到历史记录

        【参数说明】
        - session_id: 会话ID
        - turn: 一轮对话 {"question": "...", "answer": "...", "score": 85}
        - max_length: 最大保留轮数（防止无限增长）
        """
        list_key = f"interview:history:{session_id}"

        await self.lpush(list_key, turn)

        current_len = await self.llen(list_key)
        if current_len > max_length:
            await self.client.ltrim(list_key, 0, max_length - 1)

        return min(current_len, max_length)

    async def get_recent_history(
        self,
        session_id: str,
        count: int = 10
    ) -> List[Dict[str, Any]]:
        """获取最近 N 轮对话历史"""
        list_key = f"interview:history:{session_id}"
        return await self.lrange(list_key, 0, count - 1)

    async def clear_session(self, session_id: str) -> bool:
        """清除会话所有相关数据"""
        keys_to_delete = [
            f"interview:session:{session_id}",
            f"interview:history:{session_id}",
        ]
        deleted = await self.delete(*keys_to_delete)
        return deleted > 0


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_redis_client_instance: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """获取全局 Redis 客户端单例"""
    global _redis_client_instance
    if _redis_client_instance is None:
        _redis_client_instance = RedisClient()
    return _redis_client_instance
