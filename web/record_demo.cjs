/*
 * Issue #43 final demonstration recording.
 * Requires A's API on 8000 and D's same-origin console on 8766.
 * Captions explain the screen only; they never change Trace, scores, or node state.
 */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const BASE = process.env.CONSOLE_URL || 'http://127.0.0.1:8766';
const OUT = path.resolve(process.env.RECORD_DIR || 'outputs/d-demo-video');
const TOTAL_SECONDS = 382;

(async () => {
  fs.mkdirSync(OUT, {recursive: true});
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({
    viewport: {width: 1920, height: 1080},
    recordVideo: {dir: OUT, size: {width: 1920, height: 1080}},
  });
  const page = await context.newPage();
  const video = page.video();
  const started = Date.now();
  const chapters = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  async function until(second) {
    const remaining = second * 1000 - (Date.now() - started);
    if (remaining > 0) await page.waitForTimeout(remaining);
  }

  async function caption(second, title, body) {
    await until(second);
    chapters.push({second, actual_second: (Date.now() - started) / 1000, title, body});
    await page.evaluate(({title, body}) => {
      let box = document.getElementById('recording-caption');
      if (!box) {
        box = document.createElement('aside');
        box.id = 'recording-caption';
        box.style = [
          'position:fixed', 'z-index:10000', 'left:48px', 'right:48px', 'bottom:24px',
          'padding:18px 28px', 'background:#10243af2', 'color:#fff',
          'border:1px solid #49728b', 'border-radius:12px',
          'font:24px/1.6 Microsoft YaHei,sans-serif',
          'box-shadow:0 3px 20px #10243a55', 'pointer-events:none',
        ].join(';');
        document.body.appendChild(box);
      }
      box.replaceChildren();
      const heading = document.createElement('strong');
      heading.style = 'display:block;color:#a8e6e6;font-size:28px';
      heading.textContent = title;
      const text = document.createElement('span');
      text.textContent = body;
      box.append(heading, text);
    }, {title, body});
    console.log(JSON.stringify({second, title}));
  }

  async function seek(count) {
    await page.locator('#seek').evaluate((element, value) => {
      element.value = String(value);
      element.dispatchEvent(new Event('input', {bubbles: true}));
    }, count);
  }

  try {
    await page.goto(BASE, {waitUntil: 'networkidle'});
    await page.waitForFunction(() => !document.querySelector('#run').disabled);
    assert.equal(await page.locator('#mode').inputValue(), 'api');
    await caption(0, '链衡 ChainGuard · D 组真实 API 演示', '连续录制：Mock LLM + 离线占位语料 + 实际检索、L1 与启发式 Mock L2。L3 尚未实现。');
    await caption(18, '痛点：结果必须可追溯', '产业需求不是一次性文本生成。每次修订都要知道哪个节点执行、哪条规则失败、为什么只回退到指定节点。');
    await page.locator('#request').fill('用机器视觉升级精密零件产线质检，输出可落地方案。');
    await caption(38, '11 节点工作流', 'plan → retrieve → fanout → analyze / outline → write → verify → gate → review → snap；默认回边是 revise → fanout。');
    await until(52);
    await page.locator('details.panel').evaluate(element => {element.open = true;});
    await page.locator('#workflow-source').scrollIntoViewIfNeeded();
    await caption(58, '实际 YAML 配置', '画面中的拓扑来自 workflows/industry_solution.yaml；页面显示真实源文件，不在演示中手工画一张替代图。');
    await until(69);
    await page.locator('details.panel').evaluate(element => {element.open = false;});
    await page.locator('#run').scrollIntoViewIfNeeded();
    await page.locator('#run').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent === '通过', null, {timeout: 120000});
    const actual = await page.evaluate(() => ({events, history, result: lastResult}));
    assert.ok(actual.result.run_id);
    assert.deepEqual(actual.history.map(item => item.scorecard.verdict), ['fail', 'pass']);
    const rawTrace = await page.request.get(`${BASE}/api/files/${actual.result.run_id}/trace.jsonl`).then(response => response.text());
    const stored = rawTrace.trim().split(/\r?\n/).map(JSON.parse);
    assert.deepEqual(actual.events, stored);
    const artifact = await page.request.get(`${BASE}/runs/${actual.result.run_id}/artifacts`).then(response => response.json());
    assert.deepEqual(stored, artifact.trace_bundle);
    const failed = stored.findIndex(event => event.event_id === actual.history[0].event_id) + 1;
    const revise = stored.findIndex(event => event.kind === 'revise') + 1;
    const passed = stored.findIndex(event => event.event_id === actual.history[1].event_id) + 1;
    await caption(76, '真实 HTTP API 已完成', `页面收到 ${stored.length} 条 SSE 事件；浏览器事件、落盘 trace.jsonl 与 delivery_artifact.trace_bundle 逐条相同。`);
    await page.locator('#pace').selectOption('1500');
    await page.locator('#replay').click();
    await page.waitForTimeout(Math.max(0, failed * 1500 - 450));
    await seek(failed);
    await caption(113, '首轮真实检查：fail', 'CITATION_MISSING 是 blocker；即使 0.950 高于 0.85 阈值，也必须 fail。verify 绿色只表示检查执行完成。');
    await page.locator('#reviews').scrollIntoViewIfNeeded();
    await caption(140, '失败原因与目标节点', '问题段落是「1. 现状痛点」，target_node=write。LoopController 使用这个目标定向回退，不重新运行无关节点。');
    await seek(revise);
    await page.locator('.graph').scrollIntoViewIfNeeded();
    await caption(172, 'Trace 记录 revise', '紫色状态来自真实 revise 事件；页面的状态颜色全部由 Trace 归约，不由字幕或前端分数推断。');
    await seek(revise + 1);
    await caption(196, '定向回退：write → verify', '第 1 轮只重新执行受影响路径；retrieve、analyze、outline 没有第二轮 start 事件，原结果继续复用。');
    await seek(passed);
    await caption(224, '修订后：pass / 1.000', '失败轮次保留在回放和评分卡里；补齐引用后才通过，页面没有把 fail 改成 pass。');
    await page.locator('#reviews').scrollIntoViewIfNeeded();
    await caption(248, '交付物与完整性校验', 'solution.md、evidence_chain.json、scorecard.json、trace.jsonl 加 delivery_artifact.json；manifest 记录 SHA256 与字节数。');
    await page.locator('#evidence').click();
    await page.waitForFunction(() => document.querySelector('#preview').textContent.includes('char_range'));
    await caption(276, '证据链可回溯', '证据引用来自本次检索。页面读取 evidence_refs.json；代理在提供文件前按 manifest 校验摘要，篡改会被拒绝。');
    await page.locator('#round-select').selectOption('0');
    await caption(297, '回放只读', '拖动进度条只重建节点状态与评分摘要，不重新调用工具，不伪造历史草稿，不提供 checkpoint 续跑。');
    const fixturePath = path.resolve('outputs/d-round3/trace.jsonl');
    assert.ok(fs.existsSync(fixturePath), 'run python -m web.capture_round3 first');
    await page.locator('#import').setInputFiles({
      name: 'fault-injection-r3.trace.jsonl', mimeType: 'text/plain',
      buffer: fs.readFileSync(fixturePath),
    });
    await page.waitForFunction(() => document.querySelector('#status').textContent === '已导入');
    await caption(321, '故障注入回放：R3', '这是演示夹具逐轮修复缺失引用，不是普通 API 运行自然经过三轮；页面仍展示实际生成的 Trace。');
    await page.locator('#round-select').selectOption('3');
    await page.locator('.graph').scrollIntoViewIfNeeded();
    const fixtureEvents = await page.evaluate(() => events);
    const r3Write = fixtureEvents.findIndex(event => event.round === 3 && event.kind === 'start' && event.node_id === 'write');
    const r3Verify = fixtureEvents.findIndex(event => event.round === 3 && event.kind === 'start' && event.node_id === 'verify');
    await seek(r3Write + 1);
    assert.equal(await page.locator('#node-write').getAttribute('class'), 'node running');
    await until(339);
    await seek(r3Verify + 1);
    assert.equal(await page.locator('#node-verify').getAttribute('class'), 'node running');
    assert.match(await page.locator('#round-path').innerText(), /R3.*write.*verify/);
    await caption(350, 'R3 路径：write → verify → gate → review → snap', '拖动进度条定位第三轮重跑，证明回放能够看到定向路径；这是故障注入证据，边界在文档中明示。');
    await until(370);
    await page.locator('#load-demo').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent === 'CLI Trace 已载入');
    await caption(370, '复现命令与工程边界', 'python -m src.run --output outputs/demo；pytest tests/test_console.py -q；python scripts/check.py。模型仍为 Mock，L3 待实现。');
    await until(TOTAL_SECONDS);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    await context.close();
    const webmPath = await video.path();
    const stableWebm = path.join(OUT, 'chainguard-d-console-api-1080p.webm');
    fs.copyFileSync(webmPath, stableWebm);
    const manifest = {
      source_webm: stableWebm,
      captured_at: timestamp,
      duration_seconds: (Date.now() - started) / 1000,
      viewport: {width: 1920, height: 1080},
      actual_api: true,
      run_id: actual.result.run_id,
      event_count: stored.length,
      verdicts: actual.history.map(item => item.scorecard.verdict),
      trace_matches_file: true,
      trace_matches_artifact: true,
      round3_fixture: 'outputs/d-round3/trace.jsonl',
      round3_is_fault_injection: true,
      captions_burned_in: true,
      audio: false,
      continuous: true,
      browser_errors: errors,
      chapters,
    };
    fs.writeFileSync(path.join(OUT, 'recording.json'), JSON.stringify(manifest, null, 2), 'utf8');
    console.log(JSON.stringify(manifest));
  } finally {
    await context.close().catch(() => {});
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
