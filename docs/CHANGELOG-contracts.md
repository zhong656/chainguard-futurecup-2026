# 契约定稿记录

2026-11-04  llm_response  provider 限四种；响应仅表示成功调用；usage 只记供应商报告的 token，Mock 为 0/0；degraded 由调度器在成功降级后置位；mock 与实际 provider 一致。— A 定，待团队复核 — 影响：LLM 适配层、调度器、Trace。

2026-11-04  task_state  运行状态为五态；预算按包含重试的调用尝试次数计；续跑读取 checkpoint，Trace 只用于审计。— A 定，待团队复核 — 影响：调度器、checkpoint、交付重放。

2026-11-05  workflow  空依赖为唯一入口；when 使用受限 Python 比较语法；普通依赖无环、回边显式声明；修订最多 3 轮、连续两轮无提升停止；固定 analyze/write 供评分卡回退。— D 定，待 A/C 复核 — 影响：工作流编译与 LoopController（D）、调度与 checkpoint（A）、Agent 名称与 scorecard.target_node（C）。
