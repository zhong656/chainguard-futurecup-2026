# D：Issue #86 官方 3–5 分钟演示

负责人 D（2055034503-ai）；脚本版本：2026-11-11；替代 #43 的 393 秒旧成片。
官方赛制说明 P25 要求 **3–5 分钟（180–300 秒）**，本版目标 **4 分 30 秒**，
预留 30 秒余量。1920×1080、H.264、yuv420p、中文字幕烧录；无声字幕版。

## 必须保留的四段

| 时间 | 官方要求 | 实际操作与证据 |
| --- | --- | --- |
| 0:00–0:15 | 平台界面 | 输入产业需求，展示工作流、评分与 Trace 入口；直接说明 Mock 边界。 |
| 0:15–0:45 | Agent 编排过程 | YAML 只展示 10 秒；展示 11 节点、角色、并行分支和修订回边。 |
| 0:45–1:30 | 任务调度执行 | 点击真实 POST /runs；接收 SSE；以每事件 0.18 秒快速重放实际 start/end 事件。 |
| 1:30–2:50 | 结果验证与反馈循环 | R0 0.950 + blocker 仍 fail；问题定位 write；定向重跑 write→verify；保留 R1 1.000/pass。 |

## 补充画面与收尾

| 时间 | 内容 |
| --- | --- |
| 2:50–3:10 | 证据链 20 秒：本次 evidence_refs.json 与对应仓库原文片段核对。 |
| 3:10–4:05 | 同一 run 的 Trace 进度条，聚焦 R0→R1；交付物与 manifest。 |
| 4:05–4:20 | 四段操作摘要与实现边界。 |
| 4:20–4:30 | 复现命令与结束。 |

章节实际开始时间记录在 recording.json 的 chapters[].actual_second。
时长以最终 MP4 元数据为准，不能用录制器墙钟时间代替。

## 录制与验收

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:LLM_PROVIDER = 'mock'
# 终端 1
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --no-access-log
# 终端 2
python -m web.demo_server --port 8766 --api-base http://127.0.0.1:8000
# 终端 3，另需 Node、Playwright 与 Edge
node web/record_demo.cjs
python -m pytest tests/test_check_video.py tests/test_console.py -q
python scripts/check.py
# H.264 转码后；ffmpeg 与 ffprobe 须在 PATH
python scripts/check_video.py 'D:/未来杯-ChainGuard/成片材料-20261111/演示视频_v2.mp4' --frames 8
```

CONSOLE_URL 可指定控制台地址；RECORD_DIR 可覆盖输出目录。
原始录制与 recording.json 默认在 outputs/d-demo-video-v2/；最终成片按 #86 放到
`D:/未来杯-ChainGuard/成片材料-20261111/演示视频_v2.mp4`，生成物不入 Git。

scripts/check_video.py 的上下限同步改为 180/300 秒；边界用例包含 180、270、300
应通过，以及 179.99、300.01、393.36 应拒绝。旧脚本的 300–480 秒不能作为合规依据。
参数通过后仍需人眼检查字幕、敏感信息与四段关键操作。

## 真实性与边界

- 使用实际 HTTP API、Mock LLM、离线转述语料、实际检索与 L1/启发式 Mock L2；L3 未实现。
- 同一次 run 的 SSE、落盘 trace.jsonl 与 delivery_artifact.trace_bundle 逐条一致。
- R0/R1 评分来自本次 rounds.json，并关联同轮 verify end 的 event_id。
- 保留失败轮次；不伪造历史草稿，不用字幕或前端分数改变 Trace 和节点颜色。
- 证据核对的只读录制辅助视图读取对应仓库文件，按字符区间逐字核对 text 并复算
  SHA256 前 16 位；辅助视图不是应用新增功能。Markdown 无物理页，不编造 page。
- 本短版仅展示实际 R0→R1，不混入 R3 故障注入；原有 R3 夹具另供回放验收。
- Trace 重放只读，不再次调用工具，也不提供 checkpoint 续跑。
