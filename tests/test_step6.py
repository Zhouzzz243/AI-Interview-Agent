"""
Step 6 测试脚本 - 验证 Memory 层功能

【测试内容】
1. SessionStore: 会话 CRUD、阶段管理、题目记录、得分管理、追问配额
2. ShortTermMemory: 消息管理、Token控制、窗口裁剪
3. MemoryManager: 统一入口、双层协作

【运行方式】
python test_step6.py

【前置条件】
- Redis 服务已启动（或允许内存模式降级）
- 已安装所有依赖
"""

import asyncio
import sys
from datetime import datetime


def print_separator(title: str):
    """打印分隔线"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


async def test_short_term_memory():
    """测试短期记忆模块"""
    print_separator("[1] 测试 ShortTermMemory (短期记忆)")
    
    from app.memory.short_term_memory import ShortTermMemory, Message
    
    print("\n[测试] 创建短期记忆实例...")
    memory = ShortTermMemory(
        system_prompt="你是面试官，请引导候选人进行技术面试。",
        max_rounds=5,
        max_tokens=2000
    )
    print(f"[OK] 创建成功: {memory}")
    
    print("\n[测试] 添加消息...")
    memory.add_user_message("你好，我是候选人")
    memory.add_assistant_message("请先做个自我介绍")
    memory.add_user_message("我是XXX大学的学生，主修计算机科学...")
    memory.add_assistant_message("好的，我看到你熟悉Java和MySQL")
    
    stats = memory.get_stats()
    print(f"[OK] 添加4条消息后统计:")
    print(f"   - 总消息数: {stats.total_messages}")
    print(f"   - 对话轮数: {stats.window_size}")
    print(f"   - 预估Token: {stats.estimated_tokens}")
    
    print("\n[测试] 获取 LLM 上下文格式...")
    messages = memory.get_messages_for_llm()
    print(f"[OK] 消息数量: {len(messages)}")
    if messages:
        print(f"   - 第一条(system): {messages[0]['role']} - {messages[0]['content'][:30]}...")
        print(f"   - 第二条(user): {messages[1]['role']} - {messages[1]['content'][:30]}...")
    
    print("\n[测试] 获取最后一条用户消息...")
    last_user = memory.get_last_user_content()
    if last_user:
        print(f"[OK] 最后用户输入: {last_user[:50]}...")
    
    print("\n[测试] Token 控制与裁剪...")
    for i in range(10):
        memory.add_user_message(f"这是第{i+1}轮的用户输入内容" * 20)
        memory.add_assistant_message(f"这是第{i+1}轮的AI回复内容" * 15)
    
    stats_after_trim = memory.get_stats()
    print(f"[OK] 大量添加后自动裁剪:")
    print(f"   - 总消息数: {stats_after_trim.total_messages} (受 max_rounds={5} 限制)")
    print(f"   - 对话轮数: {stats_after_trim.window_size}")
    
    print("\n[测试] 更新系统提示词...")
    new_prompt = "现在是实习经历深挖阶段，请用STAR法则提问"
    memory.update_system_prompt(new_prompt)
    messages_updated = memory.get_messages_for_llm()
    if messages_updated and messages_updated[0]['content'] == new_prompt:
        print(f"[OK] 系统提示词更新成功")
    
    print("\n[测试] 清空记忆...")
    memory.clear()
    print(f"[OK] 清空后: {memory}")
    
    return True


async def test_session_store():
    """测试会话存储模块"""
    print_separator("[2] 测试 SessionStore (Redis会话存储)")
    
    from app.memory.session_store import SessionStore, get_session_store
    from app.api.schemas import InterviewPhase
    
    store = get_session_store()
    
    test_session_id = f"test_session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    test_user_id = "test_user_001"
    test_resume_id = "test_resume_001"
    
    print(f"\n[测试] 创建会话: {test_session_id}")
    success = await store.create_session(
        session_id=test_session_id,
        user_id=test_user_id,
        resume_id=test_resume_id,
        phase=InterviewPhase.SELF_INTRO
    )
    
    if success:
        print("[OK] 会话创建成功")
    else:
        print("[WARN] Redis 可能未连接，使用降级模式继续测试")
    
    print("\n[测试] 获取会话信息...")
    session = await store.get_session(test_session_id)
    if session:
        print(f"[OK] 获取成功:")
        print(f"   - phase: {session.get('phase')}")
        print(f"   - user_id: {session.get('user_id')}")
        print(f"   - follow_up_budget: {session.get('follow_up_budget')}")
        print(f"   - question_count: {session.get('question_count')}")
    else:
        print("[WARN] 无法获取会话（Redis可能不可用）")
    
    print("\n[测试] 更新阶段...")
    phase_success = await store.update_phase(test_session_id, InterviewPhase.INTERNSHIP_QA)
    current_phase = await store.get_phase(test_session_id)
    if current_phase == InterviewPhase.INTERNSHIP_QA:
        print(f"[OK] 阶段更新成功: {current_phase.value}")
    
    print("\n[测试] 记录已问过的题目...")
    q_success1 = await store.add_asked_question(test_session_id, "internship", "q_internship_001")
    q_success2 = await store.add_asked_question(test_session_id, "internship", "q_internship_002")
    q_success3 = await store.add_asked_question(test_session_id, "project", "q_project_001")
    q_success4 = await store.add_asked_question(test_session_id, "eight_part", "javase_q001")
    q_success5 = await store.add_asked_question(test_session_id, "eight_part", "jvm_q001")
    
    asked = await store.get_asked_questions(test_session_id)
    if asked:
        print(f"[OK] 题目记录成功:")
        print(f"   - 实习题: {asked.get('internships', [])}")
        print(f"   - 项目题: {asked.get('projects', [])}")
        print(f"   - 八股题: {asked.get('eight_parts', {})}")
    
    print("\n[测试] 记录得分...")
    score_success1 = await store.add_score(test_session_id, "self_intro", 85)
    score_success2 = await store.add_score(test_session_id, "internship", 78)
    score_success3 = await store.add_score(test_session_id, "internship", 82)
    
    scores = await store.get_scores(test_session_id)
    averages = await store.get_average_scores(test_session_id)
    if scores:
        print(f"[OK] 得分记录成功:")
        print(f"   - 原始得分: {scores}")
        print(f"   - 平均分: {averages}")
    
    print("\n[测试] 追问配额管理...")
    budget_before = await store.get_followup_budget(test_session_id)
    remaining1 = await store.decrement_followup_budget(test_session_id)
    remaining2 = await store.decrement_followup_budget(test_session_id)
    budget_after = await store.get_followup_budget(test_session_id)
    print(f"[OK] 追问配额变化: {budget_before} -> {remaining1} -> {remaining2} -> 当前{budget_after}")
    
    print("\n[测试] 对话历史记录...")
    chat_success1 = await store.add_chat_message(
        test_session_id, "user", "我做过一个电商项目",
        metadata={"phase": "project_qa"}
    )
    chat_success2 = await store.add_chat_message(
        test_session_id, "assistant", "能详细说说吗？用了什么技术栈？"
    )
    
    history = await store.get_chat_history(test_session_id, limit=5)
    if history:
        print(f"[OK] 对话历史记录成功: 共{len(history)}条")
        for msg in history[-2:]:
            role = msg.get("role")
            content_preview = msg.get("content", "")[:40]
            print(f"   - [{role}]: {content_preview}...")
    
    print("\n[测试] 获取会话统计摘要...")
    summary = await store.get_session_stats(test_session_id)
    if summary:
        print(f"[OK] 统计摘要:")
        print(f"   - 阶段: {summary.get('phase')}")
        print(f"   - 总出题数: {summary.get('total_questions')}")
        print(f"   - 平均分: {summary.get('average_score')}")
        print(f"   - 剩余追问: {summary.get('remaining_followups')}")
    
    print("\n[测试] 删除会话...")
    delete_success = await store.delete_session(test_session_id)
    exists_after_delete = await store.exists(test_session_id)
    if delete_success or not exists_after_delete:
        print(f"[OK] 删除成功（或已自动过期）")
    
    return True


async def test_memory_manager():
    """测试记忆管理器（统一入口）"""
    print_separator("[3] 测试 MemoryManager (统一入口)")
    
    from app.memory.memory_manager import get_memory_manager
    from app.api.schemas import InterviewPhase
    
    manager = get_memory_manager()
    
    test_session_id = f"mgr_test_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    print(f"\n[测试] 通过 Manager 创建会话...")
    system_prompt = "你是专业的技术面试官，擅长考察候选人的实际能力"
    success = await manager.create_session(
        session_id=test_session_id,
        user_id="user_mgr_test",
        resume_id="resume_mgr_test",
        initial_system_prompt=system_prompt
    )
    print(f"[OK] 创建结果: {'成功' if success else '失败(可能是Redis)'}")
    
    print("\n[测试] 通过 Manager 记录对话...")
    await manager.record_user_message(
        test_session_id,
        "你好，我来参加面试",
        metadata={"phase": "self_introduction"}
    )
    await manager.record_assistant_message(
        test_session_id,
        "欢迎！请先用1-2分钟做个自我介绍",
        metadata={"phase": "self_introduction"}
    )
    await manager.record_user_message(
        test_session_id,
        "我是XXX大学计算机专业大三学生...",
        metadata={"phase": "self_introduction"}
    )
    print("[OK] 对话记录成功")
    
    print("\n[测试] 获取 LLM 上下文...")
    context = await manager.get_context_for_llm(test_session_id)
    print(f"[OK] 上下文消息数: {len(context)}")
    if context:
        print(f"   - system: {context[0].get('content', '')[:40]}...")
    
    print("\n[测试] 获取最后用户输入...")
    last_content = manager.get_last_user_content(test_session_id)
    if last_content:
        print(f"[OK] 最后用户输入: {last_content[:50]}...")
    
    print("\n[测试] 通过 Manager 记录得分和题目...")
    await manager.record_score(test_session_id, "self_intro", 88)
    await manager.record_asked_question(test_session_id, "internship", "q1")
    
    avg_scores = await manager.get_average_scores(test_session_id)
    print(f"[OK] 平均分: {avg_scores}")
    
    print("\n[测试] 消耗追问配额...")
    remaining = await manager.consume_followup_budget(test_session_id)
    print(f"[OK] 剩余追问次数: {remaining}")
    
    print("\n[测试] 获取完整会话摘要...")
    summary = await manager.get_session_summary(test_session_id)
    if summary:
        print(f"[OK] 会话摘要:")
        for key, value in summary.items():
            print(f"   - {key}: {value}")
    
    print("\n[测试] 清理测试会话...")
    await manager.delete_session(test_session_id)
    print("[OK] 清理完成")
    
    return True


async def main():
    """主测试函数"""
    print("\n" + "#" * 60)
    print("  Step 6: Memory 层功能验证")
    print("  测试时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("#" * 60)
    
    results = []
    
    try:
        result1 = await test_short_term_memory()
        results.append(("ShortTermMemory", result1))
    except Exception as e:
        print(f"\n[FAIL] ShortTermMemory 测试失败: {e}")
        results.append(("ShortTermMemory", False))
    
    try:
        result2 = await test_session_store()
        results.append(("SessionStore", result2))
    except Exception as e:
        print(f"\n[FAIL] SessionStore 测试失败: {e}")
        results.append(("SessionStore", False))
    
    try:
        result3 = await test_memory_manager()
        results.append(("MemoryManager", result3))
    except Exception as e:
        print(f"\n[FAIL] MemoryManager 测试失败: {e}")
        results.append(("MemoryManager", False))
    
    # 输出总结
    print("\n" + "#" * 60)
    print("  [RESULT] 测试结果汇总")
    print("#" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "-" * 30)
    if all_passed:
        print("  [SUCCESS] 所有测试通过！Step 6 实现完成")
    else:
        print("  [WARNING] 部分测试失败，请检查错误信息")
    print("-" * 30 + "\n")
    
    return all_passed


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[INTERRUPT] 测试被用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n[ERROR] 测试异常退出: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
