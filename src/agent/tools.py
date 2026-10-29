"""业务工具层。

铁律：工具只返回"事实"，绝不返回"决策"。
- search_materials 返回候选方案（数据驱动，模型据预算挑选）。
- generate_script 可能失败（故障注入）。
- estimate_cost 返回费用合计与是否超限（事实）。
- save_plan 唯一有副作用：幂等 + 可失败。

工具不判断"该选哪个方案""要不要重规划"——那是模型的活。
"""
from __future__ import annotations

from .models import PlanRun, load_json


class PlanStore:
    """方案内存存储。以 fingerprint 为键 → 天然幂等。"""

    def __init__(self):
        self._by_fp: dict[str, PlanRun] = {}

    def get(self, fp: str) -> PlanRun | None:
        return self._by_fp.get(fp)

    def put(self, run: PlanRun) -> None:
        self._by_fp[run.fingerprint] = run

    def all(self) -> list[PlanRun]:
        return list(self._by_fp.values())


class Tools:
    def __init__(self, store: PlanStore | None = None):
        self._materials = load_json("materials.json")["materials"]
        self._candidates = load_json("candidates.json")["candidates"]
        self._fees = load_json("fees.json")
        self.store = store or PlanStore()

    # --- 1. 素材检索：返回候选方案 ----------------------------------------
    def search_materials(self, topic: str) -> dict:
        return {
            "ok": True,
            "topic": topic,
            "candidates": [
                {"id": c["id"], "name": c["name"],
                 "estimated_cost": c["estimated_cost"],
                 "quality": c["quality"], "materials": c["materials"]}
                for c in self._candidates
            ],
            "material_count": len(self._materials),
        }

    def candidate_ids(self) -> list[str]:
        return [c["id"] for c in self._candidates]

    def get_candidate(self, cid: str) -> dict | None:
        return next((c for c in self._candidates if c["id"] == cid), None)

    # --- 2. 脚本生成：可能失败 --------------------------------------------
    def generate_script(self, topic: str, candidate_id: str) -> dict:
        inj = self._fees.get("_fail_injection", {})
        if topic in inj.get("topics", []) and inj.get("tool") == "script_gen":
            return {"ok": False, "error": "tool_error",
                    "tool": "script_gen",
                    "message": "脚本生成服务超时（故障注入）"}
        cand = self.get_candidate(candidate_id)
        if cand is None:
            return {"ok": False, "error": "bad_candidate", "candidate_id": candidate_id}
        fee = self._fees["tools"]["script_gen"]
        return {"ok": True, "tool": "script_gen",
                "candidate_id": candidate_id,
                "script": f"[{cand['name']}] 脚本草案：围绕「{topic}」展开",
                "cost": fee["cost_per_call"], "hours": fee["hours"]}

    # --- 3. 成本估算：返回费用与超限事实 ----------------------------------
    def estimate_cost(self, candidate_id: str, budget: float) -> dict:
        cand = self.get_candidate(candidate_id)
        if cand is None:
            return {"ok": False, "error": "bad_candidate", "candidate_id": candidate_id}
        base = cand["estimated_cost"]
        script_fee = self._fees["tools"]["script_gen"]["cost_per_call"]
        total = base + script_fee
        return {
            "ok": True,
            "candidate_id": candidate_id,
            "estimated_total": total,
            "budget": budget,
            "over_budget": total > budget,
            "shortfall": round(max(0.0, total - budget), 2),
        }

    # --- 4. 保存方案（唯一有副作用，幂等 + 可失败）------------------------
    def save_plan(self, run: PlanRun) -> dict:
        existing = self.store.get(run.fingerprint)
        if existing is not None:
            return {"ok": True, "status": "duplicate",
                    "fingerprint": run.fingerprint,
                    "message": "相同任务已有方案，未重复保存",
                    "plan": existing.to_dict()}
        self.store.put(run)
        return {"ok": True, "status": "saved",
                "fingerprint": run.fingerprint,
                "message": "方案已保存",
                "plan": run.to_dict()}
