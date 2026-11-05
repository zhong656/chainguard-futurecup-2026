# D 组离线演示与交接

本目录是 11/07 纵切的本机验收入口。评分与角色调用明确标为 Mock 桩；检索消费 B 的既有接口，不要求 A/C 模块先完成。生产 FastAPI/Scheduler 与 C 的四类规则验证器由相应 Owner 接入。

## 命令行

```powershell
python -m web.mock_runtime --output outputs/d-demo
python -m web.mock_runtime --scenario numeric_conflict --output outputs/d-numeric
```

默认轻量引擎只依赖现有检查依赖；真实 LangGraph 在隔离环境安装后运行：

```powershell
python -m venv --system-site-packages .venv
.venv\Scripts\python.exe -m pip install langgraph
.venv\Scripts\python.exe -m web.mock_runtime --engine langgraph
```

退出码 0 表示 Mock 通过；证据不足、超时或不收敛为非零，不假装成功。每次导出 `solution.md`、`evidence_chain.json`、`scorecard.json`、`trace.jsonl`，附通过既有契约校验的 `delivery_artifact.json` 与真实 commit SHA、文件 hash/字节数。所有产物在已忽略的 outputs/，不得提交。

## 控制台与重放

```powershell
python -m web.demo_server
# 浏览器访问 http://127.0.0.1:8765
```

选择场景并运行，实际事件通过 SSE 进入工作流图。可下载交付物、拖动 Trace 进度或导入 JSONL 只读重放。真实 LangGraph 选项需用上面的 `.venv` Python 启动服务；轻量引擎不依赖 LangGraph。

此页面是无前端安装步骤的阶段 0 演示原型；后续正式 Vue/Vite/X6 控制台、生产 API 及正式视频录制仍按交付计划推进。

## 接入约定

- `compile_langgraph(graph, handlers, active_nodes=...)` 编译一轮。handler 接收含 `results` 的状态，返回该节点结果。条件 handler 只消费 LoopController 的 pass/revise/abort 决定；普通依赖不含回边。
- `LoopController.decide(scorecard)` 读取既有评分卡和 verifier 配置，不调用模型。多问题合并下游重算；未受影响分支结果保留，默认落点为 fanout。
- 初稿 round=0，最多追加 3 轮；连续 2 轮分数未超过历史最佳值终止。一票否决不能被高总分覆盖。
- `src/trace.py` 提供结构校验、输入/输出哈希与审计重放；A 的生产日志策略与 checkpoint 接入需其会签。Trace 不保存需求/提示词原文，不作为续跑状态。
- 正式演示视频按 11/19 计划基于集成版本录制；建议依次展示正常修订、数值定向回退、无提升护栏、四件交付物及 Trace 重放。

## 验收

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1' # 仅本机已有 pytest 插件冲突时需要
python scripts/check.py
.venv\Scripts\python.exe -m pytest -q tests/test_langgraph.py tests/test_loop.py tests/test_trace.py tests/test_d_mock.py
```

CI 的最小依赖环境运行所有非 LangGraph 测试；可选 LangGraph 测试在未安装时明确 skip，不能把 skip 说成已验证。D 的开发环境必须实际安装并运行该组测试。
