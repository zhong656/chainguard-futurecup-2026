# 交接公告（2026-11-07 00:35）

> **本文件是给四个人的当前状态快照。** 每次合并后由合并者更新顶部三行，不要写别的内容。
> 事实来源优先级：`contracts/` > 本文件 > 群聊。冲突时以仓库文件为准。

## 〇、合并负责人（唯一）

| 角色 | 人 | 职责 |
| --- | --- | --- |
| **主合并人** | **B（zhong656）** | A/C/D 的 PR 由他复核并合并；维护本文件顶部状态；打每日 tag |
| **副合并人** | **A（ye0609）** | B 不在或不可用时顶上；**B 自己的 PR 只能由 A 合** |

规则：`main` 只经 PR 进入；作者不自合；合并窗口 **12:00 / 22:00**。
换人时必须改本表——否则没人知道该找谁合。

## 一、当前状态

| 项 | 值 |
| --- | --- |
| `main` | **`f2fc3bf`**（2026-11-07 20:55 快照） |
| 文件数 / 测试 | 159 个文件，251 个测试通过（2 skipped） |
| `make check` | **PASS**（9 项检查，**0 条 WARN**） |
| 打开中的 PR | **0** |
| 纵切 | **已跑通**：`python -m src.run` → 7 件交付物（含 rounds.json 与 2 张 SVG） |
| 接线 | **全部接通**：L2 / rounds / 图表 / Scheduler / layers 开关 / 反馈库 |
| 契约冻结 | **已完成**：tag `contracts-v1.0`（11 份） |
| 剩余 | #43 控制台阶段二与视频（D）—— 全队最后一项 |

## 二、拉代码之前先看这三条

1. **先拉再干活**：`git pull --ff-only`。本地旧分支**直接删掉重建**，不要 rebase 旧的——旧分支基于已合并的 main，rebase 只会制造重复冲突。
2. **一人一天一个 PR**：多件事合成一个 PR，分支活不过 24 小时。
3. **合并窗口 12:00 / 22:00**：其余时间只提不合，避免多人同时 merge 互相顶。

## 三、四个已经踩过的坑（别再踩）

| 坑 | 表现 | 正确做法 |
| --- | --- | --- |
| 生成物入库 | PR 里带 `docs/consistency-report.md`，必然冲突 | 该文件已 gitignore，CI 会 fail 拦你；本地跑 `check.py` 生成即可 |
| PowerShell 写文件带 BOM | `Set-Content -Encoding utf8` 写出 BOM，JSON 解析失败 | 用 `[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($false)))` |
| force push 到 main | 覆盖别人提交 | 只对 feature 分支可用 `--force-with-lease`，main 永久禁止 |
| 一个 clone 跑多个 agent | 陌生文件被 `git add -A` 卷进提交 | 一个工作目录只跑一个会话；`git add` 指名文件，别用 `-A` |

## 四、Windows 推送失败怎么办

直连与代理都会偶发失败，用这条组合命令（本机实测唯一稳定）：

```powershell
git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 -c http.sslBackend=openssl push
```

## 五、每个人的第一件事（11/05）

| 角色 | 第一件事 | 验收 |
| --- | --- | --- |
| **A** | ① `requirements.txt` 20 个依赖锁版本（`pip index versions` 现查，别凭记忆）；② 给 `check_contracts.py` 加 `tools ⊆ 注册表` 校验（代码见 #16 描述） | `make check` 的依赖 WARN 消失；故意写错工具名 → CI 红 |
| **B** | `src/knowledge_hub.py` 的 Mock 检索路径（RRF k=60），配 `tests/test_knowledge.py` | `pytest tests/test_knowledge.py` 通过 |
| **C** | 给 `agent_spec` 加 `read_only` 字段并填 6 份 YAML | `make check` 绿，且只读角色不含 `python_sandbox` |
| **D** | `src/loop_controller.py` 骨架；`loop.to` 已由 `write` 改为 **`fanout`**，按新值实现 | `pytest tests/test_loop.py` 通过 |

## 六、契约冻结前必须定完（11/07 22:00）

- [x] `llm_response` / `task_state` 语义（#15）
- [x] `source_ref` 命名空间 `mv/web/csv`、`score` 为融合分、RRF k=60（#12）
- [x] `scorecard` 5 维权重、0.85 阈值、一票否决（#18）
- [x] `workflow` 11 节点拓扑、`loop.to=fanout`（#20 + #21）
- [x] `agent_spec` 6 角色 tier/tools/timeout（#17）
- [ ] `agent_spec` 的 `read_only` 字段（C，11/06）
- [ ] `requirements.txt` 版本锁定（A，11/06）

冻结后 schema 变只读；要改只能走 `contract-change` PR + ≥1 名非 Owner approve + 记 `docs/CHANGELOG-contracts.md`。

## 七、出问题找谁

| 现象 | 先看 |
| --- | --- |
| `make check` 红了 | 终端最后 10 行 + `docs/CONSISTENCY.md` |
| 冲突不知道保哪边 | `docs/CONSISTENCY.md` 第六节「争议裁决」 |
| 契约字段含义不清 | `docs/CONTRACTS-REVIEW.md` 对应页 + `contracts/*.schema.json` 的 `description` |
| 归属/该改哪个文件 | `docs/owners.yaml` |
