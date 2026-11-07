"""C：失败样本库与前后对比（任务单 #42，考察点 6「结果验证与反馈优化」）。

证据链：L1 规则命中 -> 样本入库 -> 按类型统计 -> 改提示词/阈值 ->
        同一用例集复测 -> 前后对比。

边界（#42 禁区）：
  * 不修改 contracts/，不新增契约；draft / scorecard / loop_log 一律以
    JSON 字符串存进 TEXT 列，外部读库不需要本模块以外的任何 schema。
  * 默认库文件 feedback.db 已被 .gitignore 忽略，不进版本库。
  * 表述纪律：样本少就只报个案。compare() 会如实写出样本量与统计口径，
    不声称「优化后普遍提升」。

数据表以 #42 的最小表为基础，另加两列（仅本模块内部使用，不进契约）：
  resolved       同一运行的后续轮次已跑通，该失败样本视为已解决
  loop_log_json  保留循环日志原文，便于复盘「第几轮修好」

接口：record() / stats() / compare()，签名与 #42 任务单一致。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path("feedback.db")

_UNKNOWN = "_UNKNOWN_"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS failures (
  id TEXT PRIMARY KEY, run_id TEXT, round INTEGER,
  rule_id TEXT, severity TEXT, section TEXT, target_node TEXT,
  draft_json TEXT, scorecard_json TEXT, created_at TEXT,
  resolved INTEGER NOT NULL DEFAULT 0,
  loop_log_json TEXT
);
"""


