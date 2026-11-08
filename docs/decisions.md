# 决策记录（decisions）

> 一条决定一行。**只记"已定"的，不记"讨论中"的。**
> 每条必须能被代码或契约文件验证；口头约定不写在这里。
> 格式：`日期   决定   谁定   影响   验证方式`

## 12. 与外部协作 / 流程

  日期   决定   谁定   影响   验证  
  ---   ---   ---   ---   ---  
  11-05   **生成物永不入库**：`docs/consistency-report.md` 移出版本库，CI 生成 artifact   B（全权处理）   所有 PR   `.gitignore` + CI `Guard generated files` 步骤  
  11-05   **`docs/CHANGELOG-contracts.md` 只在 main 上追加**，分支禁止修改   B   所有契约 PR   PR 模板 + 复核  
  11-05   **一人一天一个 PR**，分支活不过 24 小时（**11-07 20:12 取消限流**，保留「分支活不过 24 小时」）   B   全员   看板 / 站会  
  11-05   **合并窗口 12:00 / 22:00**，其余时间只提不合   B   全员   看板  
  11-05   **每天 22:00 打 tag `snapshot/YYYYMMDD`**   B   回滚能力   `git tag -l`  
  11-05   **一个 clone 只跑一个 agent**   B   全员   事故复盘（11-04 陌生文件）  
  11-05   `Free` 套餐下 CI **不能强制阻断合并**，只能红灯 + 人工拒绝   事实   全员   分支保护接口 403 实测  

## 11. 契约与接口

  日期   决定   谁定   影响   验证  
  ---   ---   ---   ---   ---  
  11-04   契约冻结 **2026-11-07 22:00**；第 10 份 `delivery_artifact` 延至 **11-08 12:00**   A/B/C/D   全员   `contracts/*.schema.json` 的 description  
  11-04   `delivery_artifact` **只允许 `$ref` 组装**，不许重定义 scorecard/source_id/trace_event 字段   A   C/D   `check_contracts` 的 `$ref` 解析  
  11-04   `source_id` 命名空间限 `mv` / `web` / `csv` 三个   B   C/D   `source_ref.schema.json` + `make check`  
  11-04   `retrieval_result.score` = **融合后的归一化分**，非单路分   B   C/D   `retrieval_result.schema.json`  
  11-04   融合算法 **RRF k=60**，不做分数加权   B   B 的实现   契约 description  
  11-05   `scorecard` 5 维权重 **0.30/0.20/0.20/0.20/0.10**，阈值 **0.85**   C   D 的 Loop   `configs/verifier.yaml`  
  11-05   新增**一票否决**：任一维 <0.60 或存在 blocker issue → fail   C   D 的 Loop   `contracts/examples/scorecard.good.json`  
  11-05   主工作流固定 **11 节点**，`analyze` / `write` 是回退目标   D   A/C   `workflows/industry_solution.yaml`  
  11-05   **`loop.to = fanout`**（公共上游），`target_node` 可覆盖   B（裁决）   D   `workflow.schema.json` + `tests/test_dag.py`  
  11-05   `llm_response` 的 `mock=true` → `usage` 必须 0/0   A   全体   `if/then` 校验  
  11-05   `task_state.budget` 按**调用尝试次数**计（重试占一次）   A   调度   契约 `required`  
  11-05   `agent_spec` 冻结 8 个工具名，`tools` 只能引用注册表   C/B   全体   `src/tools/registry.py` + `#16`  

## 10. 工具与检查

  日期   决定   谁定   影响   验证  
  ---   ---   ---   ---   ---  
  11-04   **`make check` 是唯一准入门槛**，等价 `python scripts/check.py`   A   全员   `.github/workflows/ci.yml`  
  11-04   契约必须有 **正例 + 反例**，反例不被拒即判 schema 过松   B   全员   `check_contracts` 第 8 项  
  11-05   新增**跨契约引用检查**：`target_node` 必须在工作流节点集内   B   C/D   `check_contracts` 第 9 项  
  11-05   Windows 推送统一用 `-c http.proxy=... -c http.sslBackend=openssl`   B   全员   实测（直连与纯代理均失败）  
  11-05   写文件禁用 PowerShell `Set-Content -Encoding utf8`（写 BOM 会破坏 JSON）   B   全员   实际踩坑  

## 待定（不要在代码里假设）

  事项   谁定   期限  
  ---   ---   ---  
  `agent_spec` 的 `read_only` 字段   C   11-06  
  `requirements.txt` 版本锁定   A   11-06  
  评委如何看待 private 仓库代码（打包 zip / 邀请 / 临时公开）   A   11-10  

## 2026-11-07 · 契约冻结 v1.0（B）

**冻结动作**：11 份 JSON Schema 全部定稿，打 tag contracts-v1.0（提交 194f63d）。

| 项 | 结果 |
| --- | --- |
| 契约数 | 11（draft 于 #28 加入） |
| 正反例 | 11 组全部符合预期（正例通过、反例被拒） |
| 跨契约引用 | target_node 全部可解析（11 个节点） |
| 命名空间白名单 | mv / web / csv / kb（kb 于本次冻结前新增，见 CHANGELOG-contracts） |

**冻结后规则**：任何字段增删、必填项变化、pattern 修改，一律走 contract-change
（提案 → 影响面说明 → 全量 make check → 记录到 CHANGELOG-contracts.md），并同步更新正反例。
**描述文本的澄清**（不改变校验行为）可由契约 Owner 直接提交，需在 CHANGELOG 记一行。

## 2026-11-07 · 反馈数据的表述纪律（B 记录，C 提出）

样本量小的时候，"改善"这个说法很容易变成夸大。为此定一条硬规矩，写材料与答辩都适用：

1. **样本数 < 30 时只报个案与方向，不写"优化后普遍提升"**；
2. 引用 `feedback.compare()` 的数字，必须同时说明**样本量与批次**（哪个 run、第几轮）；
3. `resolved` 只表示"同一次运行后续轮次跑通"，**不得表述为线上修复率**；
4. 允许并且鼓励写"这条我们只验了个案"——**比编一个宏观数字安全**。
