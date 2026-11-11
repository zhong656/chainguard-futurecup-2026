/*
 * Issue #86 official 3–5 minute demonstration recording.
 * Requires A's API on 8000 and D's same-origin console on 8766.
 * Captions explain the screen only; they never change Trace, scores, or node state.
 */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const BASE = process.env.CONSOLE_URL || 'http://127.0.0.1:8766';
const OUT = path.resolve(process.env.RECORD_DIR || 'outputs/d-demo-video-v2');
const TOTAL_SECONDS = 270;
const OFFICIAL_SECONDS = {min: 180, max: 300};

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
    await caption(0, '平台界面 · 链衡 ChainGuard', '输入产业需求，运行工作流并查看评分、证据和 Trace。实际 HTTP API；模型为 Mock，L2 为启发式 Mock，L3 未实现。');
    await page.locator('#request').fill('用机器视觉升级精密零件产线质检，输出可落地方案。');

    await until(15);
    await page.locator('details.panel').evaluate(element => {element.open = true;});
    await page.locator('#workflow-source').scrollIntoViewIfNeeded();
    await caption(15, 'Agent 编排 · 真实 YAML，只展示 10 秒', '11 个节点声明依赖与角色：规划、检索、分析、写作、验证和复核；并行分析与提纲在 write 汇合。');
    await until(25);
    await page.locator('details.panel').evaluate(element => {element.open = false;});
    await page.locator('.graph').scrollIntoViewIfNeeded();
    await caption(25, 'Agent 编排 · 11 节点工作流图', '默认修订回边 revise → fanout；验证器给出 target_node 时，只重跑目标节点及受影响的下游。修订最多 3 轮。');

    await until(45);
    await page.locator('#run').scrollIntoViewIfNeeded();
    await caption(45, '任务调度执行 · 点击真实运行', 'POST /runs 创建任务，SSE 返回实际 start / end / revise 事件。节点颜色来自 Trace；不会用字幕改状态。');
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
    assert.ok(failed > 0 && revise > failed && passed > revise);
    await caption(60, '任务调度执行 · 实际事件快速重放', `本次 ${stored.length} 条 SSE 与 trace.jsonl、trace_bundle 逐条一致。每事件 0.18 秒，随后停在首轮验证结果。`);
    await page.locator('#pace').selectOption('180');
    await page.locator('#replay').click();
    await page.waitForTimeout(stored.length * 180 + 300);
    await seek(failed);
    await page.locator('.columns').scrollIntoViewIfNeeded();
    await caption(75, '任务调度执行 · 从事件核对节点', 'R0 按依赖运行 plan、retrieve、fanout、analyze / outline、write、verify。verify 绿色表示执行完成，业务质量单独看评分卡。');

    await caption(90, '验证与反馈循环 · R0 失败必须保留', '0.950 高于阈值 0.85，仍因 CITATION_MISSING blocker 判 fail。问题段落是「1. 现状痛点」，修订目标是 write。');
    await page.locator('#reviews').scrollIntoViewIfNeeded();
    await until(115);
    await seek(revise);
    await page.locator('.graph').scrollIntoViewIfNeeded();
    await caption(115, '验证与反馈循环 · 根据问题定向回退', 'revise 记录真实修订决定：target_node=write。保留原有检索、分析与提纲，不把整条链路再跑一遍。');
    const r1Write = stored.findIndex(event => event.round === 1 && event.kind === 'start' && event.node_id === 'write');
    const r1Verify = stored.findIndex(event => event.round === 1 && event.kind === 'start' && event.node_id === 'verify');
    assert.ok(r1Write >= 0 && r1Verify > r1Write);
    await until(130);
    await seek(r1Write + 1);
    await caption(130, '验证与反馈循环 · 只重跑 write → verify', '当前高亮来自本次 R1 start 事件。修订先进入 write，再交给 verify；首轮失败评分仍保留。');
    await until(140);
    await seek(r1Verify + 1);
    await until(150);
    await seek(passed);
    await page.locator('#reviews').scrollIntoViewIfNeeded();
    await caption(150, '验证与反馈循环 · R1 通过', '补齐引用后 1.000 / pass。页面同时保留 R0 fail 和 R1 pass；反馈驱动的是这次定向修订，不宣称普遍提升。');

    await until(170);
    await page.locator('#evidence').click();
    await page.waitForFunction(() => document.querySelector('#preview').textContent.includes('char_range'));
    await page.locator('#preview').scrollIntoViewIfNeeded();
    await caption(170, '证据链 · 本次 evidence_refs.json', 'source_id、file_path、char_range、text 与 hash 均来自本次运行。当前语料为 Markdown 转述卡，没有物理页码，不编造 page。');
    const refs = await page.request.get(`${BASE}/api/files/${actual.result.run_id}/evidence_refs.json`).then(response => response.json());
    const ref = refs.find(item => item.char_range && item.file_path.endsWith('.md'));
    assert.ok(ref, 'This run needs a text evidence source for the original-file comparison.');
    const knowledge = path.resolve('knowledge');
    const sourcePath = path.resolve(knowledge, ref.file_path);
    assert.ok(sourcePath.startsWith(knowledge + path.sep));
    const source = fs.readFileSync(sourcePath, 'utf8').replace(/\r\n?/g, '\n');
    const excerpt = Array.from(source).slice(ref.char_range[0], ref.char_range[1]).join('');
    assert.equal(excerpt, ref.text);
    assert.equal(crypto.createHash('sha256').update(excerpt, 'utf8').digest('hex').slice(0, 16), ref.hash);
    await until(180);
    // A read-only recording aid displays actual file bytes; it is not an app feature.
    await page.evaluate(({file, range, text, hash}) => {
      const panel = document.createElement('section'); panel.id = 'recording-source-proof';
      panel.style = 'position:fixed;inset:70px 120px 190px;z-index:9999;background:white;border:2px solid #087d89;border-radius:12px;padding:28px;font:24px/1.6 Microsoft YaHei,sans-serif;overflow:auto;color:#233247';
      const title = document.createElement('h2'); title.textContent = '原文核对 · 只读录制辅助视图';
      const location = document.createElement('p'); location.textContent = `knowledge/${file} · char_range=[${range.join(', ')}] · hash=${hash}`;
      const content = document.createElement('pre'); content.style = 'white-space:pre-wrap;overflow-wrap:anywhere;font:22px/1.7 Microsoft YaHei,sans-serif'; content.textContent = text;
      panel.append(title, location, content); document.body.appendChild(panel);
    }, {file:ref.file_path, range:ref.char_range, text:excerpt, hash:ref.hash});
    await caption(180, '证据链 · 对照仓库实际原文片段', '录制器读取对应文件的字符区间，逐字核对 text，并复算 SHA256 前 16 位。此视图只辅助展示真实文件内容，不更改应用数据。');
    await until(190);
    await page.locator('#recording-source-proof').evaluate(element => element.remove());

    await seek(failed);
    await page.locator('.columns').scrollIntoViewIfNeeded();
    await caption(190, 'Trace 重放 · R0 失败 → R1 通过', '拖动进度条只重建真实节点状态和评分历史，不再次调用模型或工具。短版聚焦本次 R0→R1，不混入第三轮故障注入夹具。');
    await until(205);
    await seek(r1Write + 1);
    await until(215);
    await seek(passed);
    await until(225);
    await seek(stored.length);
    await caption(225, 'Trace 重放 · 交付文件与校验包', '本次 solution.md、评分卡、证据链与 Trace 可下载；delivery_artifact.json 的 manifest 记录提交、SHA256 与字节数。');
    await until(245);
    await page.locator('.graph').scrollIntoViewIfNeeded();
    await caption(245, '四段闭环已展示', '平台界面 → Agent 编排 → 任务调度执行 → 验证与反馈循环。当前为实际 HTTP API + Mock 模型，L3 未实现。');
    await caption(260, '复现与结束', 'python -m src.run；python scripts/check.py。视频按官方 3–5 分钟验收，目标 4 分 30 秒；保留失败证据与实现边界。');
    await until(TOTAL_SECONDS);
    const recordedSeconds = (Date.now() - started) / 1000;
    const timestamp = new Date().toISOString();
    assert.deepEqual(errors, []);
    await context.close();
    const webmPath = await video.path();
    const stableWebm = path.join(OUT, 'chainguard-demo-v2-source.webm');
    fs.copyFileSync(webmPath, stableWebm);
    const manifest = {
      issue: 86, source_webm: stableWebm, captured_at: timestamp,
      capture_wall_seconds: recordedSeconds, target_seconds: TOTAL_SECONDS,
      official_seconds: OFFICIAL_SECONDS,
      official_sections: [
        {name:'平台界面', start:0, end:15}, {name:'Agent 编排过程', start:15, end:45},
        {name:'任务调度执行', start:45, end:90}, {name:'结果验证与反馈循环', start:90, end:170},
      ],
      viewport: {width:1920,height:1080}, actual_api:true, run_id:actual.result.run_id,
      event_count:stored.length, verdicts:actual.history.map(item => item.scorecard.verdict),
      trace_matches_file:true, trace_matches_artifact:true, replay_interval_ms:180,
      revision_rounds:[0,1], round3_included:false,
      evidence_comparison:{source_id:ref.source_id,file_path:ref.file_path,char_range:ref.char_range,hash:ref.hash,text_matches_source:true,hash_matches_source:true,display_start:180,display_end:190},
      captions_burned_in:true,audio:false,continuous:true,browser_errors:errors,chapters,
    };
    fs.writeFileSync(path.join(OUT, 'recording.json'), JSON.stringify(manifest,null,2), 'utf8');
    console.log(JSON.stringify(manifest));
  } finally {
    await context.close().catch(() => {});
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
