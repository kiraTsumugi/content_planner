"""CLI 入口。

用法：
  python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05
  python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 -v
  python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 --json
  python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 --trace out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .agent.llm import ModelClient
from .agent.react_loop import Result, run
from .agent.tools import PlanStore, Tools

STATUS_LABEL = {
    "draft_saved": "方案已保存",
    "needs_more_info": "资料不足，待补充",
    "incomplete": "未完成",
    "save_failed": "保存失败",
    "blocked": "已阻断",
}


def _to_dict(r: Result) -> dict:
    return {
        "status": r.status,
        "status_label": STATUS_LABEL.get(r.status, r.status),
        "topic": r.topic,
        "pending": r.pending,
        "final": r.final,
        "plan": r.run.to_dict() if r.run else None,
        "trace": [asdict(s) for s in r.trace],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="content-planner")
    p.add_argument("--topic", required=True, help="内容主题")
    p.add_argument("--budget", type=float, default=None, help="预算（模拟单位）")
    p.add_argument("--deadline", default=None, help="截止时间 YYYY-MM-DD")
    p.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    p.add_argument("--trace", default=None, help="将完整 trace 写入文件")
    p.add_argument("--offline", action="store_true", help="强制离线 Mock 模型")
    p.add_argument("--verbose", "-v", action="store_true", help="打印每步决策")
    args = p.parse_args(argv)

    model = ModelClient(offline=True if args.offline else None)
    tools = Tools(PlanStore())

    result = run(args.topic, args.budget, args.deadline, model=model, tools=tools)
    out = _to_dict(result)
    out["model_mode"] = model.mode

    if args.trace:
        with open(args.trace, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if result.status != "incomplete" else 2

    if args.verbose:
        print(f"[model] {model.mode}")
        for s in result.trace:
            print(f"  step {s.n}: {s.action} args={s.args}  ← {s.reason}")
            if s.observation:
                print(f"           obs={json.dumps(s.observation, ensure_ascii=False)[:150]}")

    print(f"\n主题: {result.topic}")
    print(f"状态: {STATUS_LABEL.get(result.status, result.status)}")
    print(f"决策依据: {result.final.get('reason', '')}")

    if result.run:
        print("\n任务计划 / 步骤状态:")
        if not result.run.steps:
            print("  (无步骤)")
        for s in result.run.steps:
            mark = {"success": "✓", "failed": "✗", "skipped": "-"}.get(s.status, "?")
            extra = f" 费用={s.cost}" if s.cost else ""
            print(f"  {mark} {s.name} [{s.status}]{extra}")
        print(f"费用合计: {result.run.total_cost} / 预算 {args.budget}"
              + ("  ⚠ 超预算" if args.budget is not None
                 and result.run.total_cost > args.budget else ""))
        if result.run.candidate_id:
            print(f"所选方案: {result.run.candidate_id}")

    if result.pending:
        print("待确认 / 缺口:")
        for item in result.pending:
            print(f"  - {item}")

    return 0 if result.status != "incomplete" else 2


if __name__ == "__main__":
    sys.exit(main())
