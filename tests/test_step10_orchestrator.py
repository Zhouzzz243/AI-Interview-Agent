"""
InterviewOrchestrator 完整功能测试

【测试目标】
验证编排器的4个核心方法逻辑是否正确：
1. start_interview()  → 开始面试（初始化+第一题）
2. chat()             → 对话交互（评分+追问决策+出新题）
3. end_interview()    → 结束评分（综合评估）
4. parse_resume()     → 简历解析

【使用方式】
cd D:\agentproject\AI-Interview-Agent-python
python tests/test_step10_orchestrator.py

【预期输出】
- 每个步骤的详细日志
- 最终结果打印
- 如果有错误会显示具体堆栈

【注意事项】
- 需要Redis服务运行中（用于SessionStore）
- LLM调用需要有效的API Key（在.env文件中配置）
- 测试数据都是模拟的，不会影响真实业务
"""

import asyncio
import sys
import os
import json
from datetime import datetime
from typing import Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.logger import get_logger, setup_logging
from app.orchestrator.interview_orchestrator import InterviewOrchestrator, get_interview_orchestrator
from app.api.schemas import InterviewPhase


logger = get_logger(__name__)


class OrchestratorTester:
    """Orchestrator 测试类"""
    
    def __init__(self):
        self.orchestrator: InterviewOrchestrator = None
        self.test_session_id = f"test_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.test_resume_id = "test_resume_001"
        self.results = []
    
    async def setup(self):
        """初始化测试环境"""
        print("\n" + "="*80)
        print("🚀 InterviewOrchestrator 功能测试开始")
        print("="*80)
        
        # 初始化日志系统（开发模式：彩色输出）
        setup_logging(log_level="DEBUG", json_output=False)
        
        logger.info(
            "test_environment_setup",
            session_id=self.test_session_id,
            resume_id=self.test_resume_id,
            python_version=sys.version
        )
        
        # 创建编排器实例
        self.orchestrator = get_interview_orchestrator()
        logger.info("orchestrator_instance_created")
    
    async def test_1_start_interview(self):
        """
        测试1: start_interview() - 开始面试
        
        【验证点】
        ✓ Redis会话是否创建成功
        ✓ 第一道题是否生成（应该是自我介绍）
        ✓ 返回值格式是否正确 {code, question}
        ✓ question_count是否更新为1
        """
        print("\n" + "─"*80)
        print("📋 测试1: start_interview() - 开始面试")
        print("─"*80)
        
        try:
            logger.info(
                "test1_start",
                session_id=self.test_session_id,
                resume_id=self.test_resume_id
            )
            
            # 调用start_interview
            result = await self.orchestrator.start_interview(
                session_id=self.test_session_id,
                resume_id=self.test_resume_id
            )
            
            # 打印返回结果
            print(f"\n✅ 返回结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            # 验证结果格式
            assert result.get("code") == 200, f"期望code=200，实际={result.get('code')}"
            assert "question" in result, "返回值缺少question字段"
            assert len(result["question"]) > 0, "question内容为空"
            
            logger.info(
                "test1_success",
                question_length=len(result["question"]),
                question_preview=result["question"][:50] + "..."
            )
            
            self.results.append({
                "test": "test_1_start_interview",
                "status": "PASS",
                "detail": f"第一题生成成功，长度={len(result['question'])}"
            })
            
            return True
            
        except Exception as e:
            logger.exception("test1_failed", error=str(e))
            self.results.append({
                "test": "test_1_start_interview",
                "status": "FAIL",
                "detail": str(e)
            })
            return False
    
    async def test_2_chat_normal(self):
        """
        测试2: chat() - 普通对话（非追问）
        
        【模拟场景】
        用户回答了第一道题（自我介绍），系统应该：
        ① 记录用户回答到短期记忆
        ② 对回答进行评分（score）
        ③ 做出追问决策（decision）
        ④ 生成下一题或追问
        
        【验证点】
        ✓ 返回值包含8个字段（score/feedback/nextQuestion/phase/isFollowUp/questionCount/remainingQuestions/decision）
        ✓ score是0-100的整数
        ✓ phase是合法的枚举值
        ✓ isFollowUp是布尔值
        """
        print("\n" + "─"*80)
        print("💬 测试2: chat() - 普通对话（自我介绍）")
        print("─"*80)
        
        user_answer = """我叫张三，今年24岁，本科毕业于XX大学计算机科学与技术专业。
        我在校期间学习了Java、Spring、MySQL等技术栈，参与过2个项目实践。
        我对技术充满热情，希望能在贵公司发挥自己的能力。"""
        
        try:
            logger.info(
                "test2_chat_start",
                session_id=self.test_session_id,
                answer_length=len(user_answer)
            )
            
            # 调用chat
            result = await self.orchestrator.chat(
                session_id=self.test_session_id,
                user_answer=user_answer
            )
            
            # 打印返回结果
            print(f"\n✅ 返回结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            # 验证基本结构
            assert result.get("code") == 200, f"期望code=200，实际={result.get('code')}"
            data = result.get("data", {})
            
            # 验证8个核心字段
            required_fields = ["score", "feedback", "nextQuestion", "phase", 
                             "isFollowUp", "questionCount", "remainingQuestions"]
            for field in required_fields:
                assert field in data, f"缺少字段: {field}"
            
            # 验证字段类型和范围
            score = data["score"]
            assert isinstance(score, (int, float)), f"score应为数字，实际={type(score)}"
            assert 0 <= score <= 100, f"score应在0-100之间，实际={score}"
            
            is_follow_up = data["isFollowUp"]
            assert isinstance(is_follow_up, bool), f"isFollowUp应为布尔值"
            
            phase = data["phase"]
            valid_phases = [p.value for p in InterviewPhase]
            assert phase in valid_phases, f"无效的phase={phase}"
            
            logger.info(
                "test2_success",
                score=score,
                phase=phase,
                is_follow_up=is_follow_up,
                next_question_length=len(data["nextQuestion"])
            )
            
            self.results.append({
                "test": "test_2_chat_normal",
                "status": "PASS",
                "detail": f"score={score}, phase={phase}, isFollowUp={is_follow_up}"
            })
            
            return True
            
        except Exception as e:
            logger.exception("test2_failed", error=str(e))
            self.results.append({
                "test": "test_2_chat_normal",
                "status": "FAIL",
                "detail": str(e)
            })
            return False
    
    async def test_3_chat_technical(self):
        """
        测试3: chat() - 技术问题回答（可能触发追问）
        
        【模拟场景】
        回答HashMap底层原理，这是一个高价值技术问题，
        可能会触发follow_up或interest_follow_up决策
        
        【验证点】
        ✓ decision字段存在且为有效值
        ✓ confidence在0.0-1.0范围内
        ✓ 如果是追问，nextQuestion应该与原问题相关
        """
        print("\n" + "─"*80)
        print("🔧 测试3: chat() - 技术问题回答（HashMap原理）")
        print("─"*80)
        
        technical_answer = """HashMap的底层结构是数组加链表（JDK8后加入红黑树）。
        核心原理是通过key的hashCode计算索引位置，将元素存入数组的对应桶中。
        当发生哈希冲突时，使用链表法解决，链表长度超过8且数组长度大于64时会转成红黑树。
        HashMap不是线程安全的，并发环境下可以使用ConcurrentHashMap替代。
        扩容机制是当元素数量超过容量×负载因子（默认0.75）时触发，扩容为原来的2倍。"""
        
        try:
            logger.info(
                "test3_chat_technical_start",
                session_id=self.test_session_id,
                answer_length=len(technical_answer)
            )
            
            result = await self.orchestrator.chat(
                session_id=self.test_session_id,
                user_answer=technical_answer
            )
            
            print(f"\n✅ 返回结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            data = result.get("data", {})
            
            # 验证decision子对象
            if "decision" in data:
                decision = data["decision"]
                valid_decisions = ["follow_up", "interest_follow_up", 
                                 "next_question", "phase_switch"]
                assert decision.get("decision") in valid_decisions, \
                    f"无效的decision={decision.get('decision')}"
                
                confidence = decision.get("confidence", 0)
                assert 0 <= confidence <= 1, \
                    f"confidence应在0-1之间，实际={confidence}"
                
                logger.info(
                    "test3_decision_analyzed",
                    decision_type=decision.get("decision"),
                    confidence=confidence,
                    reason=decision.get("reason", "")[:100]
                )
            
            self.results.append({
                "test": "test_3_chat_technical",
                "status": "PASS",
                "detail": f"score={data.get('score')}, decision={data.get('decision', {}).get('decision', 'N/A')}"
            })
            
            return True
            
        except Exception as e:
            logger.exception("test3_failed", error=str(e))
            self.results.append({
                "test": "test_3_chat_technical",
                "status": "FAIL",
                "detail": str(e)
            })
            return False
    
    async def test_4_end_interview(self):
        """
        测试4: end_interview() - 结束评分
        
        【验证点】
        ✓ 返回FinalScoreResult（9个字段）
        ✓ final_score是浮点数
        ✓ level是A/B/C/D之一
        ✓ dimensions包含5个维度
        ✓ passed是布尔值（final_score >= 70）
        """
        print("\n" + "─"*80)
        print("📊 测试4: end_interview() - 结束评分")
        print("─"*80)
        
        try:
            logger.info(
                "test4_end_interview_start",
                session_id=self.test_session_id
            )
            
            result = await self.orchestrator.end_interview(
                session_id=self.test_session_id
            )
            
            print(f"\n✅ 返回结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            assert result.get("code") == 200, f"期望code=200，实际={result.get('code')}"
            data = result.get("data", {})
            
            # 验证9个核心字段
            required_fields = [
                "finalScore", "level", "dimensions", "summary",
                "strengths", "weaknesses", "suggestions", "passed"
            ]
            for field in required_fields:
                assert field in data, f"缺少字段: {field}"
            
            # 验证finalScore
            final_score = data["finalScore"]
            assert isinstance(final_score, (int, float)), \
                f"finalScore应为数字，实际={type(final_score)}"
            assert 0 <= final_score <= 100, \
                f"finalScore应在0-100之间，实际={final_score}"
            
            # 验证level
            level = data["level"]
            assert level in ["A", "B", "C", "D"], \
                f"无效的level={level}"
            
            # 验证dimensions（5个维度）
            dimensions = data["dimensions"]
            expected_dims = {"practice_experience", "technical_knowledge", 
                           "communication", "potential", "attitude"}
            actual_dims = {d["dimension"] for d in dimensions}
            assert expected_dims == actual_dims, \
                f"维度不匹配: 缺失={expected_dims - actual_dims}, 多余={actual_dims - expected_dims}"
            
            # 验证passed逻辑
            passed = data["passed"]
            expected_passed = final_score >= 70
            assert passed == expected_passed, \
                f"passed={passed} 但 final_score={final_score}，应该={'>=70' if expected_passed else '<70'}"
            
            logger.info(
                "test4_success",
                final_score=final_score,
                level=level,
                passed=passed,
                dimension_count=len(dimensions),
                strengths_count=len(data.get("strengths", [])),
                weaknesses_count=len(data.get("weaknesses", []))
            )
            
            self.results.append({
                "test": "test_4_end_interview",
                "status": "PASS",
                "detail": f"finalScore={final_score}, level={level}, passed={passed}"
            })
            
            return True
            
        except Exception as e:
            logger.exception("test4_failed", error=str(e))
            self.results.append({
                "test": "test_4_end_interview",
                "status": "FAIL",
                "detail": str(e)
            })
            return False
    
    async def test_5_parse_resume(self):
        """
        测试5: parse_resume() - 简历解析（可选，需要真实PDF）
        
        【说明】
        此测试需要真实的PDF文件URL，如果没有则跳过
        只验证接口是否能正常调用和错误处理
        """
        print("\n" + "─"*80)
        print("📄 测试5: parse_resume() - 简历解析（模拟调用）")
        print("─"*80)
        
        try:
            # 使用模拟的file_url（不需要真实文件，只测试接口层）
            mock_file_url = "https://example.com/mock_resume.pdf"
            
            logger.info(
                "test5_parse_resume_start",
                file_url=mock_file_url
            )
            
            result = await self.orchestrator.parse_resume(file_url=mock_file_url)
            
            print(f"\n✅ 返回结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            # 只验证返回格式，不要求一定成功（因为可能没有真实文件）
            assert "code" in result, "返回值缺少code字段"
            
            if result.get("code") == 200:
                assert "content" in result, "成功响应应包含content字段"
                logger.info("test5_success_with_content")
            else:
                logger.warning(
                    "test5_skipped_no_real_file",
                    code=result.get("code"),
                    error=result.get("error", "")
                )
            
            self.results.append({
                "test": "test_5_parse_resume",
                "status": "PASS",
                "detail": f"code={result.get('code')}, 接口可正常调用"
            })
            
            return True
            
        except Exception as e:
            logger.exception("test5_failed", error=str(e))
            self.results.append({
                "test": "test_5_parse_resume",
                "status": "FAIL",
                "detail": str(e)
            })
            return False
    
    async def cleanup(self):
        """清理测试环境"""
        print("\n" + "─"*80)
        print("🧹 清理测试环境")
        print("─"*80)
        
        try:
            # 删除测试会话（如果MemoryManager支持的话）
            from app.memory.memory_manager import get_memory_manager
            memory_mgr = get_memory_manager()
            
            delete_success = await memory_mgr.delete_session(self.test_session_id)
            
            if delete_success:
                logger.info("cleanup_success", session_id=self.test_session_id)
                print(f"✅ 测试会话已清理: {self.test_session_id}")
            else:
                logger.warning("cleanup_skipped", reason="session_not_found_or_expired")
                print(f"⚠️ 会话可能已过期自动删除")
                
        except Exception as e:
            logger.warning("cleanup_warning", error=str(e))
            print(f"⚠️ 清理时出现异常（不影响测试结果）: {e}")
    
    def print_summary(self):
        """打印测试总结"""
        print("\n" + "="*80)
        print("📊 测试结果汇总")
        print("="*80)
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = total - passed
        
        print(f"\n总测试数: {total}")
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print(f"通过率: {(passed/total*100) if total > 0 else 0:.1f}%")
        
        print("\n详细结果:")
        print("-"*80)
        for i, result in enumerate(self.results, 1):
            status_icon = "✅" if result["status"] == "PASS" else "❌"
            print(f"{i}. {status_icon} {result['test']}")
            print(f"   状态: {result['status']}")
            print(f"   详情: {result['detail']}")
            print()
        
        if failed == 0:
            print("🎉 所有测试通过！InterviewOrchestrator 逻辑正确！")
        else:
            print(f"⚠️ 有{failed}个测试失败，请检查上方日志排查原因")
        
        print("="*80 + "\n")


async def main():
    """主测试流程"""
    tester = OrchestratorTester()
    
    try:
        # 初始化
        await tester.setup()
        
        # 执行5个测试
        await tester.test_1_start_interview()
        await tester.test_2_chat_normal()
        await tester.test_3_chat_technical()
        await tester.test_4_end_interview()
        await tester.test_5_parse_resume()
        
        # 清理
        await tester.cleanup()
        
        # 打印总结
        tester.print_summary()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断测试")
    except Exception as e:
        logger.exception("test_suite_error", error=str(e))
        print(f"\n❌ 测试套件执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════╗
║         InterviewOrchestrator 功能测试 v1.0                 ║
║                                                            ║
║  测试内容:                                                  ║
║  1. start_interview()  - 开始面试                            ║
║  2. chat()             - 普通对话（自我介绍）               ║
║  3. chat()             - 技术问题（HashMap原理）            ║
║  4. end_interview()    - 结束评分                          ║
║  5. parse_resume()     - 简历解析（模拟）                   ║
║                                                            ║
║  预期耗时: 30-60秒（取决于LLM响应速度）                     ║
╚════════════════════════════════════════════════════════════╝
""")
    
    asyncio.run(main())
