/* 实际 HTTP 浏览器验收。需已启动 A API 和 D 控制台，并安装 Playwright/Edge。 */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');

// 验收期望来自 trace_event 语义与页面图例，不调用被验收的 TraceView.reduce。
const eventStates = {start:'running',end:'done',fail:'failed',abort:'failed',
  retry:'retrying',degrade:'degraded',revise:'revising',checkpoint:null};
const palette = {
  '':['#f3f6fa','#d6dee8'], running:['#e0f4f4','#0d939c'], done:['#e8f5ef','#62a789'],
  failed:['#fcebea','#d57d76'], retrying:['#fff1d8','#c19030'],
  degraded:['#fff1d8','#c19030'], revising:['#efe5ff','#9773bf']
};
const rgb = hex => `rgb(${hex.slice(1).match(/../g).map(value=>parseInt(value,16)).join(', ')})`;

(async () => {
  const output = path.resolve(process.env.CONSOLE_EVIDENCE_DIR || 'outputs/d-api-evidence');
  const thirdPath = process.env.ROUND3_TRACE || 'outputs/d-round3/trace.jsonl';
  fs.mkdirSync(output,{recursive:true});
  // 失败时不让上次的 PASS 报告被误当成本次结果。
  for (const name of ['browser-report.json','frame-checks.json']) {
    fs.rmSync(path.join(output,name),{force:true});
  }
  const third = fs.readFileSync(thirdPath);
  const thirdEvents = third.toString('utf8').trim().split(/\r?\n/).map(JSON.parse);
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const page = await browser.newPage({viewport:{width:1920,height:1080}});
  const errors = [], requests = [], replayRequests = [], frameChecks = {};
  let replayPhase = null;
  // 重放若尝试联网会被记录并阻止，包括旧本地运行端点及任意工具接口。
  await page.route('**/*', route => {
    if (!replayPhase) return route.continue();
    const request = route.request();
    replayRequests.push({phase:replayPhase,method:request.method(),path:new URL(request.url()).pathname});
    return route.abort();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {if (request.url().includes('/runs')) requests.push({method:request.method(),path:new URL(request.url()).pathname});});
  const base = process.env.CONSOLE_URL || 'http://127.0.0.1:8766';
  async function seek(count) {await page.locator('#seek').evaluate((el,n)=>{el.value=n;el.dispatchEvent(new Event('input'));},count);}
  async function verifyFrame(items,count,nodeIds) {
    const expected = Object.fromEntries(nodeIds.map(id=>[id,'']));
    for (const item of items.slice(0,count)) {
      assert.ok(Object.hasOwn(eventStates,item.kind),`未知事件类型 ${item.kind}`);
      assert.ok(Object.hasOwn(expected,item.node_id),`未知节点 ${item.node_id}`);
      if (eventStates[item.kind]) expected[item.node_id] = eventStates[item.kind];
    }
    const actual = await page.evaluate(ids=>({
      count:document.querySelector('#count').textContent,
      round:document.querySelector('#round').textContent,
      nodes:Object.fromEntries(ids.map(id=>{
        const node = document.getElementById('node-'+id), style = getComputedStyle(node.querySelector('rect'));
        return [id,{class:node.getAttribute('class').trim(),fill:style.fill,stroke:style.stroke}];
      }))
    }),nodeIds);
    assert.equal(actual.count,`${count} / ${items.length}`);
    assert.equal(actual.round,`${items[count-1]?.round ?? 0} / 3`);
    for (const id of nodeIds) {
      const state = expected[id], label = `第 ${count} 帧 / ${items[count-1]?.event_id || '初始'} / ${id}`;
      assert.deepEqual(actual.nodes[id],{
        class:('node '+state).trim(),fill:rgb(palette[state][0]),stroke:rgb(palette[state][1])
      },label);
    }
    return {count,event_id:items[count-1]?.event_id ?? null,nodes:expected};
  }
  async function verifyAllFrames(name,items,nodeIds) {
    const frames = [];
    for (let count=0;count<=items.length;count++) {
      await seek(count); frames.push(await verifyFrame(items,count,nodeIds));
    }
    // 已结束的节点在向后拖动后必须恢复当时状态，不能残留最终的绿色。
    for (const count of [Math.floor(items.length/2),0,items.length]) {
      await seek(count); await verifyFrame(items,count,nodeIds);
    }
    assert.deepEqual(await page.evaluate(()=>events),items,'重放不能改写 Trace');
    frameChecks[name] = {events:items.length,nodes:nodeIds.length,frames,
      node_checks:frames.length*nodeIds.length,rewind_node_checks:3*nodeIds.length};
  }
  async function importTrace(buffer,name) {
    await page.locator('#import').setInputFiles({name,mimeType:'text/plain',buffer});
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='已导入');
    assert.deepEqual(await page.evaluate(()=>({history,result:lastResult})),{history:[],result:null});
    assert.equal(await page.locator('#evidence').isDisabled(),true);
    assert.equal(await page.locator('#downloads a').count(),0);
  }
  try {
    await page.goto(base);
    await page.locator('#run').waitFor({state:'visible'});
    await page.waitForFunction(()=>!document.querySelector('#run').disabled);
    const nodeIds = await page.evaluate(()=>workflow.nodes.map(node=>node.id));
    assert.equal(nodeIds.length,11);
    assert.equal(await page.locator('#mode').inputValue(),'api');
    await page.locator('#run').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='通过');
    const actual = await page.evaluate(()=>({events,history,result:lastResult}));
    const artifact = await page.request.get(`${base}/runs/${actual.result.run_id}/artifacts`).then(r=>r.json());
    const raw = await page.request.get(`${base}/api/files/${actual.result.run_id}/trace.jsonl`).then(r=>r.text());
    const stored = raw.trim().split('\n').map(JSON.parse);
    assert.deepEqual(actual.events,stored); assert.deepEqual(actual.events,artifact.trace_bundle);
    assert.deepEqual(actual.history.map(r=>r.scorecard.verdict),['fail','pass']);
    assert.deepEqual(requests.map(r=>r.path),['/runs',`/runs/${actual.result.run_id}/events`,`/runs/${actual.result.run_id}/artifacts`]);
    await page.waitForLoadState('networkidle');
    replayPhase = 'api-trace';
    await verifyAllFrames('api',stored,nodeIds);
    replayPhase = null;
    const failed = stored.findIndex(e=>e.event_id===actual.history[0].event_id)+1;
    await seek(13);
    await page.locator('.graph').screenshot({path:path.join(output,'01-workflow.png')});
    await seek(failed);
    assert.match(await page.locator('#reviews').innerText(),/fail/);
    assert.match(await page.locator('#status').innerText(),/fail/);
    await page.locator('.columns').screenshot({path:path.join(output,'02-failed-round.png')});
    await seek(stored.length);
    await page.locator('.columns').screenshot({path:path.join(output,'03-passed-round.png')});
    await page.locator('#evidence').click();
    await page.waitForFunction(()=>document.querySelector('#preview').textContent.includes('char_range'));
    assert.match(await page.locator('#preview').innerText(),/char_range/);
    await page.locator('#preview').screenshot({path:path.join(output,'04-evidence-refs.png')});
    await page.locator('details.panel').evaluate(el=>el.open=true);
    await page.locator('#workflow-source').screenshot({path:path.join(output,'05-workflow-yaml.png')});
    for (const [file,name] of [['scorecard','06-scorecard.png'],['convergence','07-convergence.png']]) {
      const chart = await browser.newPage({viewport:{width:1280,height:720}});
      await chart.goto(`${base}/api/files/${actual.result.run_id}/charts/${file}.svg`);
      await chart.screenshot({path:path.join(output,name)}); await chart.close();
    }
    await page.waitForLoadState('networkidle');
    replayPhase = 'round3-import';
    await importTrace(third,'故障注入-R3.trace.jsonl');
    assert.deepEqual([...new Set(thirdEvents.map(item=>item.round))],[0,1,2,3]);
    await verifyAllFrames('round3',thirdEvents,nodeIds);
    await page.locator('#round-select').selectOption('3');
    assert.equal(await page.locator('#node-write').getAttribute('class'),'node running');
    await page.locator('#step').click(); await page.locator('#step').click();
    assert.equal(await page.locator('#node-verify').getAttribute('class'),'node running');
    assert.match(await page.locator('#round-path').innerText(),/R3.*write → verify/);
    await page.screenshot({path:path.join(output,'08-round3-replay.png'),fullPage:true});
    // 真实计时器完整走完 R0–R3；完成后仍保持导入 Trace 的只读语义。
    await page.locator('#pace').selectOption('180');
    await page.locator('#replay').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='重放完成',null,
      {timeout:Math.max(30000,thirdEvents.length*200)});
    await verifyFrame(thirdEvents,thirdEvents.length,nodeIds);
    assert.deepEqual(await page.evaluate(()=>events),thirdEvents);
    // 独立 UI 夹具覆盖实际成功运行未必出现的 fail/retry/degrade/abort/checkpoint。
    // 它只验着色，明确区别于上面的真实 API 与受控故障注入纵切。
    replayPhase = 'event-kind-fixture';
    const fixture = ['start','end','fail','retry','degrade','revise','abort','checkpoint'].map((kind,i)=>({
      event_id:`ui-state-${i}`,trace_id:'ui-state-fixture',run_id:'ui-state-fixture',
      ts:`2026-11-01T00:00:00.00${i}Z`,node_id:'write',kind,round:0
    }));
    await importTrace(Buffer.from([...fixture].reverse().map(item=>JSON.stringify(item)).join('\n')),
      '仅界面状态验收.trace.jsonl');
    await verifyAllFrames('event_kinds',fixture,nodeIds);
    await page.waitForLoadState('networkidle');
    assert.deepEqual(replayRequests,[],'导入、拖动、单步及自动重放不得尝试网络请求');
    assert.deepEqual(errors,[]);
    const report = {run_id:actual.result.run_id,actual_api:true,events:stored.length,
      matches_trace_file:true,matches_artifact:true,verdicts:['fail','pass'],round3_fixture:thirdPath,
      round3_is_injected:true,round3_write_verify_replay:true,round3_autoplay:true,
      imported_trace_clears_results:true,replay_network_requests:replayRequests,
      frame_checks:Object.fromEntries(Object.entries(frameChecks).map(([name,{frames,...summary}])=>
        [name,{...summary,frames:frames.length}])),
      event_kind_fixture_is_synthetic:true,event_kinds_checked:fixture.map(item=>item.kind),
      state_palette:palette,browser_errors:errors,requests,
      source_sha256:Object.fromEntries(['verify_console.cjs','app.js','trace_view.js','style.css'].map(file=>
        [file,createHash('sha256').update(fs.readFileSync(path.join(__dirname,file))).digest('hex')])),
      evidence_files:{api_trace:'api.trace.jsonl',round3_trace:'round3.trace.jsonl',frames:'frame-checks.json'}};
    fs.writeFileSync(path.join(output,'api.trace.jsonl'),raw);
    fs.writeFileSync(path.join(output,'round3.trace.jsonl'),third);
    fs.writeFileSync(path.join(output,'frame-checks.json'),JSON.stringify(frameChecks,null,2));
    fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
