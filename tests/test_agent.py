"""可执行测试：覆盖全部验收点 + 异常输入 + 安全场景 + 加分项（失败续跑）。

运行：python -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.llm import ModelClient
from src.agent.react_loop import MAX_STEPS, run
from src.agent.tools import PlanStore, Tools


def go(topic, budget, deadline, tools=None, model=None, resume=None):
    tools = tools or Tools(PlanStore())
    model = model or ModelClient(offline=True)
    return run(topic, budget, deadline, model=model, tools=tools, resume=resume), tools


class TestNormalCompletion(unittest.TestCase):
    def test_plan_saved_within_budget(self):
        r, tools = go("秋季营销", 10, "2026-11-05")
        self.assertEqual(r.status, "draft_saved")
        self.assertEqual(len(tools.store.all()), 1)
        self.assertLessEqual(r.run.total_cost, 10)

    def test_all_steps_success(self):
        r, _ = go("秋季营销", 10, "2026-11-05")
        self.assertTrue(all(s.status == "success" for s in r.run.steps))

    def test_never_claims_published(self):
        r, _ = go("秋季营销", 10, "2026-11-05")
        blob = json.dumps({"final": r.final, "pending": r.pending}, ensure_ascii=False)
        self.assertNotIn("已发布", blob)
        self.assertNotIn("published", blob)


class TestBudgetOverrunReplanning(unittest.TestCase):
    """核心：观察到超预算后改选替代方案（对应参考实例）。"""

    def test_replan_on_over_budget(self):
        r, tools = go("秋季营销", 10, "2026-11-05")
        # 先估 premium(13) 超预算，再改选 standard(9)
        est_actions = [s for s in r.trace if s.action == "estimate_cost"]
        self.assertGreaterEqual(len(est_actions), 2)
        self.assertEqual(est_actions[0].args["candidate_id"], "PLAN_PREMIUM")
        self.assertEqual(est_actions[1].args["candidate_id"], "PLAN_STANDARD")
        # 最终保存的是可负担方案
        self.assertEqual(r.run.candidate_id, "PLAN_STANDARD")
        self.assertEqual(r.run.total_cost, 9)

    def test_infeasible_budget_returns_gap(self):
        r, tools = go("秋季营销", 3, "2026-11-05")
        self.assertEqual(r.status, "incomplete")
        self.assertEqual(len(tools.store.all()), 0)  # 无解不保存
        self.assertTrue(any("缺口" in p for p in r.pending))
        self.assertIn("最低需", r.final.get("reason", ""))


class TestMissingInput(unittest.TestCase):
    def test_missing_budget(self):
        r, _ = go("秋季营销", None, "2026-11-05")
        self.assertEqual(r.status, "needs_more_info")
        self.assertTrue(any("budget" in p for p in r.pending))

    def test_missing_deadline(self):
        r, _ = go("秋季营销", 10, None)
        self.assertEqual(r.status, "needs_more_info")
        self.assertTrue(any("deadline" in p for p in r.pending))

    def test_missing_both(self):
        r, _ = go("秋季营销", None, None)
        self.assertEqual(r.status, "needs_more_info")
        blob = " ".join(r.pending)
        self.assertIn("budget", blob)
        self.assertIn("deadline", blob)


class TestToolFailure(unittest.TestCase):
    """工具失败：保留已成功步骤，绝不把失败记成成功。"""

    def test_failure_preserves_successful_steps(self):
        r, tools = go("故障演练", 10, "2026-11-05")  # 故障注入触发 script_gen 失败
        self.assertEqual(r.status, "incomplete")
        statuses = {s.tool: s.status for s in r.run.steps}
        self.assertEqual(statuses.get("search_materials"), "success")
        self.assertEqual(statuses.get("estimate_cost"), "success")
        self.assertEqual(statuses.get("generate_script"), "failed")

    def test_failed_step_not_recorded_as_success(self):
        r, _ = go("故障演练", 10, "2026-11-05")
        failed = [s for s in r.run.steps if s.tool == "generate_script"]
        self.assertTrue(failed)
        self.assertTrue(all(s.status == "failed" for s in failed))
        self.assertEqual(len([s for s in r.run.steps if s.status == "success" and
                              s.tool == "generate_script"]), 0)

    def test_no_plan_saved_on_failure(self):
        r, tools = go("故障演练", 10, "2026-11-05")
        self.assertEqual(len(tools.store.all()), 0)


class TestIdempotency(unittest.TestCase):
    def test_duplicate_run_single_plan(self):
        tools = Tools(PlanStore())
        model = ModelClient(offline=True)
        run("秋季营销", 10, "2026-11-05", model=model, tools=tools)
        r2 = run("秋季营销", 10, "2026-11-05", model=model, tools=tools)
        self.assertEqual(len(tools.store.all()), 1)
        self.assertIn("幂等", r2.final.get("reason", ""))

    def test_different_task_new_plan(self):
        tools = Tools(PlanStore())
        model = ModelClient(offline=True)
        run("秋季营销", 10, "2026-11-05", model=model, tools=tools)
        run("冬季营销", 10, "2026-11-05", model=model, tools=tools)
        self.assertEqual(len(tools.store.all()), 2)


class TestResume(unittest.TestCase):
    """加分项：失败步骤续跑——不重做已成功步骤。"""

    def test_resume_skips_completed_steps(self):
        tools = Tools(PlanStore())
        model = ModelClient(offline=True)
        r1 = run("故障演练", 10, "2026-11-05", model=model, tools=tools)
        self.assertEqual(r1.status, "incomplete")
        # 续跑：不应重做 search_materials / estimate_cost
        r2 = run("故障演练", 10, "2026-11-05", model=model, tools=tools,
                 resume=r1.run)
        actions = [s.action for s in r2.trace]
        self.assertNotIn("search_materials", actions)
        self.assertNotIn("estimate_cost", actions)
        self.assertIn("generate_script", actions)

    def test_resume_inherits_successful_steps(self):
        tools = Tools(PlanStore())
        model = ModelClient(offline=True)
        r1 = run("故障演练", 10, "2026-11-05", model=model, tools=tools)
        r2 = run("故障演练", 10, "2026-11-05", model=model, tools=tools,
                 resume=r1.run)
        inherited = {s.tool for s in r2.run.steps if s.status == "success"}
        self.assertIn("search_materials", inherited)
        self.assertIn("estimate_cost", inherited)


class TestMalformedModelOutput(unittest.TestCase):
    """真实模型可能返回非预期输出；循环必须不崩溃。"""

    def test_unknown_action_does_not_crash(self):
        class M:
            mode = "bad"

            def decide(self, s, m):
                return {"action": "fly_to_moon", "args": {}}

        r = run("秋季营销", 10, "2026-11-05", model=M(), tools=Tools(PlanStore()))
        self.assertEqual(r.status, "incomplete")
        self.assertGreaterEqual(len(r.trace), 2)

    def test_non_dict_action_does_not_crash(self):
        class M:
            mode = "bad"

            def decide(self, s, m):
                return "plain text, not json"

        r = run("秋季营销", 10, "2026-11-05", model=M(), tools=Tools(PlanStore()))
        self.assertEqual(r.status, "incomplete")

    def test_bad_candidate_does_not_crash(self):
        r, _ = go("秋季营销", 10, "2026-11-05")
        # 直接测工具层容错
        tools = Tools(PlanStore())
        self.assertFalse(tools.estimate_cost("NO_SUCH", 10)["ok"])
        self.assertFalse(tools.generate_script("t", "NO_SUCH")["ok"])


class TestStepLimit(unittest.TestCase):
    def test_max_steps_returns_incomplete(self):
        class LoopingModel:
            mode = "loop"

            def decide(self, s, m):
                return {"action": "search_materials", "args": {"topic": "x"}}

        r = run("秋季营销", 10, "2026-11-05", model=LoopingModel(),
                tools=Tools(PlanStore()))
        self.assertEqual(r.status, "incomplete")
        self.assertTrue(any("超限" in p for p in r.pending))
        self.assertLessEqual(len([s for s in r.trace if s.action != "abort"]), MAX_STEPS)


class TestCostIntegrity(unittest.TestCase):
    """安全：费用计算准确，无虚报。"""

    def test_total_cost_matches_candidate(self):
        r, _ = go("秋季营销", 10, "2026-11-05")
        # standard(8) + script(1) = 9
        self.assertEqual(r.run.total_cost, 9)

    def test_over_budget_never_saved(self):
        r, tools = go("秋季营销", 10, "2026-11-05")
        self.assertLessEqual(r.run.total_cost, r.run.budget)
        for p in tools.store.all():
            self.assertLessEqual(p.total_cost, p.budget)


if __name__ == "__main__":
    unittest.main()
