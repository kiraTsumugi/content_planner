"""模型接入层。

两种后端：
1. 真实模型：任意 OpenAI 兼容端点，仅用标准库 urllib。
2. 离线 Mock：无 API key 时自动降级。消费工具返回的"事实"做确定性重规划。

边界声明：Mock 只验证流程、边界与重规划逻辑，不证明真实模型决策效果。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SCRIPT_FEE = 1  # 脚本生成费（与 data/fees.json 一致）


class ModelClient:
    def __init__(self, offline: bool | None = None):
        self.base_url = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("MODEL_API_KEY", "")
        self.model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        if offline is None:
            offline = not (self.base_url and self.api_key)
        self.offline = offline

    @property
    def mode(self) -> str:
        return "offline-mock" if self.offline else f"live:{self.model}"

    def decide(self, system: str, messages: list[dict]) -> dict:
        if self.offline:
            return OfflineMock.decide(messages)
        return self._call_live(system, messages)

    def _call_live(self, system: str, messages: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            return _parse_action(body["choices"][0]["message"]["content"])
        except urllib.error.URLError as e:
            raise RuntimeError(f"model_call_failed: {e}") from e


def _parse_action(content: str) -> dict:
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


class OfflineMock:
    """确定性重规划器。

    关键：消费"工具事实"而非预设剧本。预算超限 → 换更便宜候选；
    工具失败 → 尝试替代，无解则返回缺口；已成功步骤保留。
    """

    MAX_SCRIPT_ATTEMPTS = 2

    @staticmethod
    def decide(messages: list[dict]) -> dict:
        f = OfflineMock._collect(messages)
        task = f["task"]
        used = f["used"]

        # 必填项缺失 → 请求补充（不调任何工具）
        if task.get("missing"):
            return {"action": "finish", "status": "needs_more_info",
                    "reason": "任务信息缺失：" + "、".join(task["missing"]),
                    "pending": ["请补充：" + "、".join(task["missing"])]}

        budget = task["budget"]

        # 步骤1：素材检索
        if "search_materials" not in used:
            return {"action": "search_materials",
                    "args": {"topic": task["topic"]},
                    "reason": "检索候选方案"}

        candidates = f["search"]["candidates"]
        order = {"high": 0, "medium": 1, "low": 2}
        candidates = sorted(candidates, key=lambda c: order.get(c["quality"], 9))
        tried = {e["candidate_id"] for e in f["estimates"]}

        # 步骤2：估算。首次估最高质量方案（不论是否超预算），
        # 观察到超预算事实后再改选替代 —— 这才体现 ReAct 的"观察→调整"。
        if not f["estimates"]:
            pick = candidates[0]
            return {"action": "estimate_cost",
                    "args": {"candidate_id": pick["id"], "budget": budget},
                    "reason": f"估算首选方案 {pick['name']}（预估 {pick['estimated_cost']}）"}

        if f["last_estimate"].get("over_budget"):
            # 观察到超预算 → 改选可负担且未试过的替代方案
            feasible = [c for c in candidates
                        if c["id"] not in tried
                        and c["estimated_cost"] + SCRIPT_FEE <= budget]
            if feasible:
                pick = feasible[0]
                return {"action": "estimate_cost",
                        "args": {"candidate_id": pick["id"], "budget": budget},
                        "reason": f"上一方案超预算 {f['last_estimate'].get('shortfall')}，"
                                  f"改选替代 {pick['name']}（预估 {pick['estimated_cost']}）"}
            # 无可行替代 → 返回未完成与缺口
            cheapest = min(candidates, key=lambda c: c["estimated_cost"])
            cheapest_total = cheapest["estimated_cost"] + SCRIPT_FEE
            return {"action": "finish", "status": "incomplete",
                    "reason": f"预算 {budget} 下无可行方案，最低需 {cheapest_total}",
                    "pending": [f"预算缺口 {round(cheapest_total - budget, 2)}，请提高预算或缩减范围"]}

        chosen = f["last_estimate"]["candidate_id"]

        # 步骤3：生成脚本（可能失败）
        if "generate_script" not in used:
            return {"action": "generate_script",
                    "args": {"topic": task["topic"], "candidate_id": chosen},
                    "reason": f"为方案 {chosen} 生成脚本"}

        # 脚本失败 → 尝试替代候选
        if not f["last_script"].get("ok"):
            scripted = f["scripted_candidates"]
            feasible = [c for c in candidates
                        if c["estimated_cost"] + SCRIPT_FEE <= budget
                        and c["id"] not in scripted]
            if feasible and len(scripted) < OfflineMock.MAX_SCRIPT_ATTEMPTS:
                return {"action": "generate_script",
                        "args": {"topic": task["topic"], "candidate_id": feasible[0]["id"]},
                        "reason": "脚本生成失败，改试替代方案"}
            return {"action": "finish", "status": "incomplete",
                    "reason": "脚本生成工具失败，无可替代方案；已保留检索与估算结果",
                    "pending": ["脚本生成服务不可用，请稍后重试（已完成步骤可续跑）"]}

        # 步骤4：保存方案
        if "save_plan" not in used:
            return {"action": "save_plan",
                    "args": {"candidate_id": chosen},
                    "reason": "保存最终方案"}

        save = f["last_save"] or {}
        if not save.get("ok"):
            return {"action": "finish", "status": "save_failed",
                    "reason": "方案保存失败：" + save.get("message", ""),
                    "pending": ["保存失败，请重试"]}
        return {"action": "finish", "status": "draft_saved",
                "reason": "方案已保存" + ("（幂等，未重复保存）"
                          if save.get("status") == "duplicate" else ""),
                "pending": []}

    @staticmethod
    def _collect(messages: list[dict]) -> dict:
        used: list[str] = []
        task = {}
        search = None
        estimates: list[dict] = []
        scripts: list[dict] = []
        save = None
        scripted_any: list[str] = []  # 所有尝试过脚本生成的候选（含失败）
        for m in messages:
            if m.get("role") == "assistant":
                try:
                    a = _parse_action(m.get("content", ""))
                except Exception:
                    continue
                name = a.get("action")
                if name in ("search_materials", "generate_script",
                            "estimate_cost", "save_plan"):
                    used.append(name)
                if name == "generate_script":
                    cid = a.get("args", {}).get("candidate_id")
                    if cid:
                        scripted_any.append(cid)
            if m.get("role") in ("tool", "user"):
                try:
                    obs = json.loads(m.get("content", ""))
                except Exception:
                    continue
                if not isinstance(obs, dict):
                    continue
                if "topic" in obs and "budget" in obs and "deadline" in obs:
                    task = obs
                elif "candidates" in obs:
                    search = obs
                elif "estimated_total" in obs:
                    estimates.append(obs)
                elif obs.get("tool") == "script_gen":
                    scripts.append(obs)
                elif obs.get("error") == "tool_error":
                    scripts.append(obs)
                elif "plan" in obs:
                    save = obs
        return {
            "used": used, "task": task, "search": search,
            "estimates": estimates, "scripts": scripts, "save": save,
            "last_estimate": estimates[-1] if estimates else {},
            "last_script": scripts[-1] if scripts else {},
            "last_save": save,
            "scripted_candidates": scripted_any,
        }
