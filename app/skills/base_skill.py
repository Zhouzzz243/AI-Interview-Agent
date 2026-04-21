"""
基础技能抽象类

【Java 类比】
- 类似 abstract class 或 interface
- 定义所有 Skill 的通用接口和公共方法
- 提供模板方法模式（Template Method Pattern）

【设计原则】
1. 所有具体的 Skill 都继承此类
2. 统一的执行入口: execute()
3. 统一的错误处理和日志记录
4. 支持依赖注入（LLM、Memory等）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass

from app.infrastructure.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SkillResult:
    """
    技能执行结果（统一返回格式）
    
    【Java 类比】
    类似 Result<T> 或 Response<T> 包装类
    
    【属性说明】
    - success: 是否执行成功
    - data: 业务数据（根据不同Skill类型而异）
    - error: 错误信息（失败时）
    - metadata: 元数据（用于调试和分析）
    """
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: Optional[Dict] = None
    
    @classmethod
    def ok(cls, data: Any, **metadata) -> 'SkillResult':
        """创建成功结果"""
        return cls(success=True, data=data, metadata=metadata or {})
    
    @classmethod
    def fail(cls, error: str, **metadata) -> 'SkillResult':
        """创建失败结果"""
        return cls(success=False, error=error, metadata=metadata or {})


class BaseSkill(ABC):
    """
    基础技能抽象类
    
    【Java 类比】
    ```java
    public abstract class BaseSkill {
        protected LLMClient llmClient;
        protected MemoryManager memory;
        
        public BaseSkill(LLMClient llmClient, MemoryManager memory) {
            this.llmClient = llmClient;
            this.memory = memory;
        }
        
        // 模板方法：定义算法骨架
        public final SkillResult execute(String sessionId, Map<String, Object> context) {
            try {
                // 1. 前置校验
                this.validate(context);
                // 2. 执行具体逻辑
                Object result = this.doExecute(sessionId, context);
                // 3. 后置处理
                this.postProcess(result);
                return SkillResult.ok(result);
            } catch (Exception e) {
                return SkillResult.fail(e.getMessage());
            }
        }
        
        protected abstract Object doExecute(String sessionId, Map<String, Object> context);
    }
    ```
    
    【使用示例】
    ```python
    class ResumeSkill(BaseSkill):
        def do_execute(self, session_id, context):
            resume_text = context['resume_text']
            # 解析简历...
            return parsed_result
    """
    
    def __init__(self):
        self._name = self.__class__.__name__
        logger.info("skill_initialized", skill_name=self._name)
    
    @property
    def name(self) -> str:
        """获取技能名称"""
        return self._name
    
    async def execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> SkillResult:
        """
        执行技能（模板方法模式）
        
        【执行流程】
        1. validate() → 前置校验
        2. do_execute() → 具体业务逻辑（子类实现）
        3. post_process() → 后置处理
        
        【参数】
        - session_id: 会话ID
        - context: 上下文数据（包含输入参数）
        - kwargs: 额外参数
        
        【返回】统一格式的 SkillResult
        """
        try:
            logger.info(
                "skill_execution_started",
                skill_name=self._name,
                session_id=session_id
            )
            
            await self.validate(session_id, context)
            
            result = await self.do_execute(session_id, context, **kwargs)
            
            await self.post_process(session_id, result, context)
            
            logger.info(
                "skill_execution_completed",
                skill_name=self._name,
                session_id=session_id,
                success=True
            )
            
            return SkillResult.ok(data=result)
            
        except ValueError as ve:
            logger.warning(
                "skill_validation_failed",
                skill_name=self._name,
                session_id=session_id,
                error=str(ve)
            )
            return SkillResult.fail(error=f"校验失败: {str(ve)}")
            
        except Exception as e:
            logger.error(
                "skill_execution_failed",
                skill_name=self._name,
                session_id=session_id,
                error=str(e),
                exc_info=True
            )
            return SkillResult.fail(error=f"执行异常: {str(e)}")
    
    async def validate(
        self,
        session_id: str,
        context: Dict[str, Any]
    ) -> None:
        """
        前置校验（子类可重写）
        
        【默认行为】检查必要字段是否存在
        【可重写】添加自定义校验逻辑
        
        【抛出】ValueError 校验不通过时
        """
        if not session_id:
            raise ValueError("session_id 不能为空")
        if not context:
            raise ValueError("context 不能为空")
    
    @abstractmethod
    async def do_execute(
        self,
        session_id: str,
        context: Dict[str, Any],
        **kwargs
    ) -> Any:
        """
        具体业务逻辑（必须由子类实现）
        
        【这是核心方法！每个Skill的主要逻辑都在这里】
        """
        pass
    
    async def post_process(
        self,
        session_id: str,
        result: Any,
        context: Dict[str, Any]
    ) -> None:
        """
        后置处理（子类可重写）
        
        【用途】
        - 记录日志
        - 更新统计信息
        - 触发后续动作
        """
        pass
    
    def __repr__(self):
        return f"<{self._name}>"
