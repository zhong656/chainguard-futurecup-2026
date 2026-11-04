# 协作规范（Contributing）

4 人小团队，17 天工期。规范从简，但下面几条**不可协商**。

## 1. 分支模型

| 分支 | 用途 | 谁能推 |
| --- | --- | --- |
| `main` | 可运行、可演示的主线 | **禁止直接 push**，只接受 PR 合并 |
| `feat/<范围>` | 新功能，如 `feat/knowledge-hub` | 功能负责人 |
| `fix/<范围>` | 缺陷修复，如 `fix/scheduler-timeout` | 修复人 |
| `docs/<范围>` | 文档、材料 | 任何人 |

分支生命周期：合并后由 PR 作者删除，保持远端只有 `main` + 在途分支。

## 2. main 的合并规则（人工强制）

> 当前为 GitHub Free 个人账号，私有仓库**不支持**分支保护规则、CODEOWNERS、PR 必需评审。
> 因此以下规则**以约定 + 人工复核替代**，由队长在合并时逐条确认：

1. **`main` 只经 PR 合并**，任何人不得直接 `git push origin main`；
2. **禁止 force push 到 `main`**（含 `--force` 与 `--force-with-lease`）；
3. 每个 PR 至少 **1 人 review 通过**，且**作者不得合并自己发起的 PR**；
4. 涉及 `configs/`、`agents/`、`workflows/` 的改动，需**第二人复核**（配置即行为，改错会导致演示翻车）；
5. 合并方式统一用 **Squash and merge**，保持 `main` 线性、可回滚。

## 3. 提交信息规范

采用 Conventional Commits，**subject 用中文**，不超过 50 字：

```text
<type>(<scope>): <中文简述>

[可选正文：为什么这么改，而不是改了什么]
[可选脚注：Refs #12]
```

`type` 取值：

| type | 含义 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档 / 材料 |
| `refactor` | 重构（不改行为） |
| `test` | 测试用例 |
| `chore` | 构建、依赖、脚手架 |
| `perf` | 性能优化 |

示例：`feat(verifier): 增加引用真实性规则校验`、`fix(scheduler): 修复超时重试计数不归零`。

## 4. 提交前自查

```bash
# 1) 不提交敏感文件
git status --short          # 确认没有 .env / *.key / *.db / outputs/

# 2) 不提交调试残留
git diff --cached | Select-String -Pattern "print\(|breakpoint\(|TODO|FIXME|console.log"

# 3) YAML 可解析（改配置必做）
python -c "import yaml,sys; [yaml.safe_load(open(f,encoding='utf-8')) for f in sys.argv[1:]]" configs/*.yaml agents/*.yaml workflows/*.yaml

# 4) 测试通过
pytest -q
```

## 5. PR 要求

- 标题格式同提交规范；
- 描述按 `.github/PULL_REQUEST_TEMPLATE.md` 填写，**必须写明关联 Issue**；
- 涉及 UI / 输出的改动附截图；
- 单 PR 控制在 **400 行以内**，超了拆；
- 自己先跑一遍“复现指南”或相关用例，别把验证成本转嫁给 reviewer。

## 6. Issue 使用

| 模板 | 何时用 |
| --- | --- |
| 任务卡 | 一项开发/材料任务，必须选所属阶段与优先级（P0/P1/P2） |
| 缺陷 | 行为与预期不符，需带复现步骤与 `trace_id` |
| 风险 | 进度、技术、合规风险，需带缓解措施与负责人 |

优先级口径：**P0** 六项考察点硬证据 / 提交材料；**P1** 演示与工程化；**P2** 可选加分。

## 7. 节奏

- 每晚 **20 分钟站会**：昨天做了什么、今天做什么、卡在哪；
- 接口变动**当天**同步到群里，不等第二天；
- 每阶段末对照 `README.md` 第 2 节六项考察点逐条确认“有模块 + 有证据”，缺项立即补，不带缺口进下一阶段。
