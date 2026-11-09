/* 实际 HTTP 浏览器验收。需已启动 A API 和 D 控制台，并安装 Playwright/Edge。 */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const output = path.resolve('outputs/d-api-evidence'); fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const page = await browser.newPage({viewport:{width:1920,height:1080}});
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {if (request.url().includes('/runs')) requests.push({method:request.method(),path:new URL(request.url()).pathname});});
  const base = process.env.CONSOLE_URL || 'http://127.0.0.1:8766';
  async function seek(count) {await page.locator('#seek').evaluate((el,n)=>{el.value=n;el.dispatchEvent(new Event('input'));},count);}
  try {
    await page.goto(base);
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
    const third = fs.readFileSync('outputs/d-round3/trace.jsonl');
    await page.locator('#import').setInputFiles({name:'故障注入-R3.trace.jsonl',mimeType:'text/plain',buffer:third});
    await page.waitForFunction(()=>document.querySelector('#status').textContent==='已导入');
    await page.locator('#round-select').selectOption('3');
    assert.equal(await page.locator('#node-write').getAttribute('class'),'node running');
    await page.locator('#step').click(); await page.locator('#step').click();
    assert.equal(await page.locator('#node-verify').getAttribute('class'),'node running');
    assert.match(await page.locator('#round-path').innerText(),/R3.*write → verify/);
    await page.screenshot({path:path.join(output,'08-round3-replay.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    const report = {run_id:actual.result.run_id,actual_api:true,events:stored.length,
      matches_trace_file:true,matches_artifact:true,verdicts:['fail','pass'],round3_fixture:'outputs/d-round3/trace.jsonl',
      round3_is_injected:true,round3_write_verify_replay:true,browser_errors:errors,requests};
    fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
