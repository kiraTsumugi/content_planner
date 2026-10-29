"""ReAct 决策循环。

循环骨架：模型输出动作 → 执行工具 → 观察结果喂回模型 → 模型决定下一步。
硬约束：
- 步数上限 MAX_STEPS，达到即返回 incomplete，绝不假装成功。
- 已成功步骤保留在 PlanRun.steps 里，重规划/续跑不丢。
- 失败步骤标 failed，绝不记成 success。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import ModelClient
from .models import (FAILED, SUCCESS, PlanRun, Step, Task)
from .tools import Tools

MAX_STEPS = 10
TOOL_ACTIONS = {"search_materials", "generate_script", "estimate_cost", "save_plan"}
TOOL_STEP_NAME = {
    "search_materials": "素材检索",
    "generate_script": "脚本生成",
    "estimate_cost": "成本估算",
    "save_plan": "方案保存",
}

SYSTEM_PROMPT = """你是"内容任务规划 Agent"。职责：在给定预算与截止时间内，完成一份内容活动方案。

只能通过 JSON 动作调用工具：
- {"action":"search_materials","args":{"topic":"..."},"reason":"..."}
- {"action":"estimate_cost","args":{"candidate_id":"...","budget":N},"reason":"..."}
- {"action":"generate_script","args":{"topic":"...","candidate_id":"..."},"reason":"..."}
- {"action":"save_plan","args":{"candidate_id":"..."},"reason":"..."}
结束用：{"action":"finish","status":"draft_saved|needs_more_info|incomplete|save_failed|blocked","reason":"...","pending":["..."]}

