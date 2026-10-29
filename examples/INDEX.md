# 运行记录索引

| 用例 | 场景 | 最终状态 | 方案数 | Trace | CLI 输出 |
|---|---|---|---|---|---|
| normal | 正常完成（含超预算重规划） | `draft_saved` | 1 | [trace_normal.json](trace_normal.json) | [run_normal.txt](run_normal.txt) |
| over_budget_no_solution | 预算超限：无可行方案，返回缺口 | `incomplete` | 0 | [trace_over_budget_no_solution.json](trace_over_budget_no_solution.json) | [run_over_budget_no_solution.txt](run_over_budget_no_solution.txt) |
| missing_budget | 缺预算 | `needs_more_info` | 0 | [trace_missing_budget.json](trace_missing_budget.json) | [run_missing_budget.txt](run_missing_budget.txt) |
| missing_deadline | 缺截止时间 | `needs_more_info` | 0 | [trace_missing_deadline.json](trace_missing_deadline.json) | [run_missing_deadline.txt](run_missing_deadline.txt) |
| tool_failure | 工具失败：保留已成功步骤 | `incomplete` | 0 | [trace_tool_failure.json](trace_tool_failure.json) | [run_tool_failure.txt](run_tool_failure.txt) |
| duplicate | 重复执行：只存一份方案 | `draft_saved` | 1 | [trace_duplicate.json](trace_duplicate.json) | [run_duplicate.txt](run_duplicate.txt) |
| resume | 失败续跑（加分项） | `incomplete` | 0 | [trace_resume.json](trace_resume.json) | — |
