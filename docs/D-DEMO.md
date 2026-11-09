# D：Issue #43 演示脚本

负责人 D（2055034503-ai）；脚本版本：2026-11-09，真实 API 纵切。
视频目标时长 **5–8 分钟**，1920×1080、H.264、中文字幕烧录、连续录制，不剪除失败轮次。
视频产物在 `outputs/d-demo-video/`，运行 / 章节清单为 `recording.json`。
此次演示使用真实 HTTP API、Mock LLM、占位语料、实际检索、L1 和启发式 Mock L2；L3
仍未实现。R3 `write → verify` 是明确标注的故障注入回放，不代表普通 API 运行自然经过三轮。

## 准备

在仓库根目录运行（Windows 如有 pytest 插件冲突，先禁用自动加载）：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m src.run --output outputs/demo
python -m pytest tests/test_console.py -q
python scripts/check.py
# 终端 1
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --no-access-log
# 终端 2
python -m web.demo_server --port 8766 --api-base http://127.0.0.1:8000
```

打开本机控制台，默认模式就是「真实 HTTP API」。录制器使用 1920×1080；字幕只能解释
画面，不能修改 Trace、评分或节点颜色。执行很快，应明确说明后续为同一运行的放慢回放。

## 连续七幕

下表是录制器的计划时间；界面操作可能使章节延后，实际时间记录在
`recording.json` 的 `chapters[].actual_second`，成片时长以媒体元数据为准。

| 时间 | 操作与画面 | 讲述要点 |
| --- | --- | --- |
| 0:00–1:09 | 展示模式说明，输入机器视觉产线质检需求，查看 YAML 与 11 节点图 | D 负责编排与可视化；Mock 模型与占位资料的边界明确。默认回边 fanout，issue 可定向到 write。 |
| 1:09–1:53 | 点击运行；SSE 接收本次实际事件；选择 1.5 秒步长重放，在首轮 verify end 暂停 | 页面通过同源代理消费 A 的真实 API；所有颜色从事件归约；verify 绿色表示执行完成，业务质量看评分卡。 |
| 1:53–2:52 | 滚到首轮评分卡；保留 fail；指出缺引用的「1. 现状痛点」 | CITATION_MISSING、blocker、target_node=write。即使总分 0.950 高于阈值 0.85，也必须 fail；API 未导出的历史草稿不编造。 |
| 2:52–4:08 | 定位 revise 事件，逐步看第 1 轮 write → verify，查看 pass 1.000 | 检索、分析和提纲未重新执行。gate / review / snap 是后续出口，不是再次检索。保留两轮评分卡。 |
| 4:08–5:21 | 查看下载项与 evidence_refs.json 原文；拖动进度条 | 引用 ID 真实来自本次检索；交付物可下载，manifest 提供 commit、SHA256、字节数；回放只读。 |
| 5:21–6:10 | 导入故障注入 R3 Trace，选择 R3 并逐步定位 write、verify | 明确这是逐轮修复引用的夹具；展示实际生成的第三轮事件，不表示普通 API 需要三轮。 |
| 6:10–结束 | 载入 CLI Trace，展示复现命令与边界 | 按时间排序、只读回放；页面默认真实 API，L2 为启发式 Mock，L3 尚未实现。 |

## 验收证据与复核

- 同一次真实 API run：浏览器收到的 SSE、下载的 trace.jsonl 和
  `delivery_artifact.trace_bundle` 逐条相同；不以「页面能打开」替代验证。
- 初轮 / 修订轮评分来自 API 落盘的 rounds.json，与同轮 verify end 事件关联。
  API 未导出历史草稿，页面只展示实际问题摘要与最终 solution.md，不扩展 Trace 契约。
- trace.jsonl 中第 1 轮 start 应只有 write、verify、gate、review、snap；
  retrieve / analyze / outline 仅第 0 轮执行。
- 视频可复核 recording.json 的 run_id / 章节；原始交付物在
  outputs/api/<run_id>/。这些是运行产物，不提交到 Git。

## 回放边界

R3 回放由 `python -m web.capture_round3` 生成，实际调用现有纵切、验证器、LoopController
和 Trace 生成器，只替换 Mock LLM 输出制造逐轮缺引用。页面选择 R3 后可定位到实际
`write → verify → gate → review → snap`；字幕和页面都明确它是故障注入，不把它当作普通
API 运行的结果。L2 当前是启发式 Mock，L3 双路检索比对仍未实现。
