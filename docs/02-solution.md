# 02 · 方案

## 调用流程

```
用户意图(topic, budget, deadline)
        │
        ▼
┌──────────────────────────────────────────────┐
│ ReAct 循环 (src/agent/react_loop.py)          │
│  模型 decide() ──► 动作                        │
│      │                                         │
│      ├─ search_materials ──► 候选方案事实       │
│      ├─ estimate_cost    ──► 费用/超限事实      │
│      ├─ generate_script  ──► 脚本/失败事实      │
│      ├─ save_plan        ──► 保存结果(幂等)     │
│      └─ finish           ──► 结束               │
│      ▲                     │                   │
│      └── 观察结果喂回 ◄─────┘                    │
│  步数上限 10 → 超限 status=incomplete           │
│  已成功步骤保留在 PlanRun.steps（重规划基础）    │
└──────────────────────────────────────────────┘
```

## 动态决策（ReAct 的核心）

**工具只返回事实，决策权 100% 归模型。** 代码里没有 `if 超预算 then 换方案`——
分支在模型里，由工具事实驱动。

两条典型路径因工具结果不同而分叉：

- **路径 A（预算充足）**：`search → estimate(首选, 未超) → generate_script → save_plan → finish`
- **路径 B（超预算）**：`search → estimate(首选 13, 超限) → estimate(替代 9, 可行) → generate_script → save_plan → finish`

路径 B 中，模型**先估首选方案**，观察到超预算事实后再改选替代 —— 这正是参考实例要求的
"观察到超预算后改选替代方案"。见 `examples/trace_normal.json`。

## 关键设计取舍

### 1. 步骤状态正交：失败绝不记成成功
`Step.status ∈ {pending, success, failed, skipped}`。工具失败时该步骤标 `failed`，
**已成功步骤原样保留**。费用合计只按入选方案估算，不把失败步骤算成产出。

### 2. 幂等键放进数据结构
`PlanRun.fingerprint = hash(topic|budget|deadline)`，`PlanStore` 以它为键 →
重复执行天然只存一份方案，无需额外去重。

### 3. 重规划 = 模型消费超限事实，而非代码分支
`estimate_cost` 返回 `over_budget` 与 `shortfall` 两个事实。模型据此决定"换更便宜的候选"，
而不是代码里写死降级逻辑。

### 4. 失败续跑（加分项）
`run(resume=<上次的 PlanRun>)` 把上次**已成功步骤**的动作+观察注入对话历史，
模型据此跳过已完成步骤（trace 里不再出现 `search_materials`/`estimate_cost`），只重试失败步骤。

### 5. 无解即诚实返回缺口
预算过低时（如 3），模型不编造方案，返回 `incomplete` 与"预算缺口 N"。

### 6. 零依赖
纯标准库 `urllib` 直连 OpenAI 兼容端点。框架在本例只提供循环骨架，无增益，故不引入。

### 7. Mock 与真实模型同构
`ModelClient.decide(system, messages) -> action dict` 是唯一接口。切换后端不改循环代码。

## 技术栈

- Python 3.12，标准库 only
- 模型：OpenAI 兼容 `/chat/completions`（`response_format=json_object`）
