<!--
提交前请逐项填写；空着的项说明你还没准备好，别提交 PR。
-->

## 这个 PR 做了什么

<!-- 一段话说清「为什么改」，而不是逐条罗列 diff -->

## 关联 Issue

Closes #<!-- 必填，没有 Issue 先建一个 -->

## 变更类型

- [ ] feat 新功能
- [ ] fix 缺陷修复
- [ ] docs 文档 / 材料
- [ ] refactor 重构
- [ ] test 测试
- [ ] chore 构建 / 依赖 / 脚手架
- [ ] perf 性能

## 影响范围

- [ ] 知识库（`knowledge/` `src/knowledge_hub.py`）
- [ ] Agent 定义（`agents/` `src/registry.py`）
- [ ] 编排（`workflows/` `src/dag_compiler.py`）
- [ ] 调度（`configs/scheduler.yaml` `src/scheduler.py`）
- [ ] 验证与 Self-Loop（`configs/verifier.yaml` `src/verifier/` `src/loop_controller.py`）
- [ ] 前端（`web/`）
- [ ] 文档 / 材料（`docs/`）

## 是否触及关键配置

- [ ] 改了 `configs/` / `agents/` / `workflows/`（**需第二人复核**，配置即行为）

## 自测

- [ ] `pytest -q` 通过
- [ ] 改动到 YAML 的话，已确认可被 `yaml.safe_load` 解析
- [ ] 本地跑过相关流程 / 复现指南对应步骤
- [ ] 没有提交 `.env`、`*.key`、`*.db`、`outputs/` 等敏感或产物文件

## 截图 / 输出（涉及 UI 或交付物必填）

<!-- 贴图或贴关键输出片段；注意打码，不要出现 Key、内网地址、他人姓名 -->

## 回滚方式

<!-- 出问题怎么退：revert 该 commit / 改回哪个配置值 / 降级到哪个档位 -->

## 复核人确认（由复核者填写）

- [ ] 我已实际读过 diff，而非只看标题
- [ ] 敏感信息与调试残留已排查
- [ ] 结论：可以合并 / 需要修改
