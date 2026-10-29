"""核心数据结构。

设计原则：把"特殊情况"从代码里删掉，放进数据与状态里。
- 步骤状态正交：pending / success / failed / skipped —— 失败绝不记成成功。
- 幂等键来自数据结构本身（PlanRun.fingerprint），不是额外去重逻辑。
- 已成功步骤的结果挂在 Step 上，重规划/续跑时天然保留。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# 步骤状态（正交，互斥）
PENDING = "pending"
SUCCESS = "success"
FAILED = "failed"
SKIPPED = "skipped"


def load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Task:
    topic: str
    budget: float
    deadline: str

    @property
    def missing(self) -> list[str]:
        """缺失的必填项。"""
        miss = []
        if not self.topic:
            miss.append("topic")
        if self.budget is None:
            miss.append("budget")
        if not self.deadline:
            miss.append("deadline")
        return miss


@dataclass
class Step:
    name: str            # 人类可读的步骤名
    tool: str            # 工具名
    status: str = PENDING
    cost: float = 0.0
    result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlanRun:
    """一次执行。保留全部步骤（含成功步骤），是续跑与重规划的基础。"""
    task_id: str
    topic: str
    budget: float
    deadline: str
    candidate_id: str = ""
    accepted_estimate: dict | None = None
    steps: list[Step] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.topic}|{self.budget}|{self.deadline}".encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    @property
    def total_cost(self) -> float:
        """费用合计：以入选方案的估算总额为准（含各工具费用）；
        无入选方案时退化为已成功步骤的费用之和。失败步骤不计入。"""
        if self.accepted_estimate:
            return round(float(self.accepted_estimate.get("estimated_total", 0.0)), 2)
        return round(sum(s.cost for s in self.steps if s.status == SUCCESS), 2)

    def find(self, tool: str) -> Step | None:
        return next((s for s in self.steps if s.tool == tool), None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint
        d["total_cost"] = self.total_cost
        return d
