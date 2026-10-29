# 03 · 评估

## 测试预期 vs 实际结果

全部测试：`python -m unittest discover -s tests -v` → **21 passed**。

| 用例 | 预期 | 实际 | 证据文件 |
|---|---|---|---|
| 正常完成（重规划）| 先估 premium(13) 超预算，改选 standard(9)，保存 | ✅ | `examples/trace_normal.json` |
| 预算超限（budget 3）| `incomplete` + 缺口 3.0，不保存 | ✅ | `examples/trace_over_budget_no_solution.json` |
| 缺预算 | `needs_more_info` | ✅ | `examples/trace_missing_budget.json` |
| 缺截止时间 | `needs_more_info` | ✅ | `examples/trace_missing_deadline.json` |
| 工具失败（故障演练）| 保留检索+估算，标脚本 `failed`，`incomplete` | ✅ | `examples/trace_tool_failure.json` |
| 重复执行 | 只 1 份方案 | ✅ | `examples/trace_duplicate.json` |
| 失败续跑（加分）| 跳过已成功步骤，只重试失败步骤 | ✅ | `examples/trace_resume.json` |
| 畸形模型输出 ×3 | 不崩溃 | ✅ | `tests/test_agent.py::TestMalformedModelOutput` |
| 步数上限 | `incomplete` | ✅ | `tests/test_agent.py::TestStepLimit` |

## ReAct 决策证据（核心）

`trace_normal.json` 的重规划轨迹：

```
step1 search_materials  → 拿到 premium(12)/standard(8)/lite(5)
step2 estimate_cost(PLAN_PREMIUM)   → estimated_total=13, over_budget=true, shortfall=3.0
step3 estimate_cost(PLAN_STANDARD)  ← 模型据 step2 的超限事实改选替代，total=9 ≤ 10 ✓
step4 generate_script(PLAN_STANDARD)→ 脚本成功
step5 save_plan(PLAN_STANDARD)      → 保存
step6 finish(draft_saved)
```

`trace_tool_failure.json` 走的是**不同路径**：脚本生成失败 → 尝试替代 → 无可替代 → 停止，
且 `search`/`estimate` 两步状态仍为 `success`（结果保留）。

**同一段循环代码，因工具事实不同走出不同决策** —— 满足 ReAct 要求。

## 失败步骤不记成功（安全）

`test_failed_step_not_recorded_as_success` 断言：脚本失败时，
`generate_script` 步骤数为 failed，success 计数为 0。
`test_over_budget_never_saved` 断言：所有已保存方案的 `total_cost ≤ budget`。

## 真实模型接入验证

`python examples/verify_live_path.py` 启动本地 OpenAI 兼容 mock server，验证
`_call_live` 的 HTTP 契约（payload / Bearer 鉴权 / response_format / JSON 解析）：
→ **通过**。

## 失败与限制

1. **Mock 非真实模型决策**：默认离线 Mock 是确定性重规划器，只证明**流程、边界与重规划逻辑**，
   不证明真实 LLM 决策质量。真实能力需配 `MODEL_*` 后实测。
2. **成本模型简化**：估算 = 候选预估价 + 脚本生成费；未建模各工具逐项耗时累加。
3. **并发**：`PlanStore` 为进程内内存，多进程并发不保证幂等（考核范围外）；
   fingerprint 方案可迁移到带唯一索引的持久层。
4. **续跑为同进程 API 演示**：CLI 未暴露 `--resume`；续跑通过 `run(resume=...)` API 演示
   （见 `examples/trace_resume.json`）。
5. **单日/单方案**：一次规划产出一份方案，未做多方案批量。

## 越权/虚报检查

- 全程输出无「已发布」字样（`test_never_claims_published`）。
- 无可行方案返回 `incomplete` + 缺口，不编造成功（`test_infeasible_budget_returns_gap`）。
- 工具失败时失败步骤标 `failed`，不记成 success。
