"""
短期记忆模块 - LLM 上下文窗口管理，滑动窗口（保留最近 N 轮对话作为 LLM 上下文）

【Java 类比】
- 类似 ConversationContext 或 ChatHistory 对象
- 或者类似 LLM API 的 messages 列表管理器
- 职责：管理当前对话的上下文，控制 Token 消耗

【核心功能】
1. 维护最近 N 轮对话（滑动窗口）
2. 控制 Token 总量 < 上限（默认 4000）
3. 构建 LLM 调用所需的 messages 格式
4. 支持系统提示词注入
5. 支持摘要压缩（当对话过长时）

【为什么需要短期记忆？】
- LLM 有上下文长度限制（GLM-4: 128K tokens）
- 但为了节省成本和提升响应速度，我们主动控制输入长度
- 只保留最近 10-15 轮对话，足够维持连贯性

【数据结构】
messages = [
    {"role": "system", "content": "你是面试官..."},
    {"role": "user", "content": "自我介绍..."},
    {"role": "assistant", "content": "好的，请开始..."},
    {"role": "user", "content": "我是XXX..."},
    ...
]

【使用示例】
memory = ShortTermMemory(system_prompt="你是面试官")
memory.add_user_message("HashMap底层是什么？")
memory.add_assistant_message("HashMap底层是数组+链表...")
messages = memory.get_messages_for_llm()  # 构建LLM调用格式
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Message:
    """
    单条消息
    
    【属性】
    - role: 角色 ("system" | "user" | "assistant")
    - content: 消息内容
    - timestamp: 时间戳
    - metadata: 元数据（可选，如得分、题目类型）
    """
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Optional[Dict] = None
    
    def to_dict(self) -> Dict[str, str]:
        """转换为字典格式（用于 LLM 调用）"""
        return {
            "role": self.role,
            "content": self.content
        }


@dataclass
class MemoryStats:
    """
    记忆统计信息
    
    【用途】监控和调试
    """
    total_messages: int = 0           # 总消息数
    user_messages: int = 0             # 用户消息数
    assistant_messages: int = 0        # AI回复消息数
    estimated_tokens: int = 0          # 预估 Token 数
    window_size: int = 0               # 当前窗口大小（轮次）


class ShortTermMemory:
    """
    短期记忆核心类
    
    【Java 类比】
    ```java
    @Component
    public class ConversationContext {
        private List<Message> messages;
        private int maxTokens;
        private int maxRounds;
        
        public void addUserMessage(String content) { ... }
        public List<Map<String, String>> getMessagesForLlm() { ... }
    }
    ```
    
    【设计原则】
    1. 内存中的对象，不持久化（用完即弃）
    2. 滑动窗口：只保留最近 N 轮
    3. Token 控制：自动截断超长内容
    4. 线程安全：每个会话一个实例
    """

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        max_rounds: int = 10,
        max_tokens: int = 4000,
        max_content_length: int = 2000
    ):
        """
        初始化短期记忆
        
        【参数说明】
        - system_prompt: 系统提示词（定义AI角色和行为）
        - max_rounds: 最大保留轮数（默认10轮=20条消息）
        - max_tokens: 最大Token限制（默认4000）
        - max_content_length: 单条消息最大字符数（默认2000）
        
        【为什么设置这些限制？】
        - max_rounds: 保持上下文相关性，太旧的对话可能不相关
        - max_tokens: 控制成本和响应速度
        - max_content_length: 防止单条消息过长撑爆上下文
        """
        self._system_prompt = system_prompt
        self._max_rounds = max_rounds
        self._max_tokens = max_tokens
        self._max_content_length = max_content_length
        
        self._messages: List[Message] = []
        
        if system_prompt:
            self._add_system_message(system_prompt)

    def add_user_message(
        self,
        content: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        添加用户消息
        
        【参数说明】
        - content: 用户输入内容
        - metadata: 可选元数据（如当前阶段、题目类型等）
        
        【自动处理】
        1. 截断过长内容（>2000字符）
        2. 添加到消息列表末尾
        3. 如果超过最大轮数，自动移除最旧的消息对
        """
        truncated_content = content[:self._max_content_length]
        
        message = Message(
            role="user",
            content=truncated_content,
            metadata=metadata
        )
        
        self._messages.append(message)
        self._trim_if_needed()

    def add_assistant_message(
        self,
        content: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """添加AI回复消息"""
        truncated_content = content[:self._max_content_length]
        
        message = Message(
            role="assistant",
            content=truncated_content,
            metadata=metadata
        )
        
        self._messages.append(message)
        self._trim_if_needed()

    def _add_system_message(self, content: str) -> None:
        """添加系统提示词（始终在首位）"""
        message = Message(role="system", content=content)
        self._messages.insert(0, message)

    def update_system_prompt(self, new_prompt: str) -> None:
        """
        更新系统提示词
        
        【使用场景】面试阶段切换时更新角色设定
        例如：
        - 自我介绍阶段："请引导候选人自我介绍"
        - 实习深挖阶段："你是技术面试官，深挖实习经历"
        - 八股问答阶段："考察基础知识的掌握程度"
        """
        if self._messages and self._messages[0].role == "system":
            self._messages[0].content = new_prompt
        else:
            self._add_system_message(new_prompt)

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        """
        获取用于 LLM 调用的消息列表
        
        【返回格式】符合 OpenAI/ZhipuAI SDK 要求的格式
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            ...
        ]
        
        【注意】这是最常用的方法！每次调用 LLM 前都要调用它
        """
        return [msg.to_dict() for msg in self._messages]

    def get_recent_messages(self, n: int = 5) -> List[Message]:
        """获取最近 N 条消息"""
        return self._messages[-n:] if n > 0 else []

    def get_last_user_message(self) -> Optional[Message]:
        """获取最后一条用户消息（常用于评分）"""
        for msg in reversed(self._messages):
            if msg.role == "user":
                return msg
        return None

    def get_last_user_content(self) -> Optional[str]:
        """获取最后一条用户消息的内容（返回字符串，便于直接使用）"""
        msg = self.get_last_user_message()
        return msg.content if msg else None

    def get_last_assistant_message(self) -> Optional[Message]:
        """获取最后一条AI消息（常用于获取上一题）"""
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg
        return None

    def clear(self) -> None:
        """清空所有消息（保留系统提示词）"""
        if self._system_prompt:
            self._messages = [Message(role="system", content=self._system_prompt)]
        else:
            self._messages = []

    def clear_all(self) -> None:
        """完全清空（包括系统提示词）"""
        self._messages = []

    def _trim_if_needed(self) -> None:
        """
        检查并裁剪消息（如果超过限制）
        
        【裁剪策略】
        1. 先检查总 Token 数是否超标
        2. 再检查轮数是否超标
        3. 从最旧的非 system 消息开始删除（保留 system + 最近的消息）
        """
        while self._should_trim():
            oldest_non_system_idx = None
            
            for i, msg in enumerate(self._messages):
                if msg.role != "system":
                    oldest_non_system_idx = i
                    break
                    
            if oldest_non_system_idx is not None:
                removed = self._messages.pop(oldest_non_system_idx)

    def _should_trim(self) -> bool:
        """判断是否需要裁剪"""
        non_system_count = len([m for m in self._messages if m.role != "system"])
        rounds = non_system_count // 2
        
        token_estimate = self.estimate_tokens()
        
        return rounds > self._max_rounds or token_estimate > self._max_tokens

    def estimate_tokens(self) -> int:
        """
        预估当前消息的总 Token 数
        
        【估算规则】（中文场景）
        - 1个中文字符 ≈ 1.5 tokens
        - 1个英文单词 ≈ 1.3 tokens
        - 这里简化为：字符数 / 1.5 ≈ token 数
        """
        total_chars = sum(len(msg.content) for msg in self._messages)
        return int(total_chars / 1.5)

    def get_stats(self) -> MemoryStats:
        """获取记忆统计信息"""
        user_count = sum(1 for m in self._messages if m.role == "user")
        assistant_count = sum(1 for m in self._messages if m.role == "assistant")
        non_system_count = user_count + assistant_count
        rounds = non_system_count // 2
        
        return MemoryStats(
            total_messages=len(self._messages),
            user_messages=user_count,
            assistant_messages=assistant_count,
            estimated_tokens=self.estimate_tokens(),
            window_size=rounds
        )

    @property
    def message_count(self) -> int:
        """消息总数"""
        return len(self._messages)

    @property
    def round_count(self) -> int:
        """对话轮数（每轮=用户+AI各一条）"""
        non_system = [m for m in self._messages if m.role != "system"]
        return len(non_system) // 2

    def __len__(self) -> int:
        """支持 len(memory) 语法"""
        return len(self._messages)

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"ShortTermMemory("
            f"messages={stats.total_messages}, "
            f"rounds={stats.window_size}, "
            f"tokens≈{stats.estimated_tokens})"
        )


