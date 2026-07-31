"""
面试编排器（Interview Orchestrator）- Agent的核心调度中心

【Java 类比】
- 类似 @Service 注解的 InterviewFacadeServiceImpl
- 或者类似 Spring 的 @Service 层 + 策略模式的组合
- 职责：串联所有Skill，控制面试流程，管理会话状态

【核心职责】
1. 🔗 串联Skills：决定调用顺序和数据流转
2. 📦 数据组装：把上一个Skill的输出作为下一个的输入
3. 📝 状态维护：更新Redis中的SessionState
4. 🎯 流程控制：判断何时追问、何时出下一题、何时切换阶段

【横切关注点 → 已抽离到 Harness 层】
- 🛡️ 错误处理   → app/harness/retry.py  (指数退避重试)
- 💰 预算控制   → app/harness/budget.py (三层预算)
- 🔒 输出校验   → app/harness/guard.py  (白名单+参数校验)

【设计模式】
- Facade模式：对外提供统一入口，隐藏内部复杂性
- Template Method：定义面试流程骨架（评分→决策→出题）
- Strategy模式：根据阶段选择不同的Skill组合

【4个核心方法】
1. start_interview()   → 开始面试（初始化+第一题）
2. chat()              → 对话交互（评分+追问/出新题）⭐ 最核心
3. end_interview()     → 结束评分（综合评估）
4. parse_resume()      → 简历解析

【调用关系图】
Java端 ──HTTP──→ Router(Step11) ──调用──→ Orchestrator(本文件)
                                         │
              ┌──────────────────────────┼──────────────────────┐
              ▼                          ▼                      ▼
        MemoryManager              ScoringSkill           FollowUpSkill
        (Redis+内存)              (LLM评分)              (追问决策)
              │                          │                      │
              ▼                          ▼                      ▼
        SessionStore               LLMClient              LLMClient
        ShortTermMemory           [Harness:Retry]     InterviewSkill
                                  [Harness:Guard]
                                  [Harness:Budget]
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import json

import httpx

from app.infrastructure.logger import get_logger
from app.infrastructure.config import get_settings, InterviewSettings
from app.memory.memory_manager import MemoryManager, get_memory_manager
from app.skills.scoring_skill import ScoringSkill
from app.skills.followup_skill import FollowUpSkill
from app.skills.interview_skill import InterviewSkill
from app.skills.resume_skill import ResumeSkill
from app.skills.chat_mode_handler import ChatModeHandlerSkill
from app.api.schemas import (
    InterviewPhase,
    ChatResponse,
    FollowUpDecision,
    FinalScoreResult,
    DimensionScore,
    StartInterviewRequest,
    ChatRequest
)
# ── Harness 层依赖注入 ──
from app.harness.budget import InterviewBudget, get_interview_budget
from app.harness.guard import InterviewGuard, get_interview_guard
from app.harness.retry import RetryPolicy, RetryPresets

logger = get_logger(__name__)


class InterviewOrchestrator:
    """
    面试编排器 - Agent的大脑
    
    【Java类比】
    ```java
    @Service
    public class InterviewOrchestrator {
        // 业务依赖
        @Autowired private MemoryManager memoryManager;
        @Autowired private ScoringSkill scoringSkill;
        @Autowired private FollowUpSkill followupSkill;
        @Autowired private InterviewSkill interviewSkill;
        @Autowired private ResumeSkill resumeSkill;
        
        // Harness 层横切依赖
        @Autowired private InterviewBudget budget;
        @Autowired private InterviewGuard guard;
        @Autowired private RetryPolicy retryPolicy;
    }
    ```
    
    【单例模式】整个应用只创建一个实例（类似Spring的Singleton）
    """
    
    def __init__(self):
        """
        初始化编排器 - 注入所有依赖
        
        【Java类比】构造函数注入
        """
        logger.info("orchestrator_initializing")
        
        # ── 业务依赖 ──
        self._memory_manager: MemoryManager = get_memory_manager()
        self._scoring_skill: ScoringSkill = ScoringSkill()
        self._followup_skill: FollowUpSkill = FollowUpSkill()
        self._interview_skill: InterviewSkill = InterviewSkill()
        self._resume_skill: ResumeSkill = ResumeSkill()
        self._chat_mode_handler: ChatModeHandlerSkill = ChatModeHandlerSkill()
        self._settings: InterviewSettings = InterviewSettings()
        
        # ── Harness 层横切依赖 ──
        self._budget: InterviewBudget = get_interview_budget()
        self._guard: InterviewGuard = get_interview_guard()
        self._retry: RetryPolicy = RetryPresets.llm_call()
        
        logger.info(
            "orchestrator_initialized",
            components=[
                "MemoryManager",
                "ScoringSkill",
                "FollowUpSkill", 
                "InterviewSkill",
                "ResumeSkill",
                "ChatModeHandlerSkill",
                # Harness 层
                "InterviewBudget",
                "InterviewGuard",
                "RetryPolicy",
            ]
        )
    
    async def start_interview(
        self,
        session_id: str,
        resume_id: str
    ) -> Dict[str, Any]:
        """
        开始面试 - 初始化会话并生成第一道题
        
        【对应链路】链路2: 开始面试
        【触发时机】用户点击"开始面试"按钮后，Java调用此方法
        
        【执行流程】
        ① 在Redis中创建SessionState（TTL=7200秒）
        ② 从MySQL查询简历内容（parsed_content字段）
        ③ 解析简历JSON得到结构化数据
        ④ 调用InterviewSkill生成第一阶段(self_introduction)题目
        ⑤ 更新Redis中的question_count=1
        ⑥ 返回第一道题
        
        【参数】
        - session_id: 面试会话ID（Java生成的自增主键）
        - resume_id: 已解析的简历ID
        
        【返回值】
        {
            "code": 200,
            "question": "请先简单介绍一下你自己"
        }
        
        【异常处理】
        - Redis连接失败 → 返回错误码500
        - 简历不存在/未解析 → 返回错误码400
        - LLM调用失败 → 返回错误码503
        """
        logger.info(
            "start_interview_called",
            session_id=session_id,
            resume_id=resume_id
        )
        
        try:
            # ===== 步骤①: 创建Redis会话状态 =====
            create_success = await self._memory_manager.create_session(
                session_id=session_id,
                user_id="",  # Java端会在后续提供，这里先留空
                resume_id=resume_id,
                phase=InterviewPhase.SELF_INTRO
            )
            
            if not create_success:
                logger.error("start_interview_session_create_failed", session_id=session_id)
                return {"code": 500, "error": "无法创建面试会话"}
            
            logger.info("session_created_in_redis", session_id=session_id)
            
            # ===== 步骤②③: 从Java端加载简历数据 =====
            resume_data = await self._load_resume_from_db(resume_id)
            
            # 将简历数据保存到会话状态，供后续出题使用
            await self._memory_manager.update_session_field(
                session_id=session_id,
                field="resume_data",
                value=resume_data
            )

            # ===== Harness: 启动预算追踪 =====
            self._budget.reset_turn(session_id)
            if not self._budget.can_continue(session_id):
                logger.warning("start_interview_budget_exhausted", session_id=session_id)
                return {"code": 503, "error": "面试额度已用完，无法开始新面试"}

            # ===== 步骤④: 生成第一道题 =====
            question_result = await self._retry.execute(
                self._interview_skill.execute,
                session_id=session_id,
                context={
                    "phase": InterviewPhase.SELF_INTRO,
                    "resume_data": resume_data,
                    "question_count": 0,
                    "asked_questions": []
                }
            )
            
            if not question_result.success:
                logger.error(
                    "start_interview_question_generation_failed",
                    error=question_result.error
                )
                return {"code": 503, "error": f"AI服务暂时不可用: {question_result.error}"}
            
            generated_question = question_result.data
            question_text = generated_question.get("question", "")

            # ── Harness: Budget 记账 ──
            estimated_tokens = self._budget.estimate_tokens(question_text)
            self._budget.track_llm_call(session_id, tokens_used=estimated_tokens)
            
            # ===== 步骤⑤: 更新Redis状态 =====
            await self._memory_manager.record_assistant_message(
                session_id=session_id,
                content=question_text,
                metadata={
                    "phase": InterviewPhase.SELF_INTRO.value,
                    "question_type": "self_introduction",
                    "is_first_question": True
                }
            )
            
            # 更新题目计数
            session_state = await self._memory_manager.get_session(session_id)
            if session_state:
                await self._memory_manager.update_session_field(
                    session_id=session_id,
                    field="question_count",
                    value=1
                )
            
            logger.info(
                "start_interview_success",
                session_id=session_id,
                first_question_length=len(question_text)
            )
            
            # ===== 步骤⑥: 返回结果 =====
            return {
                "code": 200,
                "question": question_text
            }
            
        except Exception as e:
            logger.exception(
                "start_interview_unexpected_error",
                session_id=session_id,
                error=str(e)
            )
            return {"code": 500, "error": f"服务器内部错误: {str(e)}"}
    
    async def chat(
        self,
        session_id: str,
        user_answer: str
    ) -> Dict[str, Any]:
        """
        处理单轮对话 - 评分 + 追问决策 + 生成下一题 ⭐⭐⭐ 最核心！
        
        【对应链路】链路3: 对话交互（循环执行N次）
        【触发时机】每次候选人回答一道题并点击发送
        
        【执行流程（7步）】
        ① 从Redis加载SessionState
        ② 将用户回答加入短期记忆窗口（供LLM参考上下文）
        ③ 调用ScoringSkill对当前回答进行多维度评分
        ④ 调用FollowUpSkill进行三层追问决策
        ⑤ 根据决策结果决定下一题内容（追问 or 新题 or 切阶段）
        ⑥ 更新Redis中的SessionState（分数/配额/阶段/计数）
        ⑦ 构建ChatResponse返回（8个字段 + decision子对象）
        
        【参数】
        - session_id: 面试会话ID
        - user_answer: 候选人对上一道题的回答文本
        
        【返回值】ChatResponse（8个字段）:
        {
            "code": 200,
            "data": {
                "score": 82,                      # int 0-100
                "feedback": "自我介绍清晰...",     # string
                "nextQuestion": "你刚才提到...",   # string
                "phase": "self_introduction",      # enum
                "isFollowUp": true,               # bool
                "questionCount": 1,               # int (含追问)
                "remainingQuestions": 14,         # int (不含追问)
                "decision": {                     # object (可选)
                    "decision": "follow_up",       # follow_up/interest_follow_up/next_question/phase_switch
                    "reason": "...",
                    "confidence": 0.85             # float 0.0-1.0
                }
            }
        }
        
        【三层决策机制详解】
        第一层 _quick_check(): 规则过滤
          - score ∈ [75,89] → 有深挖空间
          - score >= 90 + 高价值信号 → interest_follow_up  
          - score < 75 或已充分回答 → next_question
          
        第二层 _llm_decision(): LLM智能决策
          - 分析回答质量、技术深度、是否有亮点
          - 决定是否追问以及追问方向
          
        第三层: 资源约束检查
          - 本题已追问次数 < 2?
          - 总剩余配额 > 0?
          - 连续低分次数 < 2?
        """
        logger.info(
            "chat_called",
            session_id=session_id,
            answer_length=len(user_answer)
        )
        
        try:
            # ===== Harness: 重置本轮预算计数器 =====
            self._budget.reset_turn(session_id)
            
            # ===== Harness: 预算检查 =====
            if not self._budget.can_continue(session_id):
                budget = self._budget.get_status(session_id)
                logger.warning(
                    "chat_budget_exhausted",
                    session_id=session_id,
                    reason=budget.exhausted_reason.value if budget and budget.exhausted_reason else "unknown"
                )
                return self._budget.build_degraded_response(session_id)
            
            # ===== 步骤①: 加载SessionState =====
            session_state = await self._memory_manager.get_session(session_id)
            
            if not session_state:
                logger.error("chat_session_not_found", session_id=session_id)
                return {"code": 404, "error": "面试会话不存在或已过期"}
            
            current_phase = InterviewPhase(session_state.get("phase", "self_introduction"))
            question_count = session_state.get("question_count", 0)
            follow_up_budget = session_state.get("follow_up_budget", self._settings.followup_budget)
            
            # 获取上一道题（从短期记忆中取最后一条AI消息）
            last_ai_content = self._get_last_ai_question(session_id)
            
            logger.info(
                "chat_session_loaded",
                session_id=session_id,
                current_phase=current_phase.value,
                question_count=question_count,
                follow_up_budget=follow_up_budget
            )
            
            # ===== 步骤②: 加入短期记忆 =====
            await self._memory_manager.record_user_message(
                session_id=session_id,
                content=user_answer,
                metadata={"phase": current_phase.value}
            )
            
            # ===== 闲聊模式特殊处理（CHAT_MODE 阶段）=====
            if current_phase == InterviewPhase.CHAT_MODE:
                return await self._handle_chat_mode(
                    session_id=session_id,
                    user_answer=user_answer,
                    session_state=session_state,
                    question_count=question_count
                )
            
            # ===== 步骤③: ScoringSkill评分 =====
            scoring_context = {
                "question": last_ai_content or "",
                "answer": user_answer,
                "category": self._phase_to_category(current_phase),
                "phase": current_phase.value
            }
            
            scoring_result = await self._retry.execute(
                self._scoring_skill.execute,
                session_id=session_id,
                context=scoring_context
            )
            
            if not scoring_result.success:
                logger.error("chat_scoring_failed", error=scoring_result.error)
                return {"code": 503, "error": f"评分服务暂不可用: {scoring_result.error}"}
            
            score_data = scoring_result.data
            raw_score = score_data.get("score", 70)
            
            # ── Harness: Guard 净化评分 ──
            current_score, score_valid = self._guard.sanitize_score(raw_score)
            if not score_valid:
                logger.info("chat_score_sanitized_by_guard", raw=raw_score, sanitized=current_score)
            
            feedback = score_data.get("feedback", "")
            
            # ── Harness: Budget 记账（估算本次评分调用的 token）──
            estimated_tokens = self._budget.estimate_tokens(
                str(scoring_context.get("answer", "")) + str(feedback)
            )
            self._budget.track_llm_call(session_id, tokens_used=estimated_tokens)
            
            logger.info(
                "chat_scoring_completed",
                session_id=session_id,
                score=current_score,
                category=scoring_context["category"]
            )
            
            # ===== 步骤④: FollowUpSkill三层决策 =====
            followup_context = {
                "current_phase": current_phase.value,
                "question_text": last_ai_content or "",
                "answer_text": user_answer,
                "feedback": feedback,
                "current_score": current_score
            }
            
            decision_result = await self._retry.execute(
                self._followup_skill.execute,
                session_id=session_id,
                context=followup_context
            )
            
            if not decision_result.success:
                logger.warning("chat_followup_decision_failed", using_default="next_question")
                decision_data = {"decision": "next_question", "reason": "决策服务降级", "confidence": 0.5}
            else:
                decision_data = decision_result.data
            
            # ── Harness: Guard 净化决策 ──
            decision_data = self._guard.validate_followup_decision(decision_data)
            
            decision_type = decision_data.get("decision", "next_question")
            decision_reason = decision_data.get("reason", "")
            decision_confidence = decision_data.get("confidence", 0.8)
            
            logger.info(
                "chat_followup_decision_made",
                session_id=session_id,
                decision=decision_type,
                confidence=decision_confidence
            )
            
            # ===== 步骤⑤: 决定下一题内容 =====
            is_follow_up = False
            next_question = ""
            new_phase = current_phase
            
            if decision_type in ["follow_up", "interest_follow_up"]:
                is_follow_up = True
                next_question = decision_data.get("follow_up_content") or ""
                
                if not next_question:
                    next_question = await self._generate_fallback_followup(
                        session_id=session_id,
                        answer=user_answer,
                        decision_reason=decision_reason
                    )
                
                follow_up_budget -= 1
                
            elif decision_type == "phase_switch":
                desired_phase = self._get_next_phase(current_phase)
                # ── Harness: Guard 校验阶段转换 ──
                phase_result = self._guard.validate_phase_transition(
                    current_phase.value, desired_phase.value
                )
                if not phase_result.passed:
                    logger.warning(
                        "chat_phase_transition_blocked_by_guard",
                        from_phase=current_phase.value,
                        to_phase=desired_phase.value,
                        safe_fallback=phase_result.sanitized_value,
                    )
                    new_phase = InterviewPhase(phase_result.sanitized_value)
                else:
                    new_phase = desired_phase
                next_question = await self._generate_question_for_phase(
                    session_id=session_id,
                    phase=new_phase
                )
                question_count += 1
                
            else:  # next_question
                next_question = await self._generate_question_for_phase(
                    session_id=session_id,
                    phase=current_phase
                )
                question_count += 1
            
            # ===== 步骤⑥: 更新Redis SessionState =====
            await self._record_score_to_session(
                session_id=session_id,
                phase=current_phase,
                score=current_score
            )
            
            await self._memory_manager.record_assistant_message(
                session_id=session_id,
                content=next_question,
                metadata={
                    "phase": new_phase.value,
                    "question_type": self._phase_to_category(new_phase),
                    "is_follow_up": is_follow_up
                }
            )
            
            await self._memory_manager.update_session_state(
                session_id=session_id,
                phase=new_phase.value,
                follow_up_budget=max(0, follow_up_budget),
                question_count=question_count,
                last_active=datetime.now().isoformat()
            )
            
            # 如果阶段变了，更新系统提示词
            if new_phase != current_phase:
                await self._update_system_prompt_for_phase(session_id, new_phase)
            
            # 计算剩余可出新题数
            remaining_questions = max(0, self._settings.default_question_limit - question_count)
            
            logger.info(
                "chat_completed",
                session_id=session_id,
                score=current_score,
                is_follow_up=is_follow_up,
                new_phase=new_phase.value,
                question_count=question_count,
                remaining=remaining_questions
            )
            
            # ===== 步骤⑦: 构建并返回ChatResponse =====
            response = {
                "code": 200,
                "data": {
                    "score": current_score,
                    "feedback": feedback,
                    "nextQuestion": next_question,
                    "phase": new_phase.value,
                    "isFollowUp": is_follow_up,
                    "questionCount": question_count,
                    "remainingQuestions": remaining_questions,
                    "decision": {
                        "decision": decision_type,
                        "reason": decision_reason,
                        "confidence": decision_confidence
                    }
                }
            }
            
            return response
            
        except Exception as e:
            logger.exception(
                "chat_unexpected_error",
                session_id=session_id,
                error=str(e)
            )
            return {"code": 500, "error": f"服务器内部错误: {str(e)}"}
    
    async def _handle_chat_mode(
        self,
        session_id: str,
        user_answer: str,
        session_state: dict,
        question_count: int
    ) -> Dict[str, Any]:
        """
        处理闲聊模式的对话
        
        【与正式面试的区别】
        - 不走 ScoringSkill + FollowUpSkill + InterviewSkill 链路
        - 改用 ChatModeHandlerSkill 统一处理
        - 闲聊分数不计入正式总分（只影响 attitude 维度）
        
        【执行流程】
        1. 调用 ChatModeHandlerSkill 评估回答并生成回应
        2. 如果 Skill 决定结束闲聊 → 转入 FINAL_SCORE 阶段
        3. 否则继续闲聊，返回闲聊问题/回应
        """
        logger.info(
            "chat_mode_handling",
            session_id=session_id,
            answer_length=len(user_answer)
        )
        
        try:
            recent_scores = session_state.get("scores", [])
            resume_data = session_state.get("resume_data", {})
            
            chat_context = {
                "phase": InterviewPhase.CHAT_MODE.value,
                "recent_scores": recent_scores,
                "question_count": question_count,
                "resume_data": resume_data,
            }
            
            chat_result = await self._retry.execute(
                self._chat_mode_handler.execute,
                session_id=session_id,
                context=chat_context,
                user_answer=user_answer
            )
            
            if not chat_result.success:
                logger.error(
                    "chat_mode_handler_failed",
                    session_id=session_id,
                    error=chat_result.error
                )
                return {"code": 503, "error": f"闲聊服务暂不可用: {chat_result.error}"}
            
            chat_data = chat_result.data

            # ── Harness: Budget 记账（闲聊模式也是 LLM 调用）──
            estimated_tokens = self._budget.estimate_tokens(
                str(user_answer) + str(chat_data.get("feedback", ""))
            )
            self._budget.track_llm_call(session_id, tokens_used=estimated_tokens)
            
            if chat_data.get("next_action") == "transition_to_final_score":
                # ── Harness: Guard 校验阶段转换 ──
                guard_result = self._guard.validate_phase_transition(
                    InterviewPhase.CHAT_MODE.value, InterviewPhase.FINAL_SCORE.value
                )
                target_phase = InterviewPhase(
                    guard_result.sanitized_value if not guard_result.passed else InterviewPhase.FINAL_SCORE.value
                )
                await self._memory_manager.update_session_state(
                    session_id=session_id,
                    phase=target_phase.value,
                    last_active=datetime.now().isoformat()
                )
                
                return {
                    "code": 200,
                    "data": {
                        "score": chat_data.get("score"),
                        "feedback": chat_data.get("feedback", "感谢你的分享，让我们来总结一下今天的面试表现吧。"),
                        "nextQuestion": "",
                        "phase": target_phase.value,
                        "isFollowUp": False,
                        "questionCount": question_count,
                        "remainingQuestions": 0,
                        "decision": {
                            "decision": "phase_switch",
                            "reason": "闲聊结束，进入最终评分阶段",
                            "confidence": 0.95
                        }
                    }
                }
            
            followup_text = chat_data.get("followup", "")
            next_question = followup_text or chat_data.get("question", "")
            
            await self._memory_manager.record_assistant_message(
                session_id=session_id,
                content=next_question,
                metadata={
                    "phase": InterviewPhase.CHAT_MODE.value,
                    "question_type": "chat",
                    "is_follow_up": False
                }
            )
            
            return {
                "code": 200,
                "data": {
                    "score": chat_data.get("score"),
                    "feedback": chat_data.get("feedback", ""),
                    "nextQuestion": next_question,
                    "phase": InterviewPhase.CHAT_MODE.value,
                    "isFollowUp": bool(followup_text),
                    "questionCount": question_count,
                    "remainingQuestions": max(0, self._settings.default_question_limit - question_count),
                    "decision": {
                        "decision": "next_question",
                        "reason": "闲聊模式继续",
                        "confidence": 0.9
                    }
                }
            }
            
        except Exception as e:
            logger.exception(
                "chat_mode_unexpected_error",
                session_id=session_id,
                error=str(e)
            )
            return {"code": 500, "error": f"闲聊模式异常: {str(e)}"}
    
    async def end_interview(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        结束面试并计算最终综合评分
        
        【对应链路】链路4: 结束面试
        【触发时机】用户点击"结束面试" 或 题目答完
        
        【执行流程（6步）】
        ① 从Redis加载完整的SessionState（包含所有历史scores）
        ② 提取各阶段的分数列表并计算平均值
        ③ 调用ScoringSkill.calculate_final_score()计算加权总分
        ④ 将LLM原始返回映射为FinalScoreResult格式（字段名转换！）
        ⑤ 标记Redis会话为inactive（可选删除或等TTL过期）
        ⑥ 返回FinalScoreResult（9个字段）
        
        【参数】
        - session_id: 面试会话ID
        
        【返回值】FinalScoreResult（9个字段）:
        {
            "code": 200,
            "data": {
                "finalScore": 79.2,           # float 0-100
                "level": "B",                 # A/B/C/D
                "summary": "技术基础扎实...",  # 综合评语文本
                "dimensions": [               # List[DimensionScore] (5个维度)
                    {"dimension": "practice_experience", "score": 83.1, "details": ""},
                    {"dimension": "technical_knowledge", "score": 71.75, "details": ""},
                    {"dimension": "communication", "score": 82, "details": ""},
                    {"dimension": "potential", "score": 78, "details": ""},
                    {"dimension": "attitude", "score": 85, "details": ""}
                ],
                "strengths": ["Spring熟练", ...],     # 优势列表
                "weaknesses": ["JVM需深入", ...],     # 不足列表
                "suggestions": ["复习JVM...", ...],   # 改进建议
                "passed": true                       # 是否通过(>=70)
            }
        }
        
        【五维加权公式 - 2026-04-19 更新】
        final_score = practice_experience×45% + technical_knowledge×25%
                    + communication×15% + potential×10% + attitude×5%
        
        其中 practice_experience = internship×25% + project×20%
        
        【等级判定】
        A (>=85) | B (70-84) | C (60-69) | D (<60)
        passed = final_score >= 70
        """
        logger.info("end_interview_called", session_id=session_id)
        
        try:
            # ===== 步骤①: 加载完整SessionState =====
            session_state = await self._memory_manager.get_session(session_id)
            
            if not session_state:
                logger.error("end_interview_session_not_found", session_id=session_id)
                return {"code": 404, "error": "面试会话不存在"}
            
            scores_raw = session_state.get("scores", {})
            question_count = session_state.get("question_count", 0)
            
            logger.info(
                "end_interview_session_loaded",
                session_id=session_id,
                total_questions=question_count,
                scores_phases=list(scores_raw.keys())
            )
            
            # ===== 步骤②: 计算各阶段平均分 =====
            avg_scores = {}
            for phase, score_list in scores_raw.items():
                if isinstance(score_list, list) and len(score_list) > 0:
                    avg_scores[phase] = sum(score_list) / len(score_list)
                    logger.debug(
                        "phase_average_calculated",
                        phase=phase,
                        avg=avg_scores[phase],
                        count=len(score_list)
                    )
            
            # ===== 步骤③: 调用ScoringSkill计算最终评分（带重试）=====
            session_summary = {
                "total_questions": question_count,
                "phases_covered": list(avg_scores.keys()),
                "duration_info": "可通过start_time/end_time计算"
            }
            
            final_result = await self._retry.execute(
                self._scoring_skill.calculate_final_score,
                session_id=session_id,
                all_scores=avg_scores,
                session_summary=session_summary
            )
            
            # ── Harness: Guard 校验最终评分 ──
            final_result = self._guard.validate_final_score_result(final_result)
            
            logger.info(
                "end_interview_final_score_calculated",
                session_id=session_id,
                final_score=final_result.get("final_score", 0),
                level=final_result.get("level", "C")
            )
            
            # ===== 步骤④: 字段映射（关键！）=====
            final_score_value = final_result.get("final_score", 0)
            raw_dimensions = final_result.get("dimension_scores", {})
            
            dimensions = [
                DimensionScore(
                    dimension=dim,
                    score=float(score),
                    details=""
                )
                for dim, score in raw_dimensions.items()
            ]
            
            result_data = {
                "finalScore": final_score_value,
                "level": final_result.get("level", "C"),
                "dimensions": [dim.model_dump() for dim in dimensions],
                "summary": final_result.get("summary", ""),
                "strengths": final_result.get("strengths", []),
                "weaknesses": final_result.get("weaknesses", []),
                "suggestions": final_result.get("suggestions", []),
                "passed": final_score_value >= 70
            }
            
            # ===== 步骤⑤: 标记会话结束 =====
            await self._memory_manager.update_session_field(
                session_id=session_id,
                field="status",
                value="completed"
            )
            
            # ── Harness: 清理 Budget ──
            self._budget.cleanup(session_id)
            
            logger.info(
                "end_interview_success",
                session_id=session_id,
                final_score=final_score_value,
                level=result_data["level"],
                passed=result_data["passed"]
            )
            
            # ===== 步骤⑥: 返回结果 =====
            return {
                "code": 200,
                "data": result_data
            }
            
        except Exception as e:
            logger.exception(
                "end_interview_unexpected_error",
                session_id=session_id,
                error=str(e)
            )
            return {"code": 500, "error": f"服务器内部错误: {str(e)}"}
    
    async def parse_resume(
        self,
        file_url: str,
        user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        解析简历 - 调用LLM分析PDF并返回结构化数据
        
        【对应链路】链路1: 简历上传+解析
        【触发时机】用户上传简历后，Java调用此方法
        
        【执行流程】
        ① 从file_url下载PDF文件
        ② 调用ResumeSkill.execute()解析
        ③ 内部调用LLM（GLM-4）提取结构化信息
        ④ 返回JSON字符串
        
        【参数】
        - file_url: OSS上的PDF文件URL
        - user_id: 用户ID（可选，默认为"system"）
        
        【返回值】
        {
            "code": 200,
            "content": "{JSON字符串: name, skills, internships, projects...}"
        }
        """
        logger.info("parse_resume_called", file_url=file_url[:50] + "...", user_id=user_id)
        
        try:
            result = await self._resume_skill.execute(
                session_id="resume_parse_temp",
                context={
                    "file_url": file_url,
                    "user_id": user_id
                }
            )
            
            if result.success:
                logger.info("parse_resume_success")
                return {
                    "code": 200,
                    "content": result.data
                }
            else:
                logger.error("parse_resume_failed", error=result.error)
                return {"code": 500, "error": result.error}
                
        except Exception as e:
            logger.exception("parse_resume_error", error=str(e))
            return {"code": 500, "error": f"简历解析失败: {str(e)}"}
    
    async def _load_resume_from_db(self, resume_id: str) -> Dict[str, Any]:
        """
        从Java端加载已解析的简历数据（Step 11 实现）

        【解决什么问题】
        start_interview() 需要候选人的简历结构化数据来生成个性化题目，
        但简历数据存储在 Java 端管理的 MySQL 中。
        此方法通过 HTTP 回调 Java API 获取简历数据。

        【调用时机】
        start_interview() 的步骤②③，在创建Redis会话之后、生成第一题之前

        【数据流向】
        Python(Orchestrator) ──HTTP GET──► Java(Controller)
                              ◄────JSON─────
                    { parsed_content: "{结构化JSON}" }

        【返回值】
        成功: 解析后的字典 {
            "name": "张三",
            "skills": ["Java", "Spring Boot", ...],
            "internships": [...],
            "projects": [...],
            ...
        }
        失败/降级: 空字典 {} （InterviewSkill 会用通用模式出题）

        【容错策略】
        - Java端不可达 → 返回空dict，降级为通用模式出题（不影响核心流程）
        - 简历未解析(parse_status≠2) → 返回空dict + warning日志
        - parsed_content为空或非法JSON → 返回空dict + error日志

        【Java端需要实现的接口】
        GET /api/internal/python/resume/{resume_id}
        详细规范见: docs/step11_java_api_contract.md
        """
        settings = get_settings()
        java_url = settings.java_backend_url.rstrip("/")

        logger.info(
            "loading_resume_from_java",
            resume_id=resume_id,
            java_url=java_url,
        )

        try:
            settings = get_settings()
            timeout = settings.java_backend_timeout
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"{java_url}/api/internal/python/resume/{resume_id}",
                    headers={
                        "X-Internal-Service": "ai-interview-python",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()

                data = response.json()

                parse_status = data.get("parseStatus")
                parsed_content = data.get("parsedContent", "")

                if parse_status != 2:
                    logger.warning(
                        "resume_not_parsed_yet",
                        resume_id=resume_id,
                        parse_status=parse_status,
                    )
                    return {}

                if not parsed_content:
                    logger.warning("resume_parsed_content_empty", resume_id=resume_id)
                    return {}

                try:
                    resume_data = json.loads(parsed_content)
                    logger.info(
                        "resume_loaded_successfully",
                        resume_id=resume_id,
                        has_name=bool(resume_data.get("name")),
                        skills_count=len(resume_data.get("skills", [])),
                    )
                    return resume_data if isinstance(resume_data, dict) else {}
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error(
                        "resume_parsed_content_invalid_json",
                        resume_id=resume_id,
                        error=str(e),
                    )
                    return {}

        except httpx.TimeoutException:
            logger.warning(
                "java_resume_api_timeout_fallback",
                resume_id=resume_id,
                fallback="empty_resume_data",
            )
            return {}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(
                    "resume_not_found_in_java",
                    resume_id=resume_id,
                    status=e.response.status_code,
                )
                return {}

            logger.error(
                "java_resume_api_http_error",
                resume_id=resume_id,
                status_code=e.response.status_code,
                error=str(e),
            )
            return {}

        except Exception as e:
            logger.exception(
                "load_resume_from_db_unexpected_error",
                resume_id=resume_id,
                error=str(e),
            )
            return {}
    
    # ══════════════════════════════════════════════
    # 私有辅助方法（内部使用，不对外暴露）
    # ══════════════════════════════════════════════
    
    def _phase_to_category(self, phase: InterviewPhase) -> str:
        """将面试阶段转换为题目分类"""
        mapping = {
            InterviewPhase.SELF_INTRO: "self_introduction",
            InterviewPhase.INTERNSHIP_QA: "internship",
            InterviewPhase.PROJECT_QA: "project",
            InterviewPhase.EIGHT_PART_QA: "technical_javase",
            InterviewPhase.CHAT_MODE: "chat",
            InterviewPhase.FINAL_SCORE: "final_score",
            InterviewPhase.END: "end"
        }
        return mapping.get(phase, "unknown")
    
    def _get_next_phase(self, current_phase: InterviewPhase) -> InterviewPhase:
        """获取下一个面试阶段（状态机流转）"""
        phase_order = [
            InterviewPhase.SELF_INTRO,
            InterviewPhase.INTERNSHIP_QA,
            InterviewPhase.PROJECT_QA,
            InterviewPhase.EIGHT_PART_QA,
            InterviewPhase.CHAT_MODE,
            InterviewPhase.FINAL_SCORE,
            InterviewPhase.END
        ]
        
        try:
            current_index = phase_order.index(current_phase)
            if current_index < len(phase_order) - 1:
                return phase_order[current_index + 1]
        except ValueError:
            pass
        
        return InterviewPhase.END
    
    def _get_last_ai_question(self, session_id: str) -> Optional[str]:
        """获取最后一道AI出的题目"""
        return self._memory_manager.get_last_assistant_message(session_id)
    
    async def _generate_question_for_phase(
        self,
        session_id: str,
        phase: InterviewPhase
    ) -> str:
        """为指定阶段生成新题目"""
        session = await self._memory_manager.get_session(session_id)
        resume_data = session.get("resume_data", {}) if session else {}
        
        result = await self._retry.execute(
            self._interview_skill.execute,
            session_id=session_id,
            context={
                "phase": phase,
                "resume_data": resume_data,
                "question_count": 0,
                "asked_questions": []
            }
        )
        
        if result.success and result.data:
            question_text = result.data.get("question", "请继续描述你的相关经验。")
            # ── Harness: Budget 记账 ──
            estimated_tokens = self._budget.estimate_tokens(question_text)
            self._budget.track_llm_call(session_id, tokens_used=estimated_tokens)
            return question_text
        
        return "请继续分享你的想法。"
    
    async def _generate_fallback_followup(
        self,
        session_id: str,
        answer: str,
        decision_reason: str
    ) -> str:
        """生成兜底追问（当FollowUpSkill未提供追问内容时）"""
        return f"能详细说说{decision_reason.lower()}吗？"
    
    async def _record_score_to_session(
        self,
        session_id: str,
        phase: InterviewPhase,
        score: int
    ):
        """记录分数到SessionState"""
        await self._memory_manager.record_phase_score(
            session_id=session_id,
            phase_key=phase.value,
            score=score
        )
    
    async def _update_system_prompt_for_phase(
        self,
        session_id: str,
        new_phase: InterviewPhase
    ):
        """根据新阶段更新系统提示词"""
        prompts = {
            InterviewPhase.SELF_INTRO: "你是专业的面试官，正在引导候选人做自我介绍。",
            InterviewPhase.INTERNSHIP_QA: "你是技术面试官，正在深入询问候选人的实习经历。",
            InterviewPhase.PROJECT_QA: "你是技术面试官，正在深入询问候选人的项目经验。",
            InterviewPhase.EIGHT_PART_QA: "你是技术面试官，正在考察候选人的技术基础知识。",
            InterviewPhase.CHAT_MODE: "你现在处于轻松的闲聊模式，可以聊一些非技术话题。",
            InterviewPhase.FINAL_SCORE: "面试即将结束，准备给出综合评价。"
        }
        
        new_prompt = prompts.get(new_phase, "你是专业的面试官。")
        await self._memory_manager.update_system_prompt(session_id, new_prompt)


_orchestrator_instance: Optional[InterviewOrchestrator] = None


def get_interview_orchestrator() -> InterviewOrchestrator:
    """
    获取InterviewOrchestrator单例（工厂方法）
    
    【Java类比】
    类似Spring的@Bean或者@Configurable单例注入：
    ```java
    @Bean
    @Scope("singleton")
    public InterviewOrchestrator orchestrator() {
        return new InterviewOrchestrator();
    }
    ```
    
    【使用示例】
    from app.orchestrator.interview_orchestrator import get_interview_orchestrator
    
    orchestrator = get_interview_orchestrator()
    result = await orchestrator.chat("session_123", "HashMap底层是数组加链表...")
    """
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = InterviewOrchestrator()
    return _orchestrator_instance


def reset_orchestrator_instance():
    """重置单例（测试用）"""
    global _orchestrator_instance
    _orchestrator_instance = None