def _dumps(value: object) -> str:
    """把任意样本内容压成 JSON 字符串；遇到非标准类型退化为字符串，不丢数据。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _connect(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_SQL)
    conn.commit()
    return conn


def _batch_id(run_id: str) -> str:
    return "fb-" + hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:16]


def _sample_id(run_id: str, issue: dict, round_no: int, pos: int) -> str:
    """同一 (run_id, round, rule_id, section, 序号) 永远得到同一个 id。

    这是幂等的关键：重复调用 record() 时 INSERT OR IGNORE 会直接跳过，
    既不会抛主键冲突，也不会把统计数字翻倍。
    """
    key = "|".join(
        (
            str(run_id),
            str(round_no),
            str(issue.get("rule_id") or ""),
            str(issue.get("section") or ""),
            str(pos),
        )
    )
    return "fb-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _round_of(scorecard: dict, loop_log: list[dict]) -> int:
    """失败发生在评分卡自己标明的那一轮；没有就退回日志里第一个未通过的轮次。"""
    candidates = [scorecard.get("round")]
    for item in loop_log or []:
        if isinstance(item, dict) and item.get("verdict") != "pass":
            candidates.append(item.get("round"))
    for value in candidates:
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def _final_pass(scorecard: dict, loop_log: list[dict]) -> bool:
    """循环日志最后一轮说了算；日志为空时用评分卡的 verdict 兜底。

    对应纵切 rounds.json 的形状：[{round: 0, verdict: "fail"},
    {round: 1, verdict: "pass"}] —— 末尾 pass 即本轮失败已被修复。
    """
    for item in reversed(loop_log or []):
        if isinstance(item, dict) and "verdict" in item:
            return item["verdict"] == "pass"
    return scorecard.get("verdict") == "pass"


def record(
    run_id: str,
    draft: dict,
    scorecard: dict,
    loop_log: list[dict],
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """写入一次运行的失败样本，返回样本 id。

    一条 issue 一行；draft / scorecard / loop_log 完整保留在 JSON 列里。
    同一 run_id 重复调用是幂等的（INSERT OR IGNORE），不会抛异常也不会重复计数。
    评分卡 verdict=pass 且没有 issues 时不产生失败样本行，返回批次 id。
    """
    issues = [i for i in (scorecard.get("issues") or []) if isinstance(i, dict)]
    round_no = _round_of(scorecard, loop_log)
    resolved = 1 if _final_pass(scorecard, loop_log) else 0
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    draft_json = _dumps(draft)
    scorecard_json = _dumps(scorecard)
    loop_log_json = _dumps(loop_log or [])
    batch_id = _batch_id(run_id)

    conn = _connect(db_path)
    written: list[str] = []
    try:
        with conn:
            for pos, issue in enumerate(issues):
                sample_id = _sample_id(run_id, issue, round_no, pos)
                written.append(sample_id)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO failures
                      (id, run_id, round, rule_id, severity, section,
                       target_node, draft_json, scorecard_json, created_at,
                       resolved, loop_log_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sample_id,
                        str(run_id),
                        round_no,
                        str(issue.get("rule_id") or _UNKNOWN),
                        str(issue.get("severity") or _UNKNOWN),
                        str(issue.get("section") or _UNKNOWN),
                        str(issue.get("target_node") or _UNKNOWN),
                        draft_json,
                        scorecard_json,
                        created_at,
                        resolved,
                        loop_log_json,
                    ),
                )
            # 最终跑通时，把该 run_id 下的历史样本一并标记为已解决。
            # 重复写入时这一步只会把 1 再写一次，仍然幂等。
            if resolved:
                conn.execute(
                    "UPDATE failures SET resolved = 1 WHERE run_id = ?", (str(run_id),)
                )
    finally:
        conn.close()
    return written[0] if written else batch_id


def stats(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """按规则与严重度聚合失败样本。

    返回 {'by_rule': {...}, 'by_severity': {...}, 'total': n, 'resolved': n}。
    resolved 只统计「同一次运行后续轮次已跑通」的样本，不代表线上已修复。
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT rule_id, severity, resolved FROM failures").fetchall()
    finally:
        conn.close()

    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    resolved = 0
    for row in rows:
        rule = row["rule_id"] or _UNKNOWN
        severity = row["severity"] or _UNKNOWN
        by_rule[rule] = by_rule.get(rule, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
        resolved += int(row["resolved"] or 0)
    return {
        "by_rule": by_rule,
        "by_severity": by_severity,
        "total": len(rows),
        "resolved": resolved,
    }


def compare(db_path: Path = DEFAULT_DB_PATH, *, before: str, after: str) -> dict:
    """同一批用例在两次策略下的通过率对比。

    before / after 是两次运行的 run_id（策略以 run_id 区分）。
    用例定义为 (section, rule_id)；分母取两次失败样本的并集，某次策略下
    没有对应失败样本即视为该用例通过。

    诚实口径：两次都通过的用例库里根本没有，所以这个通过率分母只覆盖
    「至少失败过一次」的用例。返回 case_basis / sample_note 把限制写明，
    样本量小只作个案，不声称优化后普遍提升（#42 表述纪律）。
    """
    conn = _connect(db_path)
    try:

        def failures_of(tag: str) -> set[tuple[str, str]]:
            rows = conn.execute(
                "SELECT section, rule_id FROM failures WHERE run_id = ?", (tag,)
            ).fetchall()
            return {(row["section"] or "", row["rule_id"] or "") for row in rows}

        before_set = failures_of(before)
        after_set = failures_of(after)
    finally:
        conn.close()

    cases = before_set | after_set
    n = len(cases)
    # 没有任何失败样本时，按「这一批用例都通过」处理，分母为 0 不报数。
    before_rate = (n - len(before_set)) / n if n else 1.0
    after_rate = (n - len(after_set)) / n if n else 1.0
    return {
        "before": before,
        "after": after,
        "cases": n,
        "before_failures": len(before_set),
        "after_failures": len(after_set),
        "before_pass_rate": round(before_rate, 3),
        "after_pass_rate": round(after_rate, 3),
        "improvement": round(after_rate - before_rate, 3),
        "case_basis": "分母为两次失败样本的并集；两次均通过的用例未入库，不在统计范围",
        "sample_note": "样本量 %d，仅个案对比，不代表优化后普遍提升" % n,
    }