class ShortTermMemoryManager:
    """
    短期记忆管理器（多会话支持）
    
    【职责】
    - 管理多个会话的短期记忆实例
    - 提供统一的创建/获取/销毁接口
    - 类似连接池的概念
    
    【使用场景】
    Python 服务可能同时处理多个用户的面试请求
    每个用户需要一个独立的 ShortTermMemory 实例
    """

    def __init__(self):
        self._memories: Dict[str, ShortTermMemory] = {}

    def create_memory(
        self,
        session_id: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> ShortTermMemory:
        """为指定会话创建新的短期记忆"""
        memory = ShortTermMemory(system_prompt=system_prompt, **kwargs)
        self._memories[session_id] = memory
        return memory

    def get_memory(self, session_id: str) -> Optional[ShortTermMemory]:
        """获取指定会话的短期记忆"""
        return self._memories.get(session_id)

    def get_or_create(
        self,
        session_id: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> ShortTermMemory:
        """获取或创建（如果不存在）"""
        memory = self._memories.get(session_id)
        if not memory:
            memory = self.create_memory(session_id, system_prompt, **kwargs)
        return memory

    def remove_memory(self, session_id: str) -> bool:
        """移除指定会话的记忆"""
        if session_id in self._memories:
            del self._memories[session_id]
            return True
        return False

    def clear_all(self) -> None:
        """清空所有会话记忆"""
        self._memories.clear()

    def get_active_sessions(self) -> List[str]:
        """获取所有活跃会话ID列表"""
        return list(self._memories.keys())

    def __contains__(self, session_id: str) -> bool:
        """支持 'session_id' in manager 语法"""
        return session_id in self._memories


_memory_manager_instance: Optional[ShortTermMemoryManager] = None


def get_short_term_memory_manager() -> ShortTermMemoryManager:
    """获取全局单例"""
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = ShortTermMemoryManager()
    return _memory_manager_instance


def reset_memory_manager():
    """重置单例（测试用）"""
    global _memory_manager_instance
    _memory_manager_instance = None
