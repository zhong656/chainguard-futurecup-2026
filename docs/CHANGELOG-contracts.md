# 契约定稿记录

2026-11-04  llm_response  provider 限四种；响应仅表示成功调用；usage 只记供应商报告的 token，Mock 为 0/0；degraded 由调度器在成功降级后置位；mock 与实际 provider 一致。— A 定，待团队复核 — 影响：LLM 适配层、调度器、Trace。

2026-11-04  task_state  运行状态为五态；预算按包含重试的调用尝试次数计；续跑读取 checkpoint，Trace 只用于审计。— A 定，待团队复核 — 影响：调度器、checkpoint、交付重放。
