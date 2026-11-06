# 契约定稿记录

2026-11-04  llm_response  provider 限四种；响应仅表示成功调用；usage 只记供应商报告的 token，Mock 为 0/0；degraded 由调度器在成功降级后置位；mock 与实际 provider 一致。— A 定，待团队复核 — 影响：LLM 适配层、调度器、Trace。

2026-11-04  task_state  运行状态为五态；预算按包含重试的调用尝试次数计；续跑读取 checkpoint，Trace 只用于审计。— A 定，待团队复核 — 影响：调度器、checkpoint、交付重放。

2026-11-05  workflow  空依赖为唯一入口；when 使用受限 Python 比较语法；普通依赖无环、回边显式声明；修订最多 3 轮、连续两轮无提升停止；固定 analyze/write 供评分卡回退。— D 定，待 A/C 复核 — 影响：工作流编译与 LoopController（D）、调度与 checkpoint（A）、Agent 名称与 scorecard.target_node（C）。

2026-11-05  agent_spec   6 个角色 tier/tools/timeout/temperature 全部落定：5 strong + 1 small（researcher），工具白名单冻结为 8 个名字  — C 定，待 A/B/D 确认  — 影响：agents/*.yaml、configs/llm.yaml routing、AgentRegistry 热加载

2026-11-05  scorecard    5 维权重 0.30/0.20/0.20/0.20/0.10，pass_threshold 0.85，新增一票否决（metric<0.60 或 blocker issue）  — C 定，待 A/B/D 确认  — 影响：configs/verifier.yaml、LoopController、评分卡前端

## 2026-11-07 · 新增命名空间 kb（B）

- **改动**：source_ref 的命名空间白名单追加 kb，用于知识库原创转述卡（kb:<doc_id>）。
- **原因**：真实语料 17 份覆盖标准/规划/统计/法规/厂商文档，横跨原有三类；硬套 mv/web 会造成语义失真。
- **影响面**：仅 description 文本与文档；pattern 未变（^[a-z]+:[A-Za-z0-9_-]+$ 本就允许任意小写命名空间），正反例不受影响。
- **不涉及**：字段增减、必填项、跨契约引用。
- **时间**：11-07 22:00 冻结前完成，属于冻结前变更。
