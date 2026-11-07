"""C：失败样本库的契约级测试（任务单 #42，考察点 6）。

四条测试对应 #42 验收：
  ① 写入后 stats() 能统计到
  ② 同一 run_id 重复写入不炸（幂等）
  ③ by_rule 按 rule_id 聚合正确
  ④ compare() 对同一批用例给出 improvement 数字

所有库文件都建在 pytest 的 tmp_path 里，不碰仓库根目录的 feedback.db。
禁区核对：样本内容必须是 JSON 字符串，不新增任何契约。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.feedback import compare, record, stats  # noqa: E402


def _issue(rule_id: str, *, section: str = "现状痛点", severity: str = "blocker") -> dict:
    """按 scorecard.schema.json 的 issues[] 形状造一条问题（target_node 用合法节点）。"""
    return {
        "section": section,
        "reason": "测试用：故意造错",
        "suggestion": "测试用：补回引用",
        "target_node": "write",
        "rule_id": rule_id,
        "severity": severity,
    }


def _card(run_id: str, issues: list[dict], *, verdict: str = "fail", round_no: int = 0) -> dict:
    """按 scorecard 必填字段造一张评分卡，字段与 src/rule_checker.py 输出一致。"""
    return {
        "run_id": run_id,
        "round": round_no,
        "score": 0.5,
        "threshold": 0.85,
        "metrics": {
            "citation": 1.0,
            "consistency": 1.0,
            "coverage": 1.0,
            "logic": 1.0,
            "format": 1.0,
        },
        "issues": issues,
        "verdict": verdict,
    }


def test_record_then_stats(tmp_path: Path) -> None:
    """① 写入后能统计到，且库文件真的落盘。"""
    db = tmp_path / "feedback.db"
    card = _card(
        "run-1",
        [
            _issue("CITATION_MISSING"),
            _issue("NUMERIC_MISMATCH", section="技术选型", severity="warning"),
        ],
    )

    sample_id = record("run-1", {"sections": []}, card, [], db)

    assert sample_id.startswith("fb-")
    assert db.exists()
    result = stats(db)
    assert result["total"] == 2
    assert result["by_rule"]["CITATION_MISSING"] == 1
    assert result["by_severity"]["blocker"] == 1
    assert result["by_severity"]["warning"] == 1
    assert isinstance(result["resolved"], int)
    assert result["resolved"] == 0


def test_record_is_idempotent(tmp_path: Path) -> None:
    """② 同一 run_id 重复写入不抛异常、不重复计数；顺带核对 JSON 字符串存储。"""
    db = tmp_path / "feedback.db"
    card = _card("run-1", [_issue("CITATION_MISSING")])

    first = record("run-1", {"sections": []}, card, [], db)
    second = record("run-1", {"sections": []}, card, [], db)

    assert first == second
    assert stats(db)["total"] == 1

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT draft_json, scorecard_json FROM failures").fetchone()
    finally:
        conn.close()
    assert json.loads(row[0]) == {"sections": []}
    assert json.loads(row[1])["verdict"] == "fail"


def test_by_rule_aggregation(tmp_path: Path) -> None:
    """③ 按 rule_id 聚合：同类两条、异类一条，统计必须分开算。"""
    db = tmp_path / "feedback.db"
    card = _card(
        "run-agg",
        [
            _issue("CITATION_MISSING", section="现状痛点"),
            _issue("CITATION_MISSING", section="技术选型"),
            _issue("NUMERIC_MISMATCH", section="成本与ROI"),
        ],
    )

    record("run-agg", {"sections": []}, card, [], db)

    result = stats(db)
    assert result["total"] == 3
    assert result["by_rule"] == {"CITATION_MISSING": 2, "NUMERIC_MISMATCH": 1}


def test_compare_gives_improvement(tmp_path: Path) -> None:
    """④ 同一批用例复测：失败从 3 条降到 1 条，improvement 必须是正数。

    顺带验证 resolved：优化后那次运行的循环日志末尾是 pass，
    说明该轮失败已在后续轮次修好，样本应被标记为已解决。
    """
    db = tmp_path / "feedback.db"
    before_issues = [
        _issue("CITATION_MISSING", section="现状痛点"),
        _issue("NUMERIC_MISMATCH", section="技术选型"),
        _issue("MISSING_SECTION", section="风险与合规"),
    ]
    record(
        "run-before",
        {"sections": []},
        _card("run-before", before_issues, round_no=0),
        [{"round": 0, "verdict": "fail"}],
        db,
    )

    after_log = [{"round": 0, "verdict": "fail"}, {"round": 1, "verdict": "pass"}]
    record(
        "run-after",
        {"sections": []},
        _card("run-after", [_issue("CITATION_MISSING")], round_no=0),
        after_log,
        db,
    )

    result = compare(db, before="run-before", after="run-after")

    assert isinstance(result["improvement"], (int, float))
    assert result["cases"] == 3
    assert result["before_failures"] == 3
    assert result["after_failures"] == 1
    assert result["after_pass_rate"] > result["before_pass_rate"]
    assert result["improvement"] > 0
    # #42 表述纪律：样本少只报个案，不声称普遍提升
    assert "个案" in result["sample_note"]
    assert "并集" in result["case_basis"]
    assert stats(db)["resolved"] == 1
