# D：Issue #43 演示脚本

负责人 D（2055034503-ai）；脚本版本：2026-11-06，基线 main `4d97621`。
脚本时长 **6 分 22 秒**；本机字幕录屏封装时长约 **6 分 23 秒**，无配音，不剪除失败轮次。
视频产物在 `outputs/d-demo-video/`，运行 / 章节清单为 `recording.json`。
此次演示使用 Mock LLM、占位语料、真实检索与真实 L1，不宣称 A API、L2/L3 已实现。

## 准备

在仓库根目录运行（Windows 如有 pytest 插件冲突，先禁用自动加载）：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m src.run --output outputs/demo
python -m pytest tests/test_console.py -q
python scripts/check.py
python -m web.demo_server
```

打开本机控制台，选择默认「本机实际纵切」。录制器建议 1600×1000；
字幕只能解释画面，不能修改 Trace、评分或节点颜色。执行很快，应明确说明后续为同一运行的放慢回放。

## 连续六幕

| 时间 | 操作与画面 | 讲述要点 |
| --- | --- | --- |
| 0:00–0:58 | 展示模式说明，输入机器视觉产线质检需求，查看 11 节点图 | D 负责编排与可视化；Mock 模型与占位资料的边界明确。默认回边 fanout，issue 可定向到 write。 |
| 0:58–1:45 | 点击运行；SSE 接收本次实际事件；选择 1.5 秒步长重放，在首轮 verify end 暂停 | 执行与回放分别说明。所有颜色从事件归约；verify 绿色表示执行完成，业务质量看评分卡。 |
| 1:45–3:30 | 滚到首轮评分卡和草稿；保留 fail；指出缺引用的「1. 现状痛点」 | CITATION_MISSING、blocker、target_node=write。即使总分 0.950 高于阈值 0.85，也必须 fail。 |
| 3:30–4:38 | 定位 revise 事件，逐步看第 1 轮 write → verify，查看 pass 1.000 | 检索、分析和提纲未重新执行。gate / review / snap 是后续出口，不是再次检索。保留两轮评分卡。 |
| 4:38–5:48 | 查看下载项，打开本次 evidence_chain.json 与 delivery_artifact.json 的 manifest 原文 | 引用 ID 真实来自本次检索；四件交付物可下载，manifest 提供 commit、SHA256、字节数。 |
| 5:48–6:22 | 载入 CLI 生成的 outputs/demo/trace.jsonl 并重放；展示复现命令 | 按时间排序、只读回放；缺失评分历史时不编造。API 等 #40 完成后联调，L2/L3 仍待接入。 |

## 验收证据与复核

- 本机控制台同一次 run：SSE 的 trace、result.events、下载 trace.jsonl 和
  delivery_artifact.trace_bundle 逐条相同；不以「页面能打开」替代验证。
- 初轮 / 修订轮评分直接捕获实际 verify end 的输出；每份快照的 SHA256 应等于
  对应事件的 output_digest，完整正文只写本机 review_history.json，不扩展 Trace 契约。
- trace.jsonl 中第 1 轮 start 应只有 write、verify、gate、review、snap；
  retrieve / analyze / outline 仅第 0 轮执行。
- 视频可复核 recording.json 的 run_id / download_id / 章节；原始交付物在
  outputs/d-console/<download_id>/。这些是运行产物，不提交到 Git。

## 仍需集成

本片为本机链路演示；A 的 #40 合入后，切换 API 模式，对实际 POST /runs、SSE、artifacts
再核对同一 run 的事件与交付物，并按需要补录 API 版本。接口截止 2026-11-17，视频截止
2026-11-18。在实际 API 验收前不关闭 #43，不宣称三层验证完成。
