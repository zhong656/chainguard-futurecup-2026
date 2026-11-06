"use strict";
const $ = (id) => document.getElementById(id);
const ns = "http://www.w3.org/2000/svg";
let workflow, events = [], timer, lastResult, history = [];
const coords = {plan:[20,95],retrieve:[190,95],fanout:[360,95],analyze:[530,30],outline:[530,160],
  write:[700,95],verify:[870,95],gate:[1040,95],revise:[1040,240],review:[1210,95],snap:[1380,95]};

function svgElement(tag, attributes, parent = $("graph")) {
  const element = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  parent.appendChild(element);
  return element;
}
function drawGraph() {
  $("graph").replaceChildren();
  const defs = svgElement("defs", {});
  const marker = svgElement("marker", {id:"arrow",viewBox:"0 0 10 10",refX:9,refY:5,
    markerWidth:6,markerHeight:6,orient:"auto-start-reverse"}, defs);
  svgElement("path", {d:"M 0 0 L 10 5 L 0 10 z",fill:"#afbdcb"}, marker);
  for (const node of workflow.nodes) {
    for (const parent of node.depends_on || []) {
      const [x,y] = coords[parent], [a,b] = coords[node.id];
      svgElement("path", {d:`M ${x+140} ${y+27} L ${a-15} ${y+27} L ${a-15} ${b+27} L ${a} ${b+27}`,
        class:"edge","marker-end":"url(#arrow)"});
    }
  }
  svgElement("path", {d:"M 1040 267 L 430 267 L 430 150",class:"edge loop-edge","marker-end":"url(#arrow)"});
  for (const node of workflow.nodes) {
    const [x,y] = coords[node.id];
    const group = svgElement("g", {id:`node-${node.id}`,class:"node"});
    svgElement("rect", {x,y,width:140,height:55,rx:9}, group);
    svgElement("text", {x:x+70,y:y+24}, group).textContent = node.id;
    svgElement("text", {x:x+70,y:y+42,class:"type"}, group).textContent = node.agent || node.type;
  }
}
function showFrame(count) {
  const visible = events.slice(0,count), states = TraceView.reduce(visible);
  for (const node of workflow.nodes) $("node-"+node.id).setAttribute("class", "node " + (states[node.id] || ""));
  $("seek").value = count;
  $("count").textContent = `${count} / ${events.length}`;
  $("round").textContent = `${events[count-1]?.round ?? 0} / 3`;
  const visibleIds = new Set(visible.map(item => item.event_id));
  const reviews = history.filter(item => visibleIds.has(item.event_id));
  $("reviews").replaceChildren();
  for (const item of reviews) {
    const card = item.scorecard, box = document.createElement("article");
    box.className = "review " + card.verdict;
    const title = document.createElement("strong");
    title.textContent = `第 ${item.round} 轮 · ${card.verdict} · ${card.score.toFixed(3)} / ${card.threshold}`;
    const body = document.createElement("pre");
    body.textContent = card.issues.map(issue => `${issue.severity} · ${issue.rule_id || "规则"} · ${issue.section}\n${issue.reason}\n定向目标：${issue.target_node}；${issue.suggestion}`).join("\n\n") || "L1 检查通过；无未解决 issue。";
    box.append(title,body); $("reviews").appendChild(box);
  }
  const latest = reviews.at(-1);
  if (count < events.length) $("status").textContent = latest ? `回放 · ${latest.scorecard.verdict}` : "回放中";
  else if (lastResult) $("status").textContent = lastResult.passed ? "通过" : "已终止";
  [...$("timeline").children].forEach((row,index) => {
    row.classList.toggle("future", index >= count);
    row.classList.toggle("current", index === count-1);
    if (index === count-1) $("timeline").scrollTop = row.offsetTop - $("timeline").offsetTop;
  });
  if (latest) {
    $("score").textContent = `${latest.scorecard.score.toFixed(3)} / ${latest.scorecard.threshold}`;
    $("preview").textContent = latest.draft.sections.map(s => `## ${s.title}\n${s.content}\n引用：${s.citations?.join(", ") || "（缺失）"}`).join("\n\n");
  } else {
    $("score").textContent = "— / 0.85";
    $("preview").textContent = "当前进度没有草稿快照；Trace 仅保存摘要。";
  }
}
function appendEvent(item) {
  events = TraceView.ordered([...events,item]);
  renderTimeline(); showFrame(events.length);
}
function renderTimeline() {
  $("timeline").replaceChildren();
  for (const item of events) {
  const row = document.createElement("div"); row.className = "event " + item.kind;
  const time = document.createElement("small"); time.textContent = new Date(item.ts).toLocaleTimeString("zh-CN", {hour12:false});
  const kind = document.createElement("b"); kind.textContent = item.kind;
  const details = document.createElement("span"); details.textContent = item.node_id;
  const note = document.createElement("i"); note.textContent = item.reason || `round ${item.round ?? 0}`;
  details.appendChild(note); row.append(time,kind,details); $("timeline").appendChild(row);
  }
  $("timeline").scrollTop = $("timeline").scrollHeight;
  $("seek").max = events.length;
}
function reset() {
  clearInterval(timer); events = []; history = []; lastResult = null; $("timeline").replaceChildren();
  $("downloads").replaceChildren(); $("preview").textContent = "等待运行结果…";
  $("result-note").textContent = "Trace 为只读事件；评分历史仅来自本次纵切的独立快照。";
  $("score").textContent = "— / 0.85"; $("seek").max = 0; $("replay").disabled = true;
  showFrame(0);
}
function showResult(result) {
  lastResult = result;
  $("status").textContent = result.passed ? "通过" : "已终止";
  $("score").textContent = `${result.scorecard.score.toFixed(3)} / 0.85`;
  $("message").textContent = result.reason;
  $("result-note").textContent = `${result.engine} · ${result.run_id}。${result.passed ? "最终评分通过；历史轮次见回放" : "未通过，不得作为成功交付"}。`;
  $("preview").textContent = result.results.write?.text || "该节点未产出草稿。";
  if (result.history) { history = result.history; showFrame(events.length); }
  $("downloads").replaceChildren();
  for (const name of result.download_id ? ["solution.md","evidence_chain.json","scorecard.json","trace.jsonl","delivery_artifact.json","review_history.json"] : []) {
    const link = document.createElement("a"); link.textContent = name;
    link.href = `/download?run=${encodeURIComponent(result.download_id)}&file=${encodeURIComponent(name)}`;
    link.download = name; $("downloads").appendChild(link);
  }
  $("replay").disabled = !events.length;
}
async function stream(response) {
  if (!response.ok || !response.headers.get("Content-Type")?.includes("text/event-stream")) throw new Error(`事件流请求失败（${response.status}），请检查服务/API。`);
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
  function dispatch(chunk) {
    chunk = chunk.replace(/\r\n/g,"\n");
    const kind = chunk.match(/^event:\s*(.+)$/m)?.[1];
    const lines = chunk.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart());
    if (!lines.length) return;
    const data = JSON.parse(lines.join("\n"));
    if (kind === "trace" || (data.event_id && data.kind)) appendEvent(data);
    if (kind === "review") { history.push(data); showFrame(events.length); }
    if (kind === "result") showResult(data);
    if (kind === "error") throw new Error(data.message);
  }
  try {
    while (true) {
      const {value,done} = await reader.read();
      buffer += decoder.decode(value,{stream:!done});
      let boundary;
      while ((boundary = buffer.search(/\r?\n\r?\n/)) >= 0) {
        const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)[0];
        dispatch(buffer.slice(0,boundary)); buffer = buffer.slice(boundary+separator.length);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  } finally { await reader.cancel().catch(() => {}); }
}
async function runApi(request) {
  const base = $("api-base").value.trim().replace(/\/$/, "");
  const started = await fetch(base+"/runs", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request})});
  if (!started.ok) throw new Error(`POST /runs 失败（${started.status}）`);
  const {run_id} = await started.json();
  if (!run_id) throw new Error("API 没有返回 run_id。");
  await stream(await fetch(`${base}/runs/${encodeURIComponent(run_id)}/events`, {headers:{Accept:"text/event-stream"}}));
  const response = await fetch(`${base}/runs/${encodeURIComponent(run_id)}/artifacts`);
  if (!response.ok) throw new Error(`交付物读取失败（${response.status}）`);
  const artifact = await response.json();
  if (artifact.scorecard) showResult({passed:artifact.scorecard.verdict === "pass",scorecard:artifact.scorecard,
    reason:"API 返回的实际评分卡；未收到历史评分快照时仅展示最终结果。",engine:"A API",run_id,
    results:{write:{text:JSON.stringify(artifact,null,2)}}});
  else { $("status").textContent = "事件流结束"; $("preview").textContent = JSON.stringify(artifact,null,2); }
  $("replay").disabled = !events.length;
}
$("run").onclick = async () => {
  if (!$("request").value.trim()) { $("message").textContent = "请输入产业需求。"; return; }
  reset(); busy(true); $("status").textContent = "运行中";
  try {
    if ($("mode").value === "api") await runApi($("request").value);
    else await stream(await fetch("/api/run-real", {method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({request:$("request").value})}));
    if (!lastResult && $("mode").value !== "api") throw new Error("事件流中断，未收到完成结果。");
  } catch (error) { $("message").textContent = error.message; $("status").textContent = "运行失败"; }
  finally { busy(false); }
};
function busy(value) { for (const id of ["run","import","load-demo","replay","mode","api-base"]) $(id).disabled = value; $("seek").disabled = value; $("replay").disabled = value || !events.length; }
$("seek").oninput = () => { clearInterval(timer); showFrame(Number($("seek").value)); };
$("replay").onclick = () => {
  clearInterval(timer); let index = 0; showFrame(0); $("status").textContent = "重放中";
  timer = setInterval(() => {
    showFrame(++index);
    if (index >= events.length) {
      clearInterval(timer); $("status").textContent = lastResult ? (lastResult.passed ? "通过" : "已终止") : "重放完成";
    }
  }, Number($("pace").value));
};
$("import").onchange = async (change) => {
  const file = change.target.files[0]; if (!file) return;
  try {
    if (file.size > 10 * 1024 * 1024) throw new Error("Trace 文件请控制在 10 MB 以内。");
    const loaded = (await file.text()).trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
    const ordered = TraceView.ordered(loaded);
    reset(); events = ordered; renderTimeline(); showFrame(events.length); $("replay").disabled = false;
    $("status").textContent = "已导入"; $("message").textContent = "只读重放，不触发工具调用。";
  } catch (error) { $("message").textContent = error.message; }
  change.target.value = "";
};
$("load-demo").onclick = async () => {
  try {
    const response = await fetch("/api/replay/demo");
    if (!response.ok) throw new Error("请先运行 python -m src.run --output outputs/demo。");
    const loaded = TraceView.ordered(await response.json());
    reset(); events = loaded; renderTimeline(); showFrame(events.length); $("replay").disabled = false;
    $("status").textContent = "CLI Trace 已载入"; $("message").textContent = "按时间戳只读回放；不推断缺失评分或草稿。";
  } catch (error) { $("message").textContent = error.message; }
};
$("mode").onchange = () => { $("api-base").hidden = $("mode").value !== "api"; };
$("run").disabled = true;
fetch("/api/workflow").then(response => response.json()).then(data => { workflow = data; drawGraph(); $("run").disabled = false; })
  .catch(() => { $("message").textContent = "工作流读取失败，请确认本机演示服务已启动。"; $("run").disabled = true; });
