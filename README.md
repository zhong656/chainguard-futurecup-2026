# 链衡 ChainGuard

> 面向复杂任务的**多智能体编排、调度、执行与可核验交付**平台
> 2026 第五届「未来杯」创新大赛 · 赛道一 · Agent 编排创新应用

<!-- 控制台截图 / DAG 流转 GIF：待接入真实 SSE 后补入（见 Issue #43） -->

## 1. 项目定位

ChainGuard 不是"又一个聊天机器人"，而是一套 **Agent Harness（智能体运行框架）**：
它不绑定某个具体任务，而是提供一条完整的工程链路——**定义知识 → 定义团队 → 编排流程 → 调度执行 → 验证结果 → 反馈优化**。

对标 LobeHub / DeepSeek Harness 的框架定位，但把 **可核验性（Verifiable Delivery）** 作为核心设计目标：

- **结论必须带证据**：Agent 输出强制绑定知识库 `source_id`，无法回溯的引用由验证器直接判不合格；
- **交付物自带验证报告**：方案书 + 证据链 + 评分卡 + 全链路 Trace，一次运行可完整重放；
- **失败可归因、可优化**：失败样本进入反馈库，离线驱动提示词 / 模型路由 / 阈值优化，用 A/B 数据说话。

**示范场景**：产业技术方案自动生成与可信交付。
例：给定一句「某年产值 3 亿元的中小型精密零件制造企业，拟在 12 个月内用机器视觉升级产线质检，请输出可落地方案」，由 6 类 Agent 协作完成检索、入库、规划、测算、撰写、核验与自动修订，最终交付带引用证据链、图表与量化评分报告的技术方案。

## 2. 赛题六项考察点对照

| # | 赛题考察点 | 本项目实现 | 可提交证据 |
| --- | --- | --- | --- |
| 1 | 知识库定义与集成 | `KnowledgeHub`：声明式知识源注册、切片与向量化、元数据与溯源 ID、混合检索（向量 + BM25 + 重排）、引用强制回填 | `knowledge/*.yaml`、检索命中率报告、引用证据链 |
| 2 | Agent 团队定义 | `AgentRegistry`：6 类角色以 YAML 声明（职责 / 工具白名单 / I/O Schema / 模型档位 / 超时重试），支持热加载与自定义角色 | `agents/*.yaml`、角色清单、热加载演示 |
| 3 | 工作流编排 | DAG 引擎：节点 / 条件边 / 并行分支 / 子图 / 循环边，支持模板导入导出与前端可视化 | `workflows/industry_solution.yaml`、DAG 图、执行轨迹 |
| 4 | 动态调度 | `Scheduler`：按复杂度分级路由模型、并发信号量、超时重试与熔断、Token 与成本预算、失败降级与断点续跑 | 调度策略说明、压测数据、故障注入录屏 |
| 5 | 自我循环 Self-Loop | `LoopController`：评分卡未达阈值时生成**定位到段落**的修订指令并回退至指定节点，最多 3 轮，含收敛检测 | 多轮对比报告、分数收敛曲线、轮次日志 |
| 6 | 结果验证与反馈优化 | 三层验证：规则验证器（引用 / 数值 / 章节 / Schema）+ 独立 Verifier Agent 交叉评审 + 双路检索比对；失败样本入反馈库驱动优化 | 评分报告、失败案例库、优化前后 A/B 对比 |
| 附加 | 可运行平台系统 | FastAPI + Web 控制台 + Docker Compose 一键启动 + Trace 可重放 | 可运行仓库、启动录屏、本文档 |
| 附加 | 完整技术方案与演示成果 | 项目书 + 架构文档 + 5–8 分钟演示视频 + 路演 PPT | `docs/提交材料清单.md` |

## 3. 5 分钟复现指南

> ✅ **当前状态：可运行**。`python scripts/check.py` 全绿（251 项检查），
> 命令行纵切与 HTTP 服务均可直接跑通，**Mock 模式不需要任何 API Key**。
> 逐项能力与证据的对应关系见 `docs/HANDOFF.md` 顶部状态表。

### 方式一：命令行纵切（最快，30 秒）

```bash
python -m src.run --request "用机器视觉升级精密零件产线质检"
```

会依次执行：混合检索（17 份语料）→ Mock 草稿 → **L1 规则 + L2 独立评审**评分 →
若未达阈值则**定位到段落**定向回退重跑 `write → verify` → 导出交付包。

产物落在 `outputs/_vertical/`，共 8 件：

```
solution.md            正文
evidence_chain.json    引用到的 source_id 清单
evidence_refs.json     每条引用的 文件 / 页码 / 字符区间 / 原文 / 哈希
                       （页码仅 PDF/DOCX 等分页格式才有值；当前 Markdown 语料为 null，
                        靠 file_path + char_range + hash 回原文核对）
scorecard.json         评分卡（含 fail→pass 的终轮结论）
rounds.json            每轮评分，首轮 fail、终轮 pass 的物证
charts/*.svg           评分卡五维 + Self-Loop 收敛曲线
trace.jsonl            全链路事件（start/end/revise/fail/retry/degrade）
delivery_artifact.json 交付清单与上述文件的 sha256
```

### 方式二：HTTP 服务

```bash
docker compose up -d          # 或本地 uvicorn src.main:app --port 8000
# POST /runs → GET /runs/{id}/events（SSE）→ GET /runs/{id}/artifacts
```

### 方式三：一键跑全部检查

```bash
python scripts/check.py       # 契约 / 配置 / 单测 / 端到端 / 纵切，共 5 步
python scripts/verify_http.py # 起真实 uvicorn，打三个接口
```

