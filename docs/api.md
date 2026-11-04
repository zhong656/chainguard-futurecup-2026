# 接口契约（人读版）

> **机器事实来源是 `contracts/*.schema.json`，本文件只是给人（和 AI）看的索引。**
> 两者冲突时以 schema 为准，并应立即修正本文件。

## 0. 冻结时间

| 契约 | 冻结 | Owner |
| --- | --- | --- |
| 前 9 份 | 2026-11-07 22:00 | 见下表 |
| `delivery_artifact` | 2026-11-08 12:00 | A |

冻结后改字段：`contract-change` PR + ≥1 名非 Owner approve + 记 `docs/CHANGELOG-contracts.md`。

## 1. 十份契约速查

| # | 文件 | Owner | 一句话 | 谁依赖 |
| --- | --- | --- | --- | --- |
| 1 | `source_ref` | B | 一条证据及其可回溯位置 | C 验证器、D 证据链、A 交付包 |
| 2 | `retrieval_result` | B | 一次检索的返回（含分数） | C、D |
| 3 | `scorecard` | C | 评分卡与待修问题 | D 的 LoopController |
| 4 | `compile_error` | C | 工作流编译错误码 | D 编译器、A 调度 |
| 5 | `agent_spec` | C | 一个角色的定义 | A 调度、D 编排 |
| 6 | `workflow` | D | 工作流图（节点/边/循环） | A 调度、C 的 target_node |
| 7 | `trace_event` | D | 一次留痕事件 | A 重放、前端 |
| 8 | `llm_response` | A | 模型调用的统一响应 | 全体 |
| 9 | `task_state` | A | 运行状态与续跑快照 | A 调度、D 续跑 |
| 10 | `delivery_artifact` | A | 可核验交付包（只 `$ref` 组装） | 评审 |

## 2. 关键字段口径（最容易写错的地方）

### `source_id`（契约 1 的 `$defs/source_id`）

- 格式：`^[a-z]+:[A-Za-z0-9_-]+$`，例 `mv:doc001`
- **命名空间白名单**：`mv`（产业/技术文档）、`web`（网页摘录）、`csv`（结构化参数表）
- **由语料入库生成，Agent 与模型一律不得自造**
- `page` / `char_range` / `row` 按语料类型给：PDF 给 `page`，网页给 `char_range`，CSV 给 `row`

### `retrieval_result.score`

- **是融合后的归一化分（0–1）**，不是向量相似度、不是 BM25 分
- 融合算法：**RRF，k=60**；不做分数加权（两路量纲不同，不可比）
- 默认 `top_k = 8`

### `scorecard`

- 维度固定 5 个：`citation` / `consistency` / `coverage` / `logic` / `format`
- 权重：**0.30 / 0.20 / 0.20 / 0.20 / 0.10**（合计 1.00）
- 阈值：**0.85**
- **一票否决**：任一维 < 0.60，或存在 `severity: blocker` 的 issue → 直接 `fail`
- `issues[].target_node` **必须是 `workflows/*.yaml` 里真实存在的节点 id**（`make check` 会校验）

### `workflow`

- 节点类型白名单 6 类：`agent` / `tool` / `parallel` / `condition` / `loop` / `checkpoint`
- `type: agent` 必须带 `agent:` 字段，取值须为 `agents/*.yaml` 的 `name`
- `depends_on` 为空 = 入口节点，**全图只允许一个入口**
- `when` 语法：受限 Python 比较表达式，只允许 `score` / `threshold` / `round` + 比较符与 `and/or/not`
- 当前主工作流 11 节点：`plan → retrieve → fanout → (analyze | outline) → write → verify → gate → revise → review → snap`
- **`loop.to = fanout`**（分析类与写作类错误的公共上游）；`target_node` 可覆盖它
- `max_rounds: 3`、`stop_if_no_gain_rounds: 2` 是常量，不可调

### `agent_spec`

- 6 个角色：`planner` / `researcher` / `analyst` / `writer` / `verifier` / `reviewer`
- `tools` 只能引用 `src/tools/registry.py` 里已注册的 **8 个工具名**
- `tier` 只有 `small` / `strong`；当前只有 `researcher` 是 small
- **`verifier` 的 temperature 必须与 `writer` 不同**（当前 0.0 vs 0.3），这是"避免同源偏差"的硬要求

### `llm_response`

- `provider` 只有 4 个：`deepseek` / `qwen` / `ollama` / `mock`
- `mock=true` 时 `usage` 必须为 `0/0`；非 mock 时 `mock` 必须 `false`
- 只表示**成功**调用；超时/限流抛有类型错误并写 Trace，不返回半个对象

### `task_state`

- 状态 5 态：`pending` / `running` / `passed` / `failed` / `aborted`
- `budget` 单位是**调用尝试次数**（重试也占一次），`calls_used` 与 `calls_max` 都必填
- 续跑读 `checkpoint`，Trace 只用于审计与重放，不当作可执行状态

### `delivery_artifact`

- **只允许 `$ref` 组装前 9 份，不许重新定义任何字段**
- `evidence_chain` 是 `source_id` 字符串数组，元素 `$ref` 契约 1 的 `$defs/source_id`
- `manifest` 是本契约自有字段：`genome_version` / `commit_sha` / `generated_at` / `files[]`

## 3. 生成物（不在本文件，也不入库）

| 文件 | 生成者 |
| --- | --- |
| `docs/consistency-report.md` | `scripts/check_contracts.py`，CI artifact 可取 |
| `docs/CHANGELOG-contracts.md` | 人工，且**只在 main 上追加** |

## 4. 改接口的正确姿势

1. 改 `contracts/*.schema.json`（连同 `contracts/examples/*.good.json` 与 `*.bad.json`）；
2. 跑 `python scripts/check.py`，**正反例都要过**；
3. 提 `contract-change` PR，列受影响模块与应会签人；
4. 合并后由合并者追加 `docs/CHANGELOG-contracts.md` 一行；
5. 同步本文件对应小节。

**禁止**：直接在代码里用新字段名而不改 schema；改了 schema 不改 examples。
