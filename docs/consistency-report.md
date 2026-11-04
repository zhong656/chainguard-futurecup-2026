# 一致性检查报告

> 本文件由 `scripts/check_contracts.py` 自动生成，**禁止手改**。
> 有异议请改脚本或改源文件后重跑 `make check`。

- 检查项：8
- 失败：0
- 警告：4
- 结论：PASS 通过

| 判定 | 检查项 | 详情 | 归属 |
| --- | --- | --- | --- |
| OK | 契约解析 | 10 份可解析 | - |
| OK | $ref 可解析 | 全部引用指向真实存在的文件与片段 | - |
| WARN | 配置待填 agents/*.yaml | 6 份仍是注释占位：agents/analyst.yaml, agents/planner.yaml, agents/researcher.yaml, agents/reviewer.yaml, agents/verifier.yaml, agents/writer.yaml | C |
| WARN | 配置待填 workflows/*.yaml | 1 份仍是注释占位：workflows/industry_solution.yaml | D |
| OK | 正反例 | 10 组全部符合预期（正例通过、反例被拒） | - |
| OK | 归属覆盖 | 9 个一级目录均已登记 | - |
| WARN | 依赖锁定 | 20/20 个依赖未锁版本（11/07 冻结前必须回填） | A |
| WARN | source_id | knowledge/sources.yaml 尚未建立，跳过 | B |
