"""黄金用例清单的结构检查（Owner: B）。

不跑纵切（跑一遍要十几秒，放进 CI 会拖慢反馈），只校验**清单本身**：
数量、id 唯一、必填字段齐全、预期写法合法。

真正的执行验证靠 `python scripts/run_golden.py`（退出码 0 才算通过），
交付前与材料提交前各跑一次。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases" / "golden.yaml"
DOC = ROOT / "docs" / "黄金用例.md"


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    assert CASES.exists(), "黄金用例清单不存在"
    data = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    return data["cases"]


def test_exactly_five_cases(cases):
    assert len(cases) == 5, f"计划是 5 个黄金用例，实际 {len(cases)} 个"


def test_ids_unique_and_ordered(cases):
    ids = [c["id"] for c in cases]
    assert ids == ["G1", "G2", "G3", "G4", "G5"], f"id 应为 G1..G5，实际 {ids}"


def test_each_case_has_scenario_and_expectation(cases):
    for case in cases:
        assert case.get("name"), f"{case.get('id')} 缺 name"
        assert case.get("scenario"), f"{case.get('id')} 缺 scenario"
        assert case.get("expect"), f"{case.get('id')} 缺 expect"


def test_outcome_values_are_legal(cases):
    legal = {"pass", "blocked"}
    for case in cases:
        outcome = case["expect"].get("outcome")
        assert outcome in legal, f"{case['id']} 的 outcome={outcome} 不在 {legal}"


def test_covers_both_paths(cases):
    """必须同时覆盖「跑通」与「按设计中止」两类路径，否则不算完整验收。"""
    outcomes = {c["expect"].get("outcome") for c in cases}
    assert outcomes == {"pass", "blocked"}, f"两条路径都要覆盖，实际只有 {outcomes}"


def test_blocked_cases_say_why(cases):
    """中止类用例必须写明触发方式——否则读者不知道它验的是什么。"""
    for case in cases:
        if case["expect"].get("outcome") == "blocked":
            assert case["scenario"], f"{case['id']} 是中止类，必须写清场景"


def test_rule_names_are_known(cases, ):
    """预期里引用的 rule_id 必须真实存在于规则验证器里。"""
    sys.path.insert(0, str(ROOT / "src"))
    import rule_checker as rc

    known = set(rc.TARGET_NODE)
    for case in cases:
        for rule in case["expect"].get("rules") or []:
            assert rule in known, f"{case['id']} 引用了未知规则 {rule}"


def test_doc_table_matches_case_count():
    """生成出来的表格必须存在且包含全部 5 个用例。"""
    assert DOC.exists(), "docs/黄金用例.md 未生成（跑 python scripts/run_golden.py --write）"
    text = DOC.read_text(encoding="utf-8")
    for case_id in ("G1", "G2", "G3", "G4", "G5"):
        assert f"| {case_id} |" in text, f"表格里缺少 {case_id}"
