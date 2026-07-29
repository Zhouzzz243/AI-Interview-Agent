"""
LLM 客户端模块 - 智谱AI GLM-4 封装

【Java 类比】
- 类似封装了 OpenFeign / RestTemplate 的 HTTP 调用
- 或者类似 @Service 注解的 LlmService
- 职责：统一管理与智谱AI的所有交互

【Python 特性说明】
1. zhipuai SDK: 智谱官方提供的 Python SDK（类似 Java 的 OpenAI Java SDK）
2. 异步编程: 使用 async/await（类似 Java 的 CompletableFuture）
3. 上下文管理器: with 语句管理资源（类似 try-with-resources）
4. 类型提示: Type hints 提供IDE自动补全（类似 Java 泛型）

【设计模式】
- 单例模式: 通过依赖注入全局共享一个客户端实例
- 策略模式: 不同模型调用使用相同接口
- 装饰器模式: logging 包装实际调用

【使用示例】
from app.tools.llm_client import LLMClient, get_llm_client

# 方式1: 直接实例化
client = LLMClient()
response = await client.chat("你好")

# 方式2: 全局单例（推荐）
client = get_llm_client()
response = await client.chat("解释HashMap原理")

# 流式输出
async for chunk in client.chat_stream("写一段自我介绍"):
    print(chunk, end="", flush=True)
"""

import asyncio
from typing import Optional, List, Dict, Any, AsyncGenerator
from dataclasses import dataclass, field

import zhipuai
from zhipuai import ZhipuAI

from app.infrastructure.config import get_settings
from app.infrastructure.logger import get_logger
from app.infrastructure.error_handler import LLMCallError, LLMTimeoutError

logger = get_logger(__name__)


@dataclass
class Message:
    """
    对话消息模型

    【Java 类比】
    - 类似 Record 或 DTO 类
    - 用于构建对话上下文（类似 ChatGPT 的 messages 数组）

    【角色说明】
    - system: 系统提示词，定义AI的行为和约束
    - user: 用户输入的消息
    - assistant: AI 的回复（用于多轮对话历史）
    """

    role: str                    # 角色: system / user / assistant
    content: str                 # 消息内容

    def to_dict(self) -> Dict[str, str]:
        """转换为字典格式（zhipuai SDK 需要的格式）"""
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    """
    LLM 响应结果封装

    【Java 类比】
    - 类似 ResponseEntity<String> 或自定义 Result<T>
    - 统一包装返回值，包含元数据

    【字段说明】
    - content: 生成的文本内容
    - model: 实际使用的模型名称
    - usage: Token 用量统计（计费依据）
    - finish_reason: 结束原因（stop=正常结束 / length=达到长度限制）
    """

    content: str                 # 生成的文本内容
    model: str = ""              # 使用的模型名称
    prompt_tokens: int = 0       # 输入 Token 数
    completion_tokens: int = 0   # 输出 Token 数
    total_tokens: int = 0        # 总 Token 数
    finish_reason: str = ""      # 结束原因
    request_id: str = ""         # 请求ID（用于追踪和调试）
    latency_ms: float = 0.0      # 响应延迟（毫秒）

    def __str__(self) -> str:
        return f"LLMResponse(content={self.content[:50]}..., tokens={self.total_tokens})"


