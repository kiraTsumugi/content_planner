# 内容任务规划 Agent

面向运营人员的内容活动方案助手：在给定**主题 / 预算 / 截止时间**内，检索素材、生成脚本、估算成本、保存方案。遇到**成本超限、工具错误或部分成功**时，模型主动**调整计划、改选替代方案或停止**，并**保留已成功步骤的结果**。

模型驱动 ReAct 循环：**模型选动作 → 执行工具 → 观察结果 → 模型调整下一步或结束**。

## 快速开始

无需任何第三方依赖（纯标准库），Python ≥ 3.10。

```bash
# 1. 正常完成：预算 10，先估 premium(13) 超预算 → 改选 standard(9) → 保存
python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 -v

# 2. 预算超限：预算 3，无可行方案 → 未完成 + 缺口
python -m src.main --topic 秋季营销 --budget 3 --deadline 2026-11-05

# 3. 缺预算
python -m src.main --topic 秋季营销 --deadline 2026-11-05

# 4. 缺截止时间
python -m src.main --topic 秋季营销 --budget 10

# 5. 工具失败：主题命中故障注入，脚本生成失败 → 保留已成功步骤
python -m src.main --topic 故障演练 --budget 10 --deadline 2026-11-05 -v

# 6. 重复执行：同任务连跑两次 → 只存一份方案
python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 --json
```

**评审入口**：`python -m src.main --topic 秋季营销 --budget 10 --deadline 2026-11-05 -v`
会打印每步的 `动作 → 参数 → 决策依据`，即完整 ReAct Trace。

## 运行模式

- **离线 Mock（默认，无 key 时自动）**：确定性重规划器。`--offline` 强制。
  边界：Mock 只验证**流程、边界与重规划逻辑**，不证明真实模型决策效果。
- **真实模型**：任意 OpenAI 兼容端点，设置环境变量后自动启用：
  ```bash
  export MODEL_BASE_URL=https://api.openai.com/v1
  export MODEL_API_KEY=sk-...
  export MODEL_NAME=gpt-4o-mini
  ```

## 测试

```bash
python -m unittest discover -s tests -v        # 21 项测试
python examples/generate_traces.py             # 重新生成 examples/ 运行记录
python examples/verify_live_path.py            # 验证真实模型 HTTP 接入路径契约
```

## 动态决策模型

| 工具事实 | 模型动作 | 最终状态 |
|---|---|---|
| 首选方案超预算 | 改选可负担替代 | （继续）|
| 无可行方案 | finish | `incomplete` + 缺口 |
| 脚本生成失败 | 改试替代；无解则停 | `incomplete`（保留成功步骤）|
| 缺预算/截止 | finish | `needs_more_info` |
| 全部成功 | save_plan | `draft_saved` |
| 重复任务 | save_plan（幂等）| `draft_saved` |
| 步数超限 | abort | `incomplete` |

## 目录

```
src/agent/        核心：models / tools / llm / react_loop
src/main.py       CLI 入口
tests/            可执行测试（21 项）
examples/         运行记录（Trace + CLI 输出）+ 生成/验证脚本
data/             合成素材 / 候选方案 / 费用表
docs/             01~05 设计文档
BRIEF.md          实现前说明
```

详见 [docs/01-requirements.md](docs/01-requirements.md) 起的设计文档。