铁律：
1. 成本超预算时，改选更便宜的替代方案，而非放弃。
2. 工具失败时，保留已成功步骤的结果，尝试替代方案；无解则返回未完成与缺口。
3. 绝不在无可行方案时声称成功。
4. 每次只输出一个 JSON 动作。"""


@dataclass
class TraceStep:
    n: int
    action: str
    args: dict
    reason: str
    observation: dict | None = None


@dataclass
class Result:
    status: str
    topic: str
    trace: list[TraceStep] = field(default_factory=list)
    final: dict = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)
    run: PlanRun | None = None


def run(topic: str, budget: float | None, deadline: str | None,
        model: ModelClient | None = None, tools: Tools | None = None,
        resume: PlanRun | None = None) -> Result:
    model = model or ModelClient()
    tools = tools or Tools()

    task = Task(topic=topic, budget=budget, deadline=deadline)
    plan = PlanRun(task_id=topic or "<none>", topic=topic or "",
                   budget=budget if budget is not None else 0.0,
                   deadline=deadline or "")

    # 续跑：继承上次的已成功步骤（含结果与费用），失败步骤不继承。
    # 这样"失败步骤续跑"不会重做已完成的活，也绝不把失败记成成功。
    resumed_note = ""
    if resume is not None:
        for s in resume.steps:
            if s.status == SUCCESS:
                plan.steps.append(Step(name=s.name, tool=s.tool, status=SUCCESS,
                                       cost=s.cost, result=s.result))
        if resume.accepted_estimate:
            plan.accepted_estimate = resume.accepted_estimate
            plan.candidate_id = resume.candidate_id
        resumed_note = "（续跑：已完成步骤将被继承，不重做）"

    intent = json.dumps({
        "task": f"为「{topic}」在预算 {budget}、截止 {deadline} 内规划内容活动方案{resumed_note}",
        "topic": topic, "budget": budget, "deadline": deadline,
        "missing": task.missing,
    }, ensure_ascii=False)

    messages: list[dict] = [{"role": "user", "content": intent}]
    # 把已成功步骤的"动作+观察"注入历史，让模型据此跳过已完成步骤。
    if resume is not None:
        for s in plan.steps:
            messages.append({"role": "assistant", "content": json.dumps(
                {"action": s.tool, "args": {}, "reason": "（续跑，已完成）"},
                ensure_ascii=False)})
            messages.append({"role": "user", "content": json.dumps(
                s.result or {}, ensure_ascii=False)})
    trace: list[TraceStep] = []

    for step_no in range(1, MAX_STEPS + 1):
        action = model.decide(SYSTEM_PROMPT, messages)

        # 契约校验：真实模型可能返回非 dict
        if not isinstance(action, dict):
            trace.append(TraceStep(step_no, "<invalid>", {}, "模型返回非结构化输出",
                                   {"error": "invalid_action"}))
            messages.append({"role": "user", "content": json.dumps(
                {"error": "invalid_action", "hint": "只输出一个 JSON 动作"})})
            continue

        name = action.get("action", "")
        args = action.get("args", {}) or {}
        reason = action.get("reason", "")
        ts = TraceStep(step_no, name, args, reason)

        if name == "finish":
            ts.observation = {"finished": True, "status": action.get("status")}
            trace.append(ts)
            return Result(status=action.get("status", "incomplete"), topic=topic,
                          trace=trace, final=action,
                          pending=action.get("pending", []), run=plan)

        if name in TOOL_ACTIONS:
            obs = _dispatch(tools, name, args, topic, budget, messages, plan)
            ts.observation = obs
            trace.append(ts)
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": json.dumps(obs, ensure_ascii=False)})
            continue

        # 未知动作：喂回错误自纠
        ts.observation = {"error": "unknown_action", "action": name}
        trace.append(ts)
        messages.append({"role": "user", "content": json.dumps(
            {"error": "unknown_action", "action": name, "hint": "重选合法动作"})})

    trace.append(TraceStep(MAX_STEPS + 1, "abort", {}, "达到步数上限",
                           {"error": "max_steps_exceeded"}))
    return Result(status="incomplete", topic=topic, trace=trace,
                  final={"reason": f"达到最大步数 {MAX_STEPS} 仍未完成"},
                  pending=["执行步数超限，未完成任务"], run=plan)


def _dispatch(tools: Tools, name: str, args: dict, topic: str,
              budget: float | None, messages: list[dict], plan: PlanRun) -> dict:
    if name == "search_materials":
        obs = tools.search_materials(args.get("topic", topic))
        _record(plan, "search_materials", obs, cost=0.0)
        return obs
    if name == "generate_script":
        obs = tools.generate_script(args.get("topic", topic),
                                    args.get("candidate_id", ""))
        if obs.get("ok"):
            _record(plan, "generate_script", obs, cost=obs.get("cost", 0.0))
        else:
            _record_failed(plan, "generate_script", obs)
        return obs
    if name == "estimate_cost":
        obs = tools.estimate_cost(args.get("candidate_id", ""),
                                  args.get("budget", budget or 0))
        _record(plan, "estimate_cost", obs, cost=0.0)
        if obs.get("ok") and not obs.get("over_budget"):
            plan.candidate_id = obs.get("candidate_id", plan.candidate_id)
            plan.accepted_estimate = obs
        return obs
    if name == "save_plan":
        cand = args.get("candidate_id", "") or plan.candidate_id
        plan.candidate_id = cand
        # 为保存补一条成功步骤（若尚未有）
        if plan.find("save_plan") is None:
            plan.steps.append(Step(name=TOOL_STEP_NAME["save_plan"],
                                   tool="save_plan", status=SUCCESS))
        return tools.save_plan(plan)
    return {"ok": False, "error": "unknown_action", "action": name}


def _record(plan: PlanRun, tool: str, obs: dict, cost: float) -> None:
    """记录一次成功的工具步骤（同工具多次调用则合并为最新）。"""
    step = plan.find(tool)
    if step is None:
        plan.steps.append(Step(name=TOOL_STEP_NAME.get(tool, tool), tool=tool,
                               status=SUCCESS, cost=cost, result=obs))
    else:
        step.status = SUCCESS
        step.cost = cost
        step.result = obs


def _record_failed(plan: PlanRun, tool: str, obs: dict) -> None:
    """记录失败步骤——status=failed，绝不记成 success。"""
    step = plan.find(tool)
    if step is None:
        plan.steps.append(Step(name=TOOL_STEP_NAME.get(tool, tool), tool=tool,
                               status=FAILED, cost=0.0, result=obs))
    else:
        step.status = FAILED
        step.cost = 0.0
        step.result = obs