class LLMClient:
    """
    智谱AI GLM-4 客户端核心类

    【Java 类比】
    ```java
    @Service
    public class LlmServiceImpl implements LlmService {
        @Value("${zhipuai.api.key}")
        private String apiKey;

        @Autowired
        private RestTemplate restTemplate;

        // 相当于 Python 的 chat() 方法
        public String chat(String prompt) { ... }
    }
    ```

    【核心功能】
    1. chat(): 同步/异步单次对话
    2. chat_stream(): 流式输出（打字机效果）
    3. chat_with_history(): 多轮对话（携带上下文）
    4. build_system_prompt(): 构建系统提示词

    【线程安全】
    - ZhipuAI 实例是线程安全的（内部使用连接池）
    - 可以在多个协程之间共享同一个实例
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化 LLM 客户端

        【参数说明】
        - api_key: 智谱AI API Key（可选，默认从配置读取）

        【Java 类比】
        - 类似 @PostConstruct 或构造函数注入
        - 如果不传参，从配置中心读取（类似 @Value 注解）
        
        【优先级】
        1. 直接传入的 api_key 参数
        2. 环境变量 ZHIPUAI_API_KEY
        3. 配置文件 settings.llm.api_key
        """
        import os
        
        env_api_key = os.getenv("ZHIPUAI_API_KEY", "")
        env_model = os.getenv("ZHIPUAI_MODEL", "")
        
        if api_key:
            self._api_key = api_key
        elif env_api_key and env_api_key != 'your_api_key_here':
            self._api_key = env_api_key
        else:
            settings = get_settings()
            self._api_key = settings.llm.api_key
            self._model = settings.llm.model
            self._temperature = settings.llm.temperature
            self._max_tokens = settings.llm.max_tokens
            self._timeout = settings.llm.timeout
            
            if not self._api_key or self._api_key == 'your_api_key_here':
                logger.warning(
                    "llm_not_configured",
                    action="请设置 ZHIPUAI_API_KEY 环境变量",
                    hint="在 .env 文件中填入你的智谱API Key"
                )
                return
        
        try:
            settings = get_settings()
            self._model = env_model or settings.llm.model
            self._temperature = settings.llm.temperature
            self._max_tokens = settings.llm.max_tokens
            self._timeout = settings.llm.timeout
        except Exception:
            self._model = env_model or "glm-4.7"
            self._temperature = 0.7
            self._max_tokens = 2000
            self._timeout = 30

        self._client: Optional[ZhipuAI] = None

    def _get_client(self) -> ZhipuAI:
        """
        获取或创建 ZhipuAI 客户端实例（懒加载单例）

        【设计模式】
        - 懒加载: 第一次调用时才创建实例
        - 单例: 整个应用只创建一个客户端实例

        【Java 类比】
        - 类似 @Bean + @Scope("singleton") + 双重检查锁
        - 或 Spring 的 Lazy Initialization
        """
        if self._client is None:
            self._client = ZhipuAI(api_key=self._api_key)
            logger.info(
                "llm_client_initialized",
                model=self._model,
                temperature=self._temperature
            )
        return self._client

    async def chat(
        self,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        history: Optional[List[Message]] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Dict] = None
    ) -> LLMResponse:
        """
        发送聊天请求（非流式）

        【Java 类比】
        ```java
        // 类似 CompletableFuture.supplyAsync()
        public CompletableFuture<String> chatAsync(String prompt) {
            return CompletableFuture.supplyAsync(() -> {
                // HTTP 调用 LLM API
                return restTemplate.postForObject(url, request, String.class);
            });
        }
        ```

        【参数说明】
        - prompt: 用户输入的问题或指令（方式1）
        - system_prompt: 系统提示词（定义AI角色和行为）
        - temperature: 温度参数（0=严谨 1=创意），None则用默认值
        - history: 历史对话记录（用于多轮对话上下文）（方式1）
        - messages: 完整的消息列表（方式2，与OpenAI SDK兼容）
        - response_format: 响应格式（如{"type": "json_object"}）

        【调用方式】
        方式1（推荐）:
            client.chat(prompt="你好", system_prompt="你是助手")
        
        方式2（兼容OpenAI格式）:
            client.chat(
                system_prompt="你是助手",
                messages=[{"role": "user", "content": "你好"}],
                response_format={"type": "json_object"}
            )

        【返回值】
        - LLMResponse: 包含生成内容、Token用量、延迟等

        【异常处理】
        - LLMCallError: API 调用失败
        - LLMTimeoutError: 请求超时
        - 由 RetryPolicy 统一处理

        【使用示例】
        # 简单调用
        response = await client.chat("解释 HashMap 的底层实现")
        print(response.content)

        # 带系统提示词
        response = await client.chat(
            prompt="评价这段代码",
            system_prompt="你是一个严格的代码审查专家"
        )

        # 多轮对话（方式1）
        history = [
            Message(role="user", content="什么是JVM?"),
            Message(role="assistant", content="JVM是Java虚拟机..."),
        ]
        response = await client.chat(
            prompt="那JVM内存结构呢？",
            history=history
        )
        
        # 使用messages参数（方式2）
        response = await client.chat(
            system_prompt="你是面试官",
            messages=[{"role": "user", "content": "请评分"}],
            response_format={"type": "json_object"}
        )
        """
        import time
        start_time = time.time()

        client = self._get_client()

        if messages:
            final_messages = list(messages)
            if system_prompt:
                final_messages.insert(0, {"role": "system", "content": system_prompt})
            logger.debug("using_messages_param", message_count=len(final_messages))
        else:
            final_messages = self._build_messages(prompt, system_prompt, history)

        try:
            create_kwargs = {
                "model": self._model,
                "messages": final_messages,
                "temperature": temperature or self._temperature,
                "max_tokens": self._max_tokens
            }
            
            if response_format:
                logger.debug("response_format_provided", format=response_format)
                try:
                    import inspect
                    sig = inspect.signature(client.chat.completions.create)
                    if 'response_format' in sig.parameters:
                        create_kwargs["response_format"] = response_format
                    else:
                        logger.warning(
                            "response_format_not_supported",
                            action="SDK不支持此参数，已忽略",
                            hint="可通过Prompt模板要求返回JSON格式"
                        )
                except Exception as e:
                    logger.warning("response_format_check_failed", error=str(e))

            response = await asyncio.to_thread(
                client.chat.completions.create,
                **create_kwargs
            )

            result = LLMResponse(
                content=response.choices[0].message.content.strip(),
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                finish_reason=response.choices[0].finish_reason,
                request_id=response.id,
                latency_ms=(time.time() - start_time) * 1000
            )

            logger.info(
                "llm_chat_success",
                model=result.model,
                tokens=result.total_tokens,
                latency_ms=result.latency_ms,
                prompt_length=len(prompt or messages[-1].get("content", "")[:50] if messages else "")
            )

            return result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(
                "llm_chat_failed",
                error=str(e),
                error_type=type(e).__name__,
                latency_ms=latency_ms
            )
            raise LLMCallError(f"LLM调用失败: {e}", detail=str(e))

    async def chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        history: Optional[List[Message]] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天请求（逐块返回内容）

        【Java 类比】
        ```java
        // 类似 Flux<String> 或 SSE (Server-Sent Events)
        public Flux<String> chatStream(String prompt) {
            return Flux.create(sink -> {
                // 逐块推送内容
                while (hasMoreChunks()) {
                    sink.next(nextChunk());
                }
                sink.complete();
            });
        }
        ```

        【为什么需要流式？】
        1. **用户体验**: 打字机效果，不用等全部生成完
        2. **首字时间(TTFB)**: 更快显示第一个字符
        3. **长文本场景**: 面试反馈可能很长，流式更友好
        4. **资源释放**: 边生成边传输，减少内存占用

        【使用方式】
        # 异步迭代（推荐用于 WebSocket 推送）
        async for chunk in client.chat_stream("写一段自我介绍"):
            # chunk 是一小段文本
            ws.send(chunk)

        # 收集全部内容
        full_response = ""
        async for chunk in client.chat_stream("解释HashMap"):
            full_response += chunk
            print(chunk, end="", flush=True)
        """
        client = self._get_client()
        messages = self._build_messages(prompt, system_prompt, history)

        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=self._model,
                messages=messages,
                temperature=temperature or self._temperature,
                max_tokens=self._max_tokens,
                stream=True
            )

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield content

        except Exception as e:
            logger.error("llm_stream_failed", error=str(e))
            raise LLMCallError(f"LLM流式调用失败: {e}", detail=str(e))

    async def chat_with_context(
        self,
        user_message: str,
        context: Dict[str, Any],
        phase: str = "general"
    ) -> LLMResponse:
        """
        带业务上下文的聊天（面试专用）

        【Java 类比】
        ```java
        // 类似带 RequestBody 的 Controller 方法
        @PostMapping("/chat")
        public Result<ChatVO> chatWithContext(
            @RequestBody ChatRequest request,
            @RequestAttribute("context") InterviewContext context
        ) { ... }
        ```

        【参数说明】
        - user_message: 用户的消息内容
        - context: 业务上下文字典，包含：
            - resume_info: 简历信息
            - current_phase: 当前阶段
            - scores: 历史得分
            - conversation_history: 对话历史
            - rag_references: RAG检索到的参考答案
        - phase: 当前面试阶段（影响系统提示词选择）

        【使用场景】
        - 面试官提问时传入简历上下文
        - 打分时传入标准答案参考
        - 追问决策时传入历史表现
        """
        system_prompt = self._build_interview_system_prompt(phase, context)

        history_messages = []
        if "conversation_history" in context:
            for turn in context["conversation_history"][-6:]:
                history_messages.append(Message(role="user", content=turn.get("question", "")))
                history_messages.append(Message(role="assistant", content=turn.get("answer", "")))

        return await self.chat(
            prompt=user_message,
            system_prompt=system_prompt,
            history=history_messages if history_messages else None
        )

    def _build_messages(
        self,
        prompt: str,
        system_prompt: Optional[str],
        history: Optional[List[Message]]
    ) -> List[Dict[str, str]]:
        """
        构建消息列表（zhipuai SDK 格式）

        【格式要求】
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "..."}
        ]

        【规则】
        1. system 消息必须在最前面（只能有一个）
        2. user 和 assistant 必须交替出现
        3. 最后一条必须是 user 消息
        """
        messages = []

        if system_prompt:
            messages.append(Message(role="system", content=system_prompt).to_dict())

        if history:
            for msg in history:
                messages.append(msg.to_dict())

        messages.append(Message(role="user", content=prompt).to_dict())

        return messages

    def _build_interview_system_prompt(
        self,
        phase: str,
        context: Dict[str, Any]
    ) -> str:
        """
        构建面试专用的系统提示词

        【根据阶段动态选择不同的 Prompt】

        【阶段映射】
        - self_intro: 自我介绍引导
        - project_qa: 项目深挖
        - internship_qa: 实习经历
        - eight_part_qa: 八股文（严格按标准答案）
        - scenario_qa: 场景题
        - coding_qa: 算法题
        - hr_round: HR面
        """
        base_prompt = f"""你是一位专业的技术面试官，正在进行{phase}阶段的面试。

