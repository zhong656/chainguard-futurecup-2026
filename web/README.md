# D 组控制台与 Trace 重放（Issue #43）

D（2055034503-ai）负责工作流编排、Loop、Trace 和控制台。当前页面默认调用
`web.local_runtime → src.vertical_slice.run_vertical_slice`，消费既有 Mock LLM、B 的
实际离线检索 / EvidencePool、C 的实际 L1 检查和 D 的 LoopController。
首轮有意缺一处引用，真实检查产生 fail，定向修订后 pass；不代表正式产业方案。

## 启动与验收

```powershell
$env:PYTHONUTF8 = '1'
# 仅本机已有 pytest 插件冲突时需要：
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m src.run --output outputs/demo
python -m pytest tests/test_console.py -q
python scripts/check.py
python -m web.demo_server
# 浏览器打开 http://127.0.0.1:8765
```

最小检查环境无需安装 requirements.txt 或前端依赖。全套 LangGraph 验收另用已有
`.venv\Scripts\python.exe -m pytest -q`，缺 LangGraph 时的 skip 不能报作通过。

## 页面操作

- **运行工作流**：本机 `/api/run-real` 只适配既有纵切；SSE 中的 trace 与最终
  `outputs/d-console/<download_id>/trace.jsonl` 逐条一致，不合成节点事件。
- **评分历史**：独立的 `review_history.json` 保存实际 verify 输出和对应草稿，
  以 `event_id` 关联 Trace。拖动进度可查看首轮 blocker 与缺引用段落，再看修订结果。
  此侧文件含演示草稿正文，仅在本机 outputs/；分享前应自行检查，不属于正式四件交付物。
- **载入 CLI Trace**：读 `outputs/demo/trace.jsonl`；也可以导入任意本地 JSONL。
  按带时区时间戳稳定排序，同一时间保持文件顺序。拒绝重复事件、混合运行或非法时间。
  只有 Trace 时不推断评分或草稿，重放不调用工具、不支持 checkpoint 续跑。
- **状态颜色**：start=青、end=绿、fail/abort=红、retry/degrade=橙、revise=紫；
  checkpoint 仅列入时间线。verify 的 end 表示检查执行完成，质量 fail 单独显示。
- **交付下载**：四件交付物 + delivery_artifact.json（实际 Git SHA、SHA256、字节数）；
  review_history.json 为额外的本机调试侧文件。outputs/ 全部不入 Git。

## A API 接口预留（待 #40 合入后实测）

选择「A 的 API」，填写服务地址。页面严格按 Issue #40 调用：

1. `POST /runs`，body 仅 `{"request":"..."}`，读取 run_id。
2. `GET /runs/{run_id}/events`，接收 SSE 中原样的 trace_event（支持默认 message）。
3. 事件流结束后 `GET /runs/{run_id}/artifacts`，展示返回的交付包或文件列表。

跨端口访问需 A 的服务允许控制台来源的 CORS，或反向代理为同源。
当前只完成客户端与接口测试响应的核对；A 的实际 API 尚未落地，不能宣称完成联调。
未收到历史评分侧文件时仅显示实际返回的最终评分。

旧 `/api/run` 和 `python -m web.mock_runtime` 保留为明确的角色/评分桩回归测试；
页面默认不使用它们。L2 独立评审、L3 双路比对仍待各自实现，不宣称三层验证完成。

## 演示

见 `docs/D-DEMO.md` 的 6 分 22 秒连续演示脚本，保留 fail→pass。
本机字幕录屏及其运行清单位于 `outputs/d-demo-video/`，不是生产 API 验收视频。
Issue #43 在 API 实测前保持 open；接口对接截止 2026-11-17，最终录制截止 2026-11-18。
