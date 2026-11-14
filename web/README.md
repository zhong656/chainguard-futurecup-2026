# D 组控制台与 Trace 重放（Issue #43）

D（2055034503-ai）负责工作流编排、Loop、Trace 和控制台。页面默认通过同源代理调用
A 的真实 HTTP API：`POST /runs`、`GET /runs/{run_id}/events`、
`GET /runs/{run_id}/artifacts`。API 当前使用 Mock LLM、B 的实际离线检索 / EvidencePool、
C 的 L1 规则和启发式 Mock L2；首轮缺一处引用，真实检查产生 fail，定向修订后 pass。

## 启动与验收

```powershell
$env:PYTHONUTF8 = '1'
# 仅本机已有 pytest 插件冲突时需要：
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m src.run --output outputs/demo
python -m pytest tests/test_console.py -q
python scripts/check.py
# 终端 1：A 的 API
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --no-access-log
# 终端 2：D 的同源代理与静态页面
python -m web.demo_server --port 8766 --api-base http://127.0.0.1:8000
# 浏览器打开 http://127.0.0.1:8766
```

最小检查环境无需安装 requirements.txt 或前端依赖。全套 LangGraph 验收另用已有
`.venv\Scripts\python.exe -m pytest -q`，缺 LangGraph 时的 skip 不能报作通过。

## 页面操作

- **运行工作流**：默认模式经过同源代理访问 A 的真实 HTTP API。SSE 中的 trace、
  artifacts 返回的 `trace_bundle`、落盘 `trace.jsonl` 逐条相同；代理不会执行本地纵切。
- **评分历史**：API 的 `rounds.json` 保存每轮实际评分摘要，按 verify end 的 `event_id`
  关联 Trace。拖动进度可查看首轮 blocker 与缺引用段落，再看修订结果；API 不导出历史草稿，
  页面不会凭空生成正文。
- **载入 CLI Trace**：读 `outputs/demo/trace.jsonl`；也可以导入任意本地 JSONL。
  按带时区时间戳稳定排序，同一时间保持文件顺序。拒绝重复事件、混合运行或非法时间。
  只有 Trace 时不推断评分或草稿，重放不调用工具、不支持 checkpoint 续跑。
- **状态颜色**：start=青、end=绿、fail/abort=红、retry/degrade=橙、revise=紫；
  checkpoint 仅列入时间线。verify 的 end 表示检查执行完成，质量 fail 单独显示。
- **交付下载**：四件交付物、rounds.json、evidence_refs.json、两张 SVG 与
  delivery_artifact.json（实际 Git SHA、SHA256、字节数）。outputs/ 全部不入 Git。

## A API 实测接口

页面默认选择「真实 HTTP API」，地址由 `web.demo_server` 的 `--api-base` 配置，页面本身
不显示地址，便于录制时避免暴露内网信息。页面严格按 Issue #40 调用：

1. `POST /runs`，body 仅 `{"request":"..."}`，读取 run_id。
2. `GET /runs/{run_id}/events`，接收 SSE 中原样的 trace_event（支持默认 message）。
3. 事件流结束后 `GET /runs/{run_id}/artifacts`，展示返回的交付包或文件列表。

控制台代理会把 API 事件原样转发为同源 SSE，并从共享 `outputs/api/<run_id>/` 读取经过
manifest SHA256/字节数校验的 `rounds.json`、`solution.md` 和证据文件。远程 API 若不共享
该目录，仍可查看 artifacts，但历史侧文件会显示为不可用。未收到历史评分侧文件时仅显示
实际返回的最终评分。

旧 `/api/run` 和 `python -m web.mock_runtime` 保留为明确的角色/评分桩回归测试；
页面默认不使用它们。L2 当前为启发式 Mock，L3 双路比对尚未实现，不宣称三层验证完成。

## 演示

见 docs/D-DEMO.md（Issue #86）：官方时长 3–5 分钟，目标 4 分 30 秒。
保留平台界面、Agent 编排、调度执行、验证与反馈循环四段；仅回放本次 R0→R1，
每事件 0.18 秒；YAML 10 秒、证据链 20 秒。原 R3 故障注入夹具仍供独立验收。

浏览器验收和录制另需 Node、Playwright 与 Edge；不加入 Python 服务的 requirements。
启动上述两个服务后，浏览器验收可独立留档：

```powershell
python -m web.capture_round3
$env:CONSOLE_URL = 'http://127.0.0.1:8766'
$env:CONSOLE_EVIDENCE_DIR = 'outputs/d-console-acceptance'
node web/verify_console.cjs
```

验收会把真实 API 的 SSE 与 artifacts、落盘 Trace 逐条比较，再逐事件拖动进度，
核对全部 11 节点的 DOM 状态及实际填色、边框颜色，也验证向后拖动可恢复历史状态。
R3 夹具由受控故障注入的真实纵切生成，检查导入、轮次跳转、单步、完整自动重放；
这些重放操作若尝试任何网络请求，验收会阻止并判失败。导入后必须清除上一任务的评分、
正文结果和下载链接。额外 8 种事件的合成夹具仅用于界面着色验收，不能作为真实运行证据。

目录中保留 8 张截图、两份原始 Trace、逐帧 `frame-checks.json` 与汇总
`browser-report.json`（含源文件 SHA256）。默认目录仍是 `outputs/d-api-evidence`，
`ROUND3_TRACE` 可指定 R3 夹具路径；建议使用独立目录保留各次验收证据。
缺少 R3 夹具或任何断言失败都会非零退出，失败运行不会留下旧的通过报告。

新短版录制用 node web/record_demo.cjs，固定 1920×1080。CONSOLE_URL 可覆盖地址。

录制源与 recording.json 默认位于 outputs/d-demo-video-v2/，PPT 与 PDF 位于
outputs/d-materials/；均不入 Git。H.264 成片按 #86 放到
D:/未来杯-ChainGuard/成片材料-20261111/演示视频_v2.mp4。
使用 python scripts/check_video.py <成片路径> --frames 8 核验 180–300 秒及媒体参数，
再人工确认字幕烧录、敏感信息与四段操作完整。
