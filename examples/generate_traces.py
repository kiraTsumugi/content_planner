#!/usr/bin/env python3
"""生成 examples/ 下的运行记录（Trace + CLI 实际输出）。

运行：python examples/generate_traces.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.llm import ModelClient
from src.agent.react_loop import run
from src.agent.tools import PlanStore, Tools

EX = ROOT / "examples"

CASES = [
    ("normal", "秋季营销", 10, "2026-11-05", "正常完成（含超预算重规划）"),
    ("over_budget_no_solution", "秋季营销", 3, "2026-11-05", "预算超限：无可行方案，返回缺口"),
    ("missing_budget", "秋季营销", None, "2026-11-05", "缺预算"),
    ("missing_deadline", "秋季营销", 10, None, "缺截止时间"),
    ("tool_failure", "故障演练", 10, "2026-11-05", "工具失败：保留已成功步骤"),
    ("duplicate", "秋季营销", 10, "2026-11-05", "重复执行：只存一份方案"),
]


def main():
    EX.mkdir(exist_ok=True)
    index = []
    for name, topic, budget, deadline, desc in CASES:
        tools = Tools(PlanStore())
        model = ModelClient(offline=True)
        if name == "duplicate":
            run(topic, budget, deadline, model=model, tools=tools)
            r = run(topic, budget, deadline, model=model, tools=tools)
        else:
            r = run(topic, budget, deadline, model=model, tools=tools)
        record = {
            "case": name,
            "description": desc,
            "topic": topic, "budget": budget, "deadline": deadline,
            "model_mode": model.mode,
            "status": r.status,
            "pending": r.pending,
            "final": r.final,
            "plan": r.run.to_dict() if r.run else None,
            "plan_count": len(tools.store.all()),
            "trace": [vars(s) for s in r.trace],
        }
        (EX / f"trace_{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [sys.executable, "-m", "src.main", "--topic", topic, "--offline"]
        if budget is not None:
            cmd += ["--budget", str(budget)]
        if deadline is not None:
            cmd += ["--deadline", deadline]
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        (EX / f"run_{name}.txt").write_text(out.stdout, encoding="utf-8")
        index.append((name, desc, r.status, len(tools.store.all())))
        print(f"[{name}] status={r.status} plans={len(tools.store.all())}")

    # 额外：失败续跑（加分项）的 Trace
    tools = Tools(PlanStore())
    model = ModelClient(offline=True)
    r1 = run("故障演练", 10, "2026-11-05", model=model, tools=tools)
    r2 = run("故障演练", 10, "2026-11-05", model=model, tools=tools, resume=r1.run)
    resume_rec = {
        "case": "resume",
        "description": "失败续跑：继承已成功步骤，不重做检索与估算（加分项）",
        "first_run": {"status": r1.status,
                      "steps": [s.to_dict() for s in r1.run.steps]},
        "resume_run": {"status": r2.status,
                       "actions": [s.action for s in r2.trace],
                       "steps": [s.to_dict() for s in r2.run.steps]},
    }
    (EX / "trace_resume.json").write_text(
        json.dumps(resume_rec, ensure_ascii=False, indent=2), encoding="utf-8")
    index.append(("resume", "失败续跑（加分项）", r2.status, 0))
    print(f"[resume] 续跑动作={[s.action for s in r2.trace]}")

    lines = ["# 运行记录索引", "",
             "| 用例 | 场景 | 最终状态 | 方案数 | Trace | CLI 输出 |",
             "|---|---|---|---|---|---|"]
    for name, desc, status, n in index:
        cli = f"[run_{name}.txt](run_{name}.txt)" if (EX / f"run_{name}.txt").exists() else "—"
        lines.append(f"| {name} | {desc} | `{status}` | {n} | "
                     f"[trace_{name}.json](trace_{name}.json) | {cli} |")
    (EX / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written to", EX)


if __name__ == "__main__":
    main()