【面试规则】
1. 根据候选人的回答给出专业、有深度的追问
2. 回答优秀时要给予肯定，回答不足时要温和引导
3. 不要一次性抛出太多问题，一次只问一个重点
4. 保持对话自然流畅，像真实的面试场景
5. 用中文回复"""

        if phase == "eight_part_qa" and "rag_references" in context:
            refs = context.get("rag_references", [])
            if refs:
                ref_text = "\n".join([f"- {r}" for r in refs[:3]])
                base_prompt += f"\n\n【参考资料（可作为评分参考）】\n{ref_text}"

        if "resume_info" in context:
            resume = context["resume_info"]
            skills = resume.get("skills", [])
            if skills:
                skill_str = ", ".join([s.get("category", "") + ":" + ",".join(s.get("items", [])) for s in skills[:3]])
                base_prompt += f"\n\n【候选人技能栈】\n{skill_str}"

        return base_prompt


# ══════════════════════════════════════════════════════════
# 全局单例工厂函数（类似 Spring 的 @Bean）
# ══════════════════════════════════════════════════════════

_llm_client_instance: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """
    获取全局 LLM 客户端单例

    【Java 类比】
    ```java
    @Bean
    @Scope("singleton")
    public LlmClient llmClient() {
        return new LlmClient();
    }

    // 使用时通过 @Autowired 注入
    @Autowired
    private LlmClient llmClient;
    ```

    【Python 特性】
    - 模块级变量作为单例缓存
    - 延迟初始化（第一次调用时才创建）
    - 线程安全（CPython GIL 保证）

    【使用方式】
    from app.tools.llm_client import get_llm_client

    client = get_llm_client()
    response = await client.chat("你好")
    """
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = LLMClient()
    return _llm_client_instance


def reset_llm_client():
    """
    重置 LLM 客户端（测试用）

    【使用场景】
    - 单元测试中需要 Mock 客户端
    - 切换 API Key 时重新初始化
    """
    global _llm_client_instance
    _llm_client_instance = None
