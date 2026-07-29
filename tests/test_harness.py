"""
Harness 层单元测试 — 纯逻辑测试，无需 Redis/LLM 等外部依赖

测试目标: budget.py | guard.py | retry.py
"""
import sys
import os
import time
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.harness.budget import (
    InterviewBudget,
    BudgetStatus,
    BudgetExhaustedReason,
    get_interview_budget,
)
from app.harness.guard import (
    InterviewGuard,
    GuardPhase,
    GuardDecision,
    GuardResult,
    get_interview_guard,
)
from app.harness.retry import (
    RetryPolicy,
    RetryPresets,
    ErrorCategory,
    ErrorClassifier,
    RetryExhaustedError,
)

PASS = 0
FAIL = 0


def test(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


# ══════════════════════════════════════════════
# 1. Budget 模块测试
# ══════════════════════════════════════════════

print("\n" + "="*60)
print("💰 Budget 模块测试")
print("="*60)

budget = InterviewBudget()

# 1.1 初始化
test("初始化后 active_sessions = 0", budget.active_sessions == 0)

# 1.2 get_or_create
status = budget.get_or_create("test_session")
test("get_or_create 返回 BudgetStatus", isinstance(status, BudgetStatus))
test("session_id 正确", status.session_id == "test_session")
test("初始 session_tokens_used = 0", status.session_tokens_used == 0)
test("初始 turn_llm_calls = 0", status.turn_llm_calls == 0)
test("初始 questions_asked = 0", status.questions_asked == 0)
test("默认 round_max_tokens = 4000", status.round_max_tokens == 4000)
test("默认 max_questions = 15", status.max_questions == 15)
test("active_sessions = 1 after creation", budget.active_sessions == 1)

# 1.3 can_continue
test("新会话 can_continue = True", budget.can_continue("test_session") is True)

# 1.4 track_llm_call
budget.track_llm_call("test_session", tokens_used=1000)
status2 = budget.get_status("test_session")
test("track_llm_call 后 turn_llm_calls +1", status2.turn_llm_calls == 1)
test("track_llm_call 后 session_tokens_used 累加", status2.session_tokens_used == 1000)

# 1.5 reset_turn
budget.reset_turn("test_session")
status3 = budget.get_status("test_session")
test("reset_turn 后 turn_llm_calls 归零", status3.turn_llm_calls == 0)
test("reset_turn 后 session_tokens 不变", status3.session_tokens_used == 1000)

# 1.6 Session tokens 耗尽
budget_big = InterviewBudget()
sid = "big_spender"
budget_big.track_llm_call(sid, tokens_used=50000)
test("session tokens 耗尽 → can_continue = False", budget_big.can_continue(sid) is False)
status_big = budget_big.get_status(sid)
test("耗尽原因 = SESSION_TOKENS", status_big.exhausted_reason == BudgetExhaustedReason.SESSION_TOKENS)

# 1.7 Turn LLM calls 耗尽
budget_turn = InterviewBudget()
sid2 = "turn_breaker"
for i in range(6):
    budget_turn.track_llm_call(sid2, tokens_used=100)
test("6次 LLM 调用后 can_continue = False", budget_turn.can_continue(sid2) is False)
st = budget_turn.get_status(sid2)
test("耗尽原因 = TURN_LLM_CALLS", st.exhausted_reason == BudgetExhaustedReason.TURN_LLM_CALLS)
# reset 后恢复
budget_turn.reset_turn(sid2)
test("reset_turn 后 can_continue = True", budget_turn.can_continue(sid2) is True)

# 1.8 Questions 耗尽
budget_q = InterviewBudget(max_questions=3)
sid3 = "q_breaker"
for i in range(3):
    budget_q.track_llm_call(sid3, tokens_used=100, increment_question=True)
test("3道题后 can_continue = False", budget_q.can_continue(sid3) is False)
st_q = budget_q.get_status(sid3)
test("耗尽原因 = SESSION_QUESTIONS", st_q.exhausted_reason == BudgetExhaustedReason.SESSION_QUESTIONS)

# 1.9 estimate_tokens
test("空文本估 0", budget.estimate_tokens("") == 0)
test("英文估 token", budget.estimate_tokens("hello world") > 0)
test("中文估 token", budget.estimate_tokens("你好世界") > 0)
test("中文估 > 英文 (字符数相同)", budget.estimate_tokens("你好世界") > budget.estimate_tokens("hello"))

# 1.10 build_degraded_response
resp = budget.build_degraded_response("test_session")
test("降级响应 code=200", resp.get("code") == 200)
test("降级响应含 phase=final_score", resp["data"]["phase"] == "final_score")
test("降级响应含 decision=budget_exhausted", resp["data"]["decision"]["decision"] == "budget_exhausted")

# 1.11 cleanup
budget.cleanup("test_session")
test("cleanup 后不存在", "test_session" not in budget._budgets)

# 1.12 BudgetStatus 属性
bs = BudgetStatus(session_id="prop_test", session_tokens_used=25000, session_max_tokens=50000)
test("session_token_pct = 50%", abs(bs.session_token_pct - 50.0) < 0.01)
test("is_exhausted = False (无原因)", bs.is_exhausted is False)
bs.exhausted_reason = BudgetExhaustedReason.SESSION_TOKENS
test("is_exhausted = True (有原因)", bs.is_exhausted is True)
summary = bs.summary()
test("summary 包含 session_tokens", "session_tokens" in summary)
test("summary 包含 EXHAUSTED", "EXHAUSTED" in summary)

# 1.13 单例
b1 = get_interview_budget()
b2 = get_interview_budget()
test("get_interview_budget 单例", b1 is b2)


# ══════════════════════════════════════════════
# 2. Guard 模块测试
# ══════════════════════════════════════════════

print("\n" + "="*60)
print("🔒 Guard 模块测试")
print("="*60)

guard = InterviewGuard()

# 2.1 合法阶段转换
result = guard.validate_phase_transition("self_introduction", "internship_qa")
test("self_intro → internship_qa 合法", result.passed is True)
test("合法转换 reason=transition_allowed", result.reason == "transition_allowed")

# 2.2 自转换始终合法
result = guard.validate_phase_transition("internship_qa", "internship_qa")
test("internship_qa → internship_qa (追问) 合法", result.passed is True)
test("自转换 reason=self_transition_allowed", result.reason == "self_transition_allowed")

# 2.3 非法阶段转换
result = guard.validate_phase_transition("final_score", "self_introduction")
test("final_score → self_intro 非法", result.passed is False)
test("非法转换有 sanitized_value", result.sanitized_value is not None)
test("退回到 end 阶段", result.sanitized_value == "end")

# 2.4 无效阶段值
result = guard.validate_phase_transition("garbage", "self_introduction")
test("无效阶段值 非法", result.passed is False)

# 2.5 sanitize_score 正常值
score, valid = guard.sanitize_score(85)
test("85 合法", valid is True and score == 85)

# 2.6 sanitize_score 越界
score, valid = guard.sanitize_score(150)
test("150 → clamp 到 100", valid is False and score == 100)

score, valid = guard.sanitize_score(-10)
test("-10 → clamp 到 0", valid is False and score == 0)

# 2.7 sanitize_score 非法类型
score, valid = guard.sanitize_score("not_a_number")
test("字符串 → 默认值 70", valid is False and score == 70)

score, valid = guard.sanitize_score(None)
test("None → 默认值 70", valid is False and score == 70)

# 2.8 validate_followup_decision 正常
d = guard.validate_followup_decision({"decision": "follow_up", "reason": "有深挖空间", "confidence": 0.85})
test("合法 decision 通过", d["decision"] == "follow_up")
test("confidence 保留", d["confidence"] == 0.85)

# 2.9 validate_followup_decision 非法值
d = guard.validate_followup_decision({"decision": "illegal_value"})
test("非法 decision → next_question 兜底", d["decision"] == "next_question")

# 2.10 validate_followup_decision 缺失字段
d = guard.validate_followup_decision({"decision": "follow_up"})
test("缺失 reason → 补默认值", "降级" in d.get("reason", ""))
test("缺失 confidence → 补 0.5", d["confidence"] == 0.5)

# 2.11 validate_followup_decision confidence 越界
d = guard.validate_followup_decision({"decision": "next_question", "confidence": 2.5})
test("confidence > 1 → clamp 到 1", d["confidence"] == 1.0)

d = guard.validate_followup_decision({"decision": "next_question", "confidence": -0.5})
test("confidence < 0 → clamp 到 0", d["confidence"] == 0.0)

# 2.12 validate_followup_decision 非 dict 输入
d = guard.validate_followup_decision("not_a_dict")
test("非 dict → 默认决策", d["decision"] == "next_question")

# 2.13 validate_scoring_dimensions 完整
dims = guard.validate_scoring_dimensions({
    "practice_experience": 85,
    "technical_knowledge": 72,
    "communication": 80,
    "potential": 75,
    "attitude": 90,
})
test("5维度都保留", len(dims) == 5)
test("practice_experience = 85", dims["practice_experience"] == 85)

# 2.14 validate_scoring_dimensions 缺失
dims = guard.validate_scoring_dimensions({"practice_experience": 85})
test("缺失4维度补 70", dims["technical_knowledge"] == 70)
test("总共5维度", len(dims) == 5)

# 2.15 validate_final_score_result 正常
final = guard.validate_final_score_result({
    "final_score": 82,
    "level": "B",
    "summary": "不错",
    "dimension_scores": {"practice_experience": 85, "technical_knowledge": 72, "communication": 80, "potential": 75, "attitude": 90},
    "strengths": ["Spring"],
    "weaknesses": ["JVM"],
    "suggestions": ["多学JVM"],
})
test("final_score 通过", final["final_score"] == 82)
test("level 保留 B", final["level"] == "B")

# 2.16 validate_final_score_result 缺失字段
final = guard.validate_final_score_result({"final_score": 50})
test("score=50 → level D (<60)", final["level"] == "D")
test("缺失 strengths → []", final["strengths"] == [])
test("缺失 dimension_scores → 补默认", len(final["dimension_scores"]) == 5)

final2 = guard.validate_final_score_result({"final_score": 90})
test("score=90 → level A", final2["level"] == "A")

final3 = guard.validate_final_score_result({"final_score": 30})
test("score=30 → level D", final3["level"] == "D")

final4 = guard.validate_final_score_result({"final_score": 65})
test("score=65 → level C (60-69)", final4["level"] == "C")

# 2.17 GuardPhase 枚举
test("GuardPhase 7 个值", len(GuardPhase) == 7)
test("GuardDecision 5 个值", len(GuardDecision) == 5)

# 2.18 单例
g1 = get_interview_guard()
g2 = get_interview_guard()
test("get_interview_guard 单例", g1 is g2)


# ══════════════════════════════════════════════
# 3. Retry 模块测试
# ══════════════════════════════════════════════

print("\n" + "="*60)
print("🔄 Retry 模块测试")
print("="*60)

# 3.1 RetryPresets.llm_call 默认值
rp = RetryPresets.llm_call()
test("max_retries = 3", rp.max_retries == 3)
test("base_delay = 1.0", rp.base_delay == 1.0)
test("max_delay = 10.0", rp.max_delay == 10.0)
test("jitter = 0.5", rp.jitter == 0.5)
test("total_timeout = 30.0", rp.total_timeout == 30.0)

# 3.2 ErrorClassifier.classify 重试型错误
tc = ErrorClassifier
test("ConnectionError → RETRYABLE", tc.classify(ConnectionError()) == ErrorCategory.RETRYABLE)
test("TimeoutError → RETRYABLE", tc.classify(TimeoutError()) == ErrorCategory.RETRYABLE)
# 以异常类型名匹配，非消息内容匹配
test("Exception 通用异常 → UNKNOWN", tc.classify(Exception("429")) == ErrorCategory.UNKNOWN)
test("Exception 通用异常 → UNKNOWN", tc.classify(Exception("503")) == ErrorCategory.UNKNOWN)

# 3.3 ErrorClassifier.classify 非重试型（匹配 "status: 400" 模式）
class HttpError400(Exception):
    pass

e400 = HttpError400("status: 400 Bad Request")
test("HTTP 400 → NON_RETRYABLE", tc.classify(e400) == ErrorCategory.NON_RETRYABLE)

# 值错误 → UNKNOWN（保守重试1次）
test("ValueError → UNKNOWN", tc.classify(ValueError()) == ErrorCategory.UNKNOWN)
test("KeyError → UNKNOWN", tc.classify(KeyError()) == ErrorCategory.UNKNOWN)

# 3.4 _calc_delay 增长
rp2 = RetryPolicy(jitter=0)
d0 = rp2._calc_delay(0)  # base * 2^0 = 1.0
d1 = rp2._calc_delay(1)  # base * 2^1 = 2.0
d2 = rp2._calc_delay(2)  # base * 2^2 = 4.0
d3 = rp2._calc_delay(3)  # base * 2^3 = 8.0
test("delay(0) = 1.0", abs(d0 - 1.0) < 0.01)
test("delay(1) = 2.0", abs(d1 - 2.0) < 0.01)
test("delay(2) = 4.0", abs(d2 - 4.0) < 0.01)
test("delay(3) = 8.0", abs(d3 - 8.0) < 0.01)

# 3.5 max_delay 上限
rp3 = RetryPolicy(max_delay=3.0, jitter=0)
d5 = rp3._calc_delay(5)  # base * 2^5 = 32.0, capped at max_delay=3.0
test("delay(5) capped at max_delay=3.0", abs(d5 - 3.0) < 0.01)

# 3.6 jitter 在合理范围
rp4 = RetryPolicy(base_delay=1.0, jitter=0.5)
delays = [rp4._calc_delay(i) for i in range(10)]
test("有 jitter 时延迟不全相同", len(set(delays)) > 1)

# 3.7 execute 成功场景
async def _test_retry_success():
    call_count = [0]
    
    async def success_fn():
        call_count[0] += 1
        return "ok"
    
    rp = RetryPolicy(max_retries=3)
    result = await rp.execute(success_fn)
    test("成功只调用1次", call_count[0] == 1)
    test("返回正确值", result == "ok")

# 3.8 execute 第3次重试才成功
async def _test_retry_recovery():
    call_count = [0]
    
    async def fail_twice_then_succeed():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError(f"fail {call_count[0]}")
        return "recovered"
    
    rp = RetryPolicy(max_retries=5, base_delay=0.001, jitter=0)
    result = await rp.execute(fail_twice_then_succeed)
    test("第3次成功", call_count[0] == 3)
    test("返回 recovered", result == "recovered")

# 3.9 execute 始终失败 → RetryExhaustedError
async def _test_retry_exhausted():
    async def always_fail():
        raise ConnectionError("always broken")
    
    rp = RetryPolicy(max_retries=2, base_delay=0.001, jitter=0)
    try:
        await rp.execute(always_fail)
        test("不应到达这里", False)
    except RetryExhaustedError as e:
        test("抛出 RetryExhaustedError", True)
        test("attempts = 3 (含首次)", e.attempts == 3)

# 3.10 execute UNKNOWN 类型错误 → 重试1次后耗尽
async def _test_retry_unknown_exhausted():
    call_count = [0]
    
    async def unknown_error():
        call_count[0] += 1
        raise ValueError("bad input")
    
    rp = RetryPolicy(max_retries=3, base_delay=0.001)
    try:
        await rp.execute(unknown_error)
        test("不应到达这里", False)
    except RetryExhaustedError:
        test("UNKNOWN → 1次重试后耗尽", True)
        test("总调用次数 = 2 (首次 + 1次重试)", call_count[0] == 2)

# 3.11 自定义 RetryPolicy
custom = RetryPolicy(max_retries=5, base_delay=0.5, max_delay=60.0, jitter=0.2, total_timeout=120.0)
test("自定义 max_retries=5", custom.max_retries == 5)
test("自定义 total_timeout=120", custom.total_timeout == 120.0)


# ══════════════════════════════════════════════
# 4. 运行异步测试
# ══════════════════════════════════════════════

print("\n" + "="*60)
print("⏳ 运行异步测试...")
print("="*60)

asyncio.run(_test_retry_success())
asyncio.run(_test_retry_recovery())
asyncio.run(_test_retry_exhausted())
asyncio.run(_test_retry_unknown_exhausted())


# ══════════════════════════════════════════════
# 5. 总结
# ══════════════════════════════════════════════

print("\n" + "="*60)
print(f"📊 测试结果: ✅ {PASS} passed | ❌ {FAIL} failed")
print("="*60)

if FAIL > 0:
    sys.exit(1)
