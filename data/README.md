# data/ 说明

全部为**合成数据**，不含任何真实隐私或密钥。

| 文件 | 内容 |
|---|---|
| `materials.json` | 素材库（类别/单位费用/耗时）。素材检索据此返回候选。 |
| `candidates.json` | 候选方案模板：`PLAN_PREMIUM`(12)、`PLAN_STANDARD`(8)、`PLAN_LITE`(5)。模型据预算挑选。 |
| `fees.json` | 工具费用与耗时表；含 `_fail_injection`（故障注入）。 |

## 候选方案与验收场景映射

| 方案 | 预估价 | 用途 |
|---|---|---|
| PLAN_PREMIUM | 12 | 首选；预算 10 时超预算 → 触发重规划 |
| PLAN_STANDARD | 8 | 替代；预算 10 时可行（含脚本费共 9）|
| PLAN_LITE | 5 | 更低成本替代 |

估算规则：`estimated_total = 候选预估价 + 脚本生成费(1)`。

## 故障注入

`fees.json._fail_injection.topics` 列出的主题（默认 `故障演练`）命中时，
`generate_script` 返回失败，用于验证"工具失败保留已成功步骤"（见 `examples/trace_tool_failure.json`）。

## 验收场景 ↔ 输入映射

| 场景 | 输入 |
|---|---|
| 正常完成（重规划）| 主题=秋季营销, 预算=10, 截止=2026-11-05 |
| 预算超限（无解）| 主题=秋季营销, 预算=3 |
| 缺预算 | 预算=None |
| 缺截止 | 截止=None |
| 工具失败 | 主题=故障演练 |
| 重复执行 | 正常输入连跑两次 |
