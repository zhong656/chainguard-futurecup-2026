# 契约语义评审（10 份，逐份填空即定稿）

> **这份文档不是给人读的说明书，是给四个人填的表。**
> 填完 → 改对应 `contracts/examples/*.good.json` 的值 → 跑 `make check` → 提 PR。
> 判据只有一条：**有人想违反它时，能否说出是哪一行会报错。** 说不清，就是还没定。

## 怎么用（每人 15 分钟，不用开会）

1. 找到自己负责的那一节，看该契约的 `good/bad` 样例；
2. 样例里的数值/枚举**不对就改**——改 JSON 就是做决定，比写文字决议可靠；
3. 本地跑 `make check`，绿了提交 PR，标题写 `contract(<契约名>): 定稿语义`；
4. 有分歧：对着 PR 里那个 JSON 的 diff 谈，10 分钟收敛；仍谈不拢由 **A 队长拍板**，记进 `docs/CHANGELOG-contracts.md`。

## 判定与权限

| 事 | 谁定 |
| --- | --- |
| 字段该叫什么、枚举有哪些值、阈值多少 | **该契约 Owner**（下表） |
| 两人字段对不上、结构互相矛盾 | Owner 协商 → 谈不拢交 A |
| 结构是否合法、`$ref` 是否断、正反例是否成立 | **机器**（`make check`），不由人拍 |
| 改完要不要通知 | `docs/owners.yaml` + PR 模板（会签人） |

---

## A 页（ye0609）｜`llm_response` · `task_state` · `delivery_artifact`

### A-1 `llm_response` —— 模型调用响应

| 问题 | 现状（我的默认） | 你的决定 |
| --- | --- | --- |
| `provider` 是否就这四档 | `deepseek/qwen/ollama/mock` | 是；填写实际产生本次响应的 provider，四个值由 schema 枚举约束。 |
| `usage` 只记 token 够不够，要不要记成本 | 只 `tokens_in/out` | 只记供应商报告的输入/输出 token；供应商缺失用量时适配层报错，不猜测。Mock 不消耗模型 token，固定记 `0/0`。美元成本依赖价格版本，由调度/报告层计算。 |
| `degraded` 由谁置位 | 没有约定 | 调度器在一次失败后成功切到备用 provider 时置 `true`；用户一开始选择 `mock` 时为 `false`。`mock` 只根据实际 provider 判定，与 `degraded` 独立。 |
| 超时/限流时是否仍返回一个完整对象 | 未定 | 否。`LLMResponse` 只代表成功调用；超时/限流抛有类型的错误，并写 `fail/retry/degrade` Trace。重试或降级成功后才返回响应。 |

### A-2 `task_state` —— 运行状态与续跑快照

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 状态机是否就 5 态 | `pending/running/passed/failed/aborted` | 是。`failed` 表示执行结束且未通过验证或重试耗尽；`aborted` 表示取消、预算/轮次护栏主动终止。节点自身仍用 `pending/running/done/failed/skipped`。 |
| `budget` 单位是调用次数还是 token | `calls_used/calls_max`（次数） | 按 LLM 调用尝试次数计，重试也占一次；每次尝试前检查 `calls_used < calls_max`。二者都必填；Token 用量留在各次 `LLMResponse.usage`。 |
| 断点续跑靠 `checkpoint` 还是重放 `trace` | 两者都有，语义未定 | 从持久化 checkpoint 恢复 `TaskState`，并校验 `contract_version`；Trace 只用于审计和播放，不当作可执行状态。`checkpoint.enabled=true` 时必须有路径和创建时间。 |

### A-3 `delivery_artifact` —— 可核验交付包（**11/08 12:00 冻结**）

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| `manifest.commit_sha` 从哪来 | 运行时 `git rev-parse` 或 CI 注入，未定 | |
| `mock` 标记怎么判定 | 手填 / 由 `LLM_PROVIDER` 推断 | |
| `files[]` 要不要含 `trace.jsonl` 本身 | 未定 | |

---

## B 页（zhong656）｜`source_ref` · `retrieval_result`

### B-1 `source_ref` —— 证据引用单元（**下游全依赖它**）

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 命名空间有哪几个 | 样例用 `mv:`，其余未定 | |
| `page` 与 `char_range` 是都要还是二选一 | 都可选 | |
| `hash` 取多少位 | `16–64` 位 | |
| `text` 存全文还是片段（长度上限） | 未定上限 | |

### B-2 `retrieval_result` —— 检索结果

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| `score` 是哪一路的分数 | 未说明（向量/BM25/重排后） | |
| 默认 `top_k` | 样例 8 | |
| 两路怎么融合 | `mode` 有 `hybrid`，但融合算法未定 | |

---

## C 页（uuiu4399）｜`agent_spec` · `scorecard` · `compile_error`

### C-1 `agent_spec` —— 角色定义

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 6 个角色各自 `tier` | 样例 writer=strong，其余未定 | |
| 每个角色的 `tools` 白名单 | 样例 2 个，其余未定 | |
| `timeout_s` 统一还是分级 | 样例 120s | |

### C-2 `scorecard` —— 评分卡（**Self-Loop 靠它回退**）

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 维度到底几个、叫什么 | 样例给了 5 个：citation/consistency/coverage/logic/format | |
| 权重分配 | 未定（`metrics` 只装分数，权重在 `configs/verifier.yaml`） | |
| `pass_threshold` | 样例 0.85 | |
| `issue.target_node` 如何保证存在 | 未校验（可加进 `check_contracts`） | |

### C-3 `compile_error` —— 编译错误码

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 8 个码够不够 | 见 schema 枚举 | |
| 工具超时/沙箱拒绝/循环超限归哪个码 | 未定，可能缺码 | |

---

## D 页（2055034503-ai）｜`workflow` · `trace_event`

### D-1 `workflow` —— 工作流图（**A 的调度器靠它**）

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 6 类节点白名单是否够 | agent/tool/parallel/condition/loop/checkpoint | |
| `depends_on` 为空 = 并行还是非法 | 未定（建议：与 `parallel` 节点同时存在时才算并行） | |
| `loop.max_rounds` 固定 3 | 是 | |
| `when` 表达式语法 | 样例写了 `score < threshold`，语法未定 | |

### D-2 `trace_event` —— 留痕事件

| 问题 | 现状 | 你的决定 |
| --- | --- | --- |
| 8 种 `kind` 够不够 | start/end/fail/retry/degrade/revise/abort/checkpoint | |
| `input_digest` 存哈希还是摘要文本 | 样例 `sha256:...` | |
| 事件是否需要 `parent_event_id` 表示嵌套 | 无此字段 | |

---

## 已知缺口（本轮不解决，留待确认）

1. **`format: date-time` 未被机器强制**：jsonschema 默认不校验 `format`，所以时间格式写错不会红。要不要加 `format_checker`（需装 `rfc3339-validator`），或改成 `pattern` 正则——**这一条需要决定**。
2. **`references` 只在样例层验证**，尚未做"字段跨契约一致性"（如 Verifier 读的 scorecard 字段是否等于 Agent 输出字段）。等 11/07 冻结后再加。

## 定稿记录

每定完一份，在 `docs/CHANGELOG-contracts.md` 追加一行：

```
2026-11-05  scorecard  metrics 定为 5 维（citation/consistency/coverage/logic/format），阈值 0.85  — C 定，ABD 确认  — 影响：verifier.yaml、loop_controller
```
