/* 浏览器和 Node 验收共用的纯函数；事件保持原样，不合成节点状态事件。 */
(function (root) {
  "use strict";
  const states = {start:"running",end:"done",fail:"failed",abort:"failed",
    retry:"retrying",degrade:"degraded",revise:"revising"};
  function time(item) {
    const fraction = item.ts.match(/\.(\d+)/)?.[1] || "";
    return BigInt(Date.parse(item.ts.replace(/\.\d+/, ""))) * 1000000000n +
      BigInt(fraction.padEnd(9,"0").slice(0,9));
  }
  function ordered(items) {
    const ids = new Set(), kinds = new Set([...Object.keys(states),"checkpoint"]);
    if (!items.length) throw new Error("Trace 为空。");
    for (const item of items) {
      if (!["event_id","trace_id","node_id","ts"].every(key => typeof item[key] === "string" && item[key]) ||
          !kinds.has(item.kind) || Number.isNaN(Date.parse(item.ts)) ||
          !/^\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)$/.test(item.ts) ||
          ids.has(item.event_id) || item.trace_id !== items[0].trace_id || item.run_id !== items[0].run_id ||
          (item.round !== undefined && (!Number.isInteger(item.round) || item.round < 0 || item.round > 3))) {
        throw new Error("Trace 格式无效或混入重复/不同运行事件。");
      }
      ids.add(item.event_id);
    }
    return [...items].sort((a,b) => time(a) < time(b) ? -1 : time(a) > time(b) ? 1 : 0);
  }
  function reduce(items) {
    const nodes = {};
    for (const item of items) if (states[item.kind]) nodes[item.node_id] = states[item.kind];
    return nodes;
  }
  root.TraceView = {ordered,reduce};
  if (typeof module !== "undefined") module.exports = root.TraceView;
})(globalThis);
