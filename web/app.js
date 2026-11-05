"use strict";
const $ = (id) => document.getElementById(id);
const ns = "http://www.w3.org/2000/svg";
let workflow, events = [], timer, lastResult;
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
  const states = {};
  for (const item of events.slice(0,count)) {
    const status = {start:"running",end:"done",fail:"failed",abort:"failed"}[item.kind];
    if (status) states[item.node_id] = status;
  }
  for (const node of workflow.nodes) $("node-"+node.id).setAttribute("class", "node " + (states[node.id] || ""));
  $("seek").value = count;
  $("count").textContent = `${count} / ${events.length}`;
  $("round").textContent = `${events[count-1]?.round ?? 0} / 3`;
}
function appendEvent(item) {
  events.push(item);
  if (events.length === 1) $("timeline").replaceChildren();
  const row = document.createElement("div"); row.className = "event " + item.kind;
  const time = document.createElement("small"); time.textContent = new Date(item.ts).toLocaleTimeString("zh-CN", {hour12:false});
  const kind = document.createElement("b"); kind.textContent = item.kind;
  const details = document.createElement("span"); details.textContent = item.node_id;
  const note = document.createElement("i"); note.textContent = item.reason || `round ${item.round ?? 0}`;
  details.appendChild(note); row.append(time,kind,details); $("timeline").appendChild(row);
  $("timeline").scrollTop = $("timeline").scrollHeight;
  $("seek").max = events.length;
  showFrame(events.length);
}
function reset() {
  clearInterval(timer); events = []; lastResult = null; $("timeline").replaceChildren();
  $("downloads").replaceChildren(); $("preview").textContent = "等待运行结果…";
  $("score").textContent = "— / 0.85"; $("seek").max = 0; $("replay").disabled = true;
  showFrame(0);
}
function showResult(result) {
  lastResult = result;
  $("status").textContent = result.passed ? "通过" : "已终止";
  $("score").textContent = `${result.scorecard.score.toFixed(3)} / 0.85`;
  $("message").textContent = result.reason;
  $("result-note").textContent = `Mock · ${result.engine} · ${result.run_id}。${result.passed ? "演示通过" : "未通过，不得作为成功交付"}。`;
  $("preview").textContent = result.results.write?.text || "该节点未产出草稿。";
  for (const name of ["solution.md","evidence_chain.json","scorecard.json","trace.jsonl","delivery_artifact.json"]) {
    const link = document.createElement("a"); link.textContent = name;
    link.href = `/download?run=${encodeURIComponent(result.download_id)}&file=${encodeURIComponent(name)}`;
    link.download = name; $("downloads").appendChild(link);
  }
  $("replay").disabled = !events.length;
}
$("run").onclick = async () => {
  if (!$("request").value.trim()) { $("message").textContent = "请输入产业需求。"; return; }
  reset(); $("run").disabled = true; $("import").disabled = true; $("status").textContent = "运行中";
  try {
    const response = await fetch("/api/run", {method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({request:$("request").value,scenario:$("scenario").value,engine:$("engine").value})});
    if (!response.ok) throw new Error("运行请求失败，请检查本机服务。");
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const {value,done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value,{stream:true});
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0,boundary); buffer = buffer.slice(boundary+2);
        const kind = chunk.match(/^event: (.+)$/m)?.[1];
        const data = JSON.parse(chunk.match(/^data: (.+)$/m)[1]);
        if (kind === "trace") appendEvent(data);
        if (kind === "result") showResult(data);
        if (kind === "error") throw new Error(data.message);
      }
    }
  } catch (error) { $("message").textContent = error.message; $("status").textContent = "运行失败"; }
  finally { $("run").disabled = false; $("import").disabled = false; }
};
$("seek").oninput = () => { clearInterval(timer); showFrame(Number($("seek").value)); };
$("replay").onclick = () => {
  clearInterval(timer); let index = 0; showFrame(0); $("status").textContent = "重放中";
  timer = setInterval(() => {
    showFrame(++index);
    if (index >= events.length) {
      clearInterval(timer); $("status").textContent = lastResult ? (lastResult.passed ? "通过" : "已终止") : "重放完成";
    }
  }, 180);
};
$("import").onchange = async (change) => {
  const file = change.target.files[0]; if (!file) return;
  try {
    if (file.size > 10 * 1024 * 1024) throw new Error("Trace 文件请控制在 10 MB 以内。");
    const loaded = (await file.text()).trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
    const ids = new Set(), kinds = new Set(["start","end","fail","retry","degrade","revise","abort","checkpoint"]);
    for (const item of loaded) {
      if (!item.event_id || !item.trace_id || !item.node_id || !kinds.has(item.kind) || Number.isNaN(Date.parse(item.ts))
          || ids.has(item.event_id) || item.trace_id !== loaded[0].trace_id) throw new Error("Trace 格式无效或混入重复/不同运行事件。");
      ids.add(item.event_id);
    }
    if (!loaded.length) throw new Error("Trace 为空。");
    reset(); loaded.forEach(appendEvent); $("replay").disabled = false;
    $("status").textContent = "已导入"; $("message").textContent = "只读重放，不触发工具调用。";
  } catch (error) { $("message").textContent = error.message; }
  change.target.value = "";
};
$("run").disabled = true;
fetch("/api/workflow").then(response => response.json()).then(data => { workflow = data; drawGraph(); $("run").disabled = false; })
  .catch(() => { $("message").textContent = "工作流读取失败，请确认本机演示服务已启动。"; $("run").disabled = true; });