> 复现命令与 CI 完全一致：CI 跑的就是 `make check`，没有第二套脚本。

```bash
# 1) 克隆
git clone https://github.com/zhong656/chainguard-futurecup-2026.git
cd chainguard-futurecup-2026

# 2) 一键启动（Mock 模式，无需任何 API Key，可离线复现）
docker compose up -d

# 3) 打开控制台
#    浏览器访问 http://localhost:8000
#    输入需求 → 观察 DAG 节点流转 → 查看评分卡与证据链

# 4) 校验交付物可重放
ls outputs/<trace_id>/    # solution.md / evidence_chain.json / scorecard.json / trace.jsonl
```

设计约束（复现性是评审硬指标）：

- **Mock 模式零凭据**：`LLM_PROVIDER=mock` 时不读取任何 Key，全流程可跑通；
- **离线语料**：`knowledge/corpus/` 内置示例语料，不依赖联网检索；
- **一键重放**：同一 `trace_id` 重放应得到一致的节点序列与评分。

## 4. 目录结构

```text
chainguard-futurecup-2026/
├── README.md
├── SECURITY.md                  # 凭据与数据安全约定
├── CONTRIBUTING.md              # 分支 / 提交 / PR / 复核规则
├── requirements.txt             # 已锁版本的依赖清单
├── configs/                     # 平台级配置
│   ├── llm.yaml                 # 模型档位与路由策略
│   ├── scheduler.yaml           # 并发 / 预算 / 超时 / 重试
│   └── verifier.yaml            # 评分卡权重与阈值
├── knowledge/                   # 知识源声明与离线语料
│   ├── sources.yaml             # 17 份知识源声明（含许可依据）
│   └── corpus/                  # 离线语料包
├── agents/                      # 6 类 Agent 角色定义
│   ├── planner.yaml
│   ├── researcher.yaml
│   ├── analyst.yaml
│   ├── writer.yaml
│   ├── verifier.yaml
│   └── reviewer.yaml
├── workflows/                   # 工作流模板
│   └── industry_solution.yaml   # 主示范工作流
├── src/                         # 后端实现（15 个模块，均已落地）
├── tests/                       # 单测 / 黄金用例 / 故障注入
├── docs/                        # 提交材料清单、逐日计划、架构文档
└── .github/                     # PR 与 Issue 模板
```

## 5. 团队分工

| 角色 | 人数 | 主要负责 | 对应考察点 |
| --- | --- | --- | --- |
| 队长 / 架构与调度 | 1 | 架构设计、LLM 适配层、Scheduler、进度与对外沟通、报名提交 | 动态调度、整体集成 |
| 知识库与工具 | 1 | KnowledgeHub、语料、检索、Python 沙箱、图表工具 | 知识库定义与集成 |
| Agent 与验证 | 1 | AgentRegistry、角色 YAML、Verifier、规则验证器、评分卡 | Agent 团队定义、结果验证 |
| 编排与前端 | 1 | DAG 编译器、LoopController、Web 控制台、Trace 重放 | 工作流编排、Self-Loop、演示 |
| 全员 | — | 文档撰写、视频录制、测试、答辩 | 完整技术方案与演示成果 |

合计 4 人（1 队长 + 3 成员）。指导老师仅做方案与答辩辅导，不参与代码与仓库管理。

## 6. 时间节点

| 阶段 | 时间 | 目标 | 验收标准 |
| --- | --- | --- | --- |
| 0 立项与报名 | 11/3 – 11/4 | 报名、建仓库骨架、六项考察点上看板 | 仓库可访问、全员能复述 6 项能力 |
| 1 方案设计 | 11/5 – 11/7 | 场景规格、架构图、数据模型、YAML、语料 | YAML 可解析，`pip install` 无报错 |
| 2 核心框架 | 11/8 – 11/12 | LLM 适配层、知识库、注册表、DAG、调度 | 与 Mock 联调通过 |
| 3 验证闭环 | 11/13 – 11/16 | 规则验证器、评分卡、Self-Loop、端到端 | 5/5 黄金用例跑通，均分 ≥ 0.85 |
| 4 前端与工程化 | 11/17 – 11/18 | 控制台、交付预览、Compose、pytest | 干净环境一键启动 |
| 5 材料提交 | 11/19 – 11/20 | 简介、文档、视频、PPT、提交包 | **11/20 上午完成提交** |
| 6 决赛冲刺 | 11/27 – 12/20 | 完善与答辩 | 12/14–12/20 线上答辩 |

> 红线：不压到 11/20 深夜提交；11/19 完成全部材料，11/20 只做上传与复核。

> **先读这里**：[交接公告](docs/HANDOFF.md) · [接口口径](docs/api.md) · [已定决定](docs/decisions.md) · [给 AI 的提示词](docs/AGENT-PROMPT.md) · [交付计划](docs/PLAN-DELIVERY.md) —— 当前状态、拉取方式、四个已踩过的坑

## 7. 协作与安全

- 协作规范见 [CONTRIBUTING.md](CONTRIBUTING.md)：`main` 仅经 PR 合并、禁止 force push、PR 需人工复核。
- 安全约定见 [SECURITY.md](SECURITY.md)：**凭据只从环境变量读取**，任何 Key 不得入库。
- 仓库为 **private**，参赛前不开源、不发布到模板库、不开启 Pages。

## 8. 参赛声明

本项目为 2026 未来杯参赛作品，赛期内暂不开源（仓库未附 LICENSE）。
文档与演示材料中不出现校名、学院、导师姓名等可能影响评审公平的信息。
