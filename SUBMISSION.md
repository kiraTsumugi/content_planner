# 交付说明 · 内容任务规划 Agent

## 提交信息

| 项 | 内容 |
|---|---|
| 题号 | 内容任务规划 Agent（项目题四选一） |
| GitHub URL | ⬅️ 待填（如 https://github.com/<用户名>/content-planner）|
| 分支 | `main` |
| 交付 tag | `submission-v1` |
| 运行方式 | CLI |
| 依赖 | 零第三方依赖，Python ≥ 3.10 |

> **关于 commit SHA**：本文件被写入最终提交，无法记录自身 SHA（自引用）。
> 请以 git tag `submission-v1` 指向的提交为交付版本：
> ```bash
> git rev-list -n1 submission-v1
> ```

## 一句话概述

面向运营人员的内容活动方案助手：在给定主题/预算/截止时间内，模型驱动 ReAct 循环完成
素材检索、脚本生成、成本估算、方案保存；遇成本超限或工具失败时**调整计划、改选替代或停止**，
并**保留已成功步骤**。

## 评审入口（先看这里）

```bash
cd content-planner

# 核心：超预算重规划全过程（每步 动作→参数→决策依据）
python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 -v

# 全量测试
python -m unittest discover -s tests -v
```

预期：先估 premium(13) 超预算 → 改选 standard(9) → 生成脚本 → 保存。

## 需求映射（验收点 → 证据）

| 验收点 | 命令 | 状态 | 证据 |
|---|---|---|---|
| 正常完成 | `--topic 秋季营销 --budget 10 --deadline 2026-11-05` | `draft_saved` | `examples/trace_normal.json` |
| 预算超限 | `--topic 秋季营销 --budget 3 --deadline 2026-11-05` | `incomplete`+缺口 | `examples/trace_over_budget_no_solution.json` |
| 缺预算 | `--topic 秋季营销 --deadline 2026-11-05` | `needs_more_info` | `examples/trace_missing_budget.json` |
| 缺截止时间 | `--topic 秋季营销 --budget 10` | `needs_more_info` | `examples/trace_missing_deadline.json` |
| 工具失败 | `--topic 故障演练 --budget 10 --deadline 2026-11-05` | `incomplete`（保留成功步骤）| `examples/trace_tool_failure.json` |
| 重复执行 | 同任务连跑两次 | 只 1 份方案 | `examples/trace_duplicate.json` |
| 失败续跑（加分）| `run(resume=...)` | 跳过已完成步骤 | `examples/trace_resume.json` |
| 畸形输出/步数上限 | — | 不崩溃 / `incomplete` | `tests/test_agent.py` |

## 核心思路（文件里放不下的取舍）

1. **工具返回事实，决策权归模型**：代码里没有 `if 超预算 then 换方案`。`estimate_cost` 返回
   `over_budget`/`shortfall` 事实，模型据此改选替代。**决策由"观察到的结果"驱动**。
2. **步骤状态正交**：`pending/success/failed/skipped`。失败步骤标 `failed`，已成功步骤保留。
   失败处理、续跑、费用计算三件事都由此自然成立。
3. **幂等**：`PlanRun.fingerprint = hash(topic|budget|deadline)` 为存储键，重复执行只存一份。
4. **失败续跑（加分）**：`run(resume=<上次 PlanRun>)` 注入已成功步骤的动作+观察，模型跳过它们。
5. **无解要诚实**：预算不足返回 `incomplete` + 缺口，绝不编造成功。
6. **不用框架**：LangGraph 等只提供循环骨架，与原生循环相比无增益，故不引入。

## 已知限制

1. 默认离线 Mock 是确定性重规划器，**不代表真实 LLM 决策质量**；真实能力需配 `MODEL_*` 实测。
2. 成本估算简化（候选预估价 + 脚本费），未逐项累加、未建模截止时间耗时约束。
3. 并发不安全（进程内内存）；fingerprint 方案可迁移到持久层。
4. 续跑通过 API 演示，CLI 未暴露 `--resume`。

## 目录导览

```
README.md              环境/运行/评审入口
SUBMISSION.md          本文件
BRIEF.md               实现前说明
src/agent/             models / tools / llm / react_loop
tests/test_agent.py    21 项测试
examples/              Trace + CLI 输出 + INDEX + 生成/验证脚本
data/                  合成素材/候选/费用表
docs/01~05             需求/方案/评估/AI使用/复盘
```
