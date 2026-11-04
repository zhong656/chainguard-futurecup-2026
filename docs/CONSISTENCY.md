# 一致性机制（CONSISTENCY）

> 本文是四人协作的**规则源**。与聊天记录冲突时，以本文与仓库文件为准。

## 一、第一原则：仓库文件是唯一事实来源

1. 所有接口、Schema、配置、验收标准、职责归属，**必须落在仓库文件里**（`contracts/`、`configs/`、`agents/`、`workflows/`、`docs/owners.yaml`）。群聊结论、口头同步、私聊约定、AI 记忆**一律不算数**。
2. 出现争议或信息缺失时：**指向具体文件路径 + 行号**。文件里没有的，先开一张 `contract-change` Issue 补文件，禁止自行拍板，也禁止按聊天记录推断。
3. **合并以 `make check` 绿灯为唯一准入标准。** 本地与 CI 跑同一条命令；禁止以「我本地能跑」「先合了再修」跳过检查。
4. `contracts/` 在 **2026-11-07 22:00** 冻结（第 10 份 `delivery_artifact` 因需 `$ref` 前 9 份，单独延至 **2026-11-08 12:00**）。冻结后任何契约改动必须走 PR，列出受影响模块与负责人，并至少获得 **1 名非 Owner 成员 approve**。
5. `docs/consistency-report.md` 由脚本自动生成，**禁止手改**；有异议改脚本或改源文件后重跑。

## 二、`make check` 是唯一标准

```
make check  ≡  python scripts/check.py
```

四个步骤，任一失败即整体失败：

| 步骤 | 内容 | 失败含义 |
|---|---|---|
| 语法 | `scripts/`、`src/` 下 Python 可解析 | 代码根本跑不起来 |
| 契约与一致性 | `$ref` 可解析、`agents/` `workflows/` 符合 Schema、目录归属齐全、`source_id` 规范、依赖锁版本 | 接口或归属已漂移 |
| 单元测试 | `pytest -q tests` | 行为回归 |
| Mock 端到端 | 生成交付包并通过 `delivery_artifact` 契约 | 交付物结构不成立 |

**Windows 没装 `make` 时，跑 `python scripts/check.py` 就是同一条命令**——这是刻意的设计，避免"本地和 CI 不是一回事"。

## 三、钩子不是标准，CI 才是

| 层 | 触发 | 内容 | 定位 |
|---|---|---|---|
| pre-commit | 每次 commit | 快检（YAML 可解析 / 契约可解析） | 提前反馈 |
| pre-push | 每次 push | 全量 `make check` | 提前反馈 |
| CI | push / PR | 全量 `make check` | **唯一准入门槛** |

**绕过 hook 不违规，CI 红灯合入才违规。** hook 可以 `--no-verify` 跳过、可以不装、可以换机器；GitHub 触发的 CI 个人跳不过，所以标准只能放在那里。

> ⚠️ 诚实说明：GitHub Free 的私有仓库**没有 required status checks**，CI 红灯在技术上拦不住合并。所以「CI 绿灯才能合并」目前是**人工纪律**，靠 PR 模板 + 复核拒绝执行，不是强制。不得在对外材料里写成"已强制"。

## 四、契约冻结与变更

**冻结时间**

| 契约 | 冻结时间 | Owner |
|---|---|---|
| 前 9 份 | 2026-11-07 22:00 | 见 `contracts_owners` |
| `delivery_artifact.schema.json` | 2026-11-08 12:00 | A |

**冻结后要改，只有一条路**：

1. 开 `contract-change` Issue，写清：为什么改、影响哪些模块、谁是应会签人；
2. PR 描述里列出受影响模块与负责人；
3. **≥1 名非 Owner 成员 approve**；
4. `make check` 绿灯；
5. 在 `docs/CHANGELOG-contracts.md` 记一行：变更原因 / 影响面 / 生效 commit。

**不允许"先改了再补 Issue"。**

## 五、依赖顺序（禁止抢跑）

```
B 的 source_ref → C 的 scorecard / compile_error → D 的 workflow / trace
                → A 的 task_state 与 Scheduler → 全链路联调
```

11/07 22:00 前必须全部冻结；**未冻结前 A 不开始写 Scheduler，D 不开始写编译器**。

## 六、争议裁决

1. 先查文件：`grep` 全仓库，找出路径与行号；
2. 文件没有 → 开 `contract-change` Issue，指定 Owner 裁决，24 小时内给结论；
3. Owner 不在 → 由 A（队长）暂定，并在 Issue 里标注"临时决定，待 Owner 追认"；
4. 结论必须回写进文件，否则视为未裁决。

## 七、闭环

```
发现不一致 → 改文件（唯一事实来源）→ 本地 make check → 提 PR
          → CI make check 绿灯 → 1 名非本人复核 → Squash 合并
```

`main` 只经 PR 合并；禁止 force push；作者不得合并自己的 PR。

## 八、生成物永不入库（2026-11-05 定）

**生成物**指每次运行都会被重写的文件，目前只有两份：

| 文件 | 谁生成 | 去处 |
| --- | --- | --- |
| `docs/consistency-report.md` | `scripts/check_contracts.py` | 本地生成 + CI artifact |
| `docs/CHANGELOG-contracts.md` | 人在合并后追加 | 只在 `main` 上追加，分支禁止修改 |

**为什么**：生成物不是"内容"，是"运行结果"。两个分支各自跑一次检查，报告必然不同；合并时就一定冲突。2026-11-04 夜里 6 个 PR 里有 5 个卡在这个文件上，就是代价。

**怎么保证**：

1. `.gitignore` 已列入，`git add -A` 不会带上；
2. CI 的 `Guard generated files` 步骤会 **fail** —— 就算 `git add -f` 强行提交，也合不进去；
3. 需要的报告从 CI artifact 下载，或本地 `python scripts/check.py` 生成。

## 九、合并纪律（2026-11-05 定）

- **一人一天一个 PR**：分支活不过 24 小时，冲突最多一行；
- **合并窗口 12:00 / 22:00**：其余时间只提不合，避免多人同时 merge 互相顶；
- **每天 22:00 打 tag** `snapshot/YYYYMMDD`：Free 套餐没有分支保护，这是唯一的回滚点；
- **一个 clone 只跑一个 agent**：多个会话同写一个工作目录会互相污染（2026-11-04 已发生一次）。

## 十、跨契约引用检查

`make check` 现在会校验：`scorecard` 样例里的 `target_node` 必须是 `workflows/*.yaml` 中真实存在的节点 id。

这类错误单看任何一份 schema 都合法，只有跨文件比对才能发现。新增同类引用时（例如 `agent` 字段指向角色名），按同样方式加检查，**不要靠人眼**。
