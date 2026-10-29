# 实现前说明（Linus 视角）

1. **必须交付的功能**
   ① ReAct 循环（模型选动作→跑工具→观察→调整/结束，步数上限 10，超限返回 incomplete）
   ② 4 个工具：素材检索 / 脚本生成 / 成本估算 / 方案保存
   ③ 动态重规划：预算超限换替代方案、工具失败则保留成功结果并改计划、无解则返回缺口
   ④ 状态正交：步骤 `pending/success/failed/skipped`，绝不把失败记成成功
   ⑤ 幂等防重复（同 task 只存一份方案）+ 失败步骤续跑

2. **最短可运行主流程**
   `python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05`
   → 检索候选 → 选方案 → 生成脚本 → 成本估算 →（超预算则换方案）→ 存方案

3. **关键文件与阻塞**
   关键：`src/main.py`、`src/agent/{models,tools,llm,react_loop}.py`、`data/*.json`、`examples/`
   阻塞：无。零依赖（纯标准库）。

4. **可以暂时不做**
   界面、线上部署、多 Agent、真实发布、并发持久化。

---

## 设计思路

**核心数据结构**：
- `Task`：主题 + 预算 + 截止时间。任一缺失 → `needs_more_info`。
- `Candidate`：候选方案（id, name, base_cost, materials）——来自素材检索结果，**数据驱动**替代选择。
- `Step`：一步（name, tool, status, cost, result）。status 正交：`pending/success/failed/skipped`。
- `PlanRun`：一次执行的步骤序列 + 费用合计。**保留已成功步骤**是续跑/重规划的基础。
- `PlanStore`：以 `fingerprint = hash(topic|budget|deadline)` 为键 → 幂等。

**消除特殊情况**：
- 工具只返回事实（检索给的候选、估算的费用、保存的结果），**决策权归模型**。
- "超预算怎么办"不在代码里写死——模型观察 `estimate_cost` 返回的超限事实后，自己选替代。

**步骤依赖**：脚本生成依赖素材检索；估算依赖前两者；保存依赖全部。
依赖用步骤状态表达，模型据已完成状态决定下一步。

**失败处理**：
- 工具失败 → 该步骤标 `failed`，**其余成功步骤保留**（不丢结果）。
- 模型据失败事实：换替代方案 / 续跑 / 停止并返回未完成原因与缺口。

**幂等**：同 (主题,预算,截止) 重复执行 → 返回 `duplicate`，不新增方案。

**模型可离线**：无 API key 时用确定性 Mock，只验证流程与边界。
