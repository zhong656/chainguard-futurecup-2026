"""C：L1 规则验证器的契约级测试。

验收口径（configs/verifier.yaml）：故意造错（假引用 / 数值不一致 / 缺章节）
必须能被检出；输出必须能直接被 D 的 LoopController 消费，不需要适配层。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scripts._schema import validator  # noqa: E402
from src.dag_compiler import compile_workflow  # noqa: E402
from src.loop_controller import LoopController  # noqa: E402
from src.rule_checker import check, required_sections, EvidenceIndex  # noqa: E402

REQUIRED = required_sections()


def good_draft(**overrides) -> dict:
    """六章齐全、引用全部可回溯、正文不含数字的合格稿。"""
    draft = {
        "run_id": "run-rule-001",
        "round": 0,
        "sections": [
            {"title": name, "content": "本段结论均有证据支撑。", "citations": ["mv:doc001"]}
            for name in REQUIRED
        ],
    }
    draft.update(overrides)
    return draft


@pytest.fixture
def evidence() -> dict:
    # 只用 id → 原文 的轻量形态，避免测试依赖占位语料的具体内容。
    return {"mv:doc001": "产线质检依赖人工复检，漏检率与过杀率同时偏高。"}


def rule_ids(card: dict) -> list[str]:
    return [issue["rule_id"] for issue in card["issues"]]


# ---------------- 契约边界：缺引用靠规则报，不靠 Schema 拦 ---------------- #

def test_draft_schema_allows_missing_citations():
    """B 的硬要求：坏稿样本必须造得出来，Schema 不能拦空引用。"""
    validator("draft.schema.json").validate(
        {"run_id": "r", "sections": [{"title": "现状痛点", "content": "无引用"}]}
    )


def test_bad_example_is_shape_valid_but_quality_bad():
    """contracts/examples/draft.bad.json 缺 content：Schema 拒，规则报 SCHEMA_INVALID。"""
    bad = json.loads((ROOT / "contracts/examples/draft.bad.json").read_text(encoding="utf-8"))
    errors = list(validator("draft.schema.json").iter_errors(bad))
    assert errors, "bad 样例必须被 Draft Schema 拒绝"
    card = check(bad, {"mv:doc001": "示例证据"})
    assert card["verdict"] == "fail"
    assert "SCHEMA_INVALID" in rule_ids(card)
    assert any(i["severity"] == "blocker" for i in card["issues"])


# ---------------- 四条规则 ---------------- #

def test_good_draft_passes_and_matches_scorecard_schema(evidence):
    card = check(good_draft(), evidence)
    validator("scorecard.schema.json").validate(card)
    assert card["verdict"] == "pass"
    assert card["score"] == 1.0
    assert card["issues"] == []
    assert set(card["metrics"]) == {"citation", "consistency", "coverage", "logic", "format"}


def test_missing_citation_reported_by_rule(evidence):
    draft = good_draft()
    draft["sections"][0].pop("citations")
    card = check(draft, evidence)
    assert "CITATION_MISSING" in rule_ids(card)
    assert card["verdict"] == "fail"


def test_empty_citation_reported_by_rule(evidence):
    draft = good_draft()
    draft["sections"][0]["citations"] = []
    card = check(draft, evidence)
    assert "CITATION_MISSING" in rule_ids(card)


def test_unknown_source_id_is_blocker(evidence):
    draft = good_draft()
    draft["sections"][0]["citations"] = ["mv:not_exist"]
    card = check(draft, evidence)
    assert "CITATION_UNKNOWN" in rule_ids(card)
    assert card["verdict"] == "fail"
    validator("scorecard.schema.json").validate(card)


def test_unparsable_source_id_does_not_break_scorecard_schema(evidence):
    """假引用不合法时不能塞进 issues[].source_id（那里有 $ref 正则）。"""
    draft = good_draft()
    draft["sections"][0]["citations"] = ["这不是合法 id"]
    card = check(draft, evidence)
    validator("scorecard.schema.json").validate(card)
    assert "CITATION_UNKNOWN" in rule_ids(card)
    assert "source_id" not in card["issues"][0]


def test_numeric_mismatch_detected():
    evidence = {"mv:doc002": "相机与镜头占比 25%–35%，单工位投入 8–15 万元。"}
    draft = good_draft()
    draft["sections"][0]["citations"] = ["mv:doc002"]
    draft["sections"][0]["content"] = "相机占比 25%–35%，但单工位投入是 99 万元。"
    card = check(draft, evidence)
    assert "NUMERIC_MISMATCH" in rule_ids(card)
    issue = next(i for i in card["issues"] if i["rule_id"] == "NUMERIC_MISMATCH")
    assert issue["target_node"] == "fanout"
    assert "99" in issue["reason"]


def test_numeric_check_skipped_when_evidence_has_no_number(evidence):
    """占位语料不含数字时不能误报，否则所有含数字的稿都会红。"""
    draft = good_draft()
    draft["sections"][0]["content"] = "按 2026 年口径测算。"
    card = check(draft, evidence)
    assert "NUMERIC_MISMATCH" not in rule_ids(card)


def test_missing_sections_detected(evidence):
    draft = good_draft(sections=[good_draft()["sections"][0]])
    card = check(draft, evidence)
    missing = [i for i in card["issues"] if i["rule_id"] == "MISSING_SECTION"]
    assert len(missing) == len(REQUIRED) - 1
    assert card["metrics"]["coverage"] < 0.60
    assert card["verdict"] == "fail"


# ---------------- 一票否决与下游联调 ---------------- #

def test_veto_blocks_high_score_with_blocker(evidence):
    """加权分再高，只要存在 blocker 就必须 fail。"""
    draft = good_draft()
    draft["sections"][0]["citations"] = []
    card = check(draft, evidence)
    assert card["score"] > 0.85
    assert min(card["metrics"].values()) >= 0.60
    assert card["verdict"] == "fail", "一票否决未生效"


def test_output_feeds_loop_controller(evidence):
    """评分卡不经过任何适配就能被 D 的 LoopController 接受并触发定向回退。"""
    graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
    policy = yaml.safe_load((ROOT / "configs/verifier.yaml").read_text(encoding="utf-8"))["scorecard"]
    controller = LoopController(graph, policy)
    draft = good_draft()
    draft["sections"][0]["citations"] = []
    decision = controller.decide(check(draft, evidence))
    assert decision.action == "revise"
    assert "write" in decision.targets


def test_evidence_accepts_chain_and_evidence_pool():
    """evidence 既能收 evidence_chain（只有 id），也能收 B 的 EvidencePool。"""
    chain = ["mv:doc001", "mv:doc002"]
    card = check(good_draft(), chain)
    assert "CITATION_UNKNOWN" not in rule_ids(card)
    assert not EvidenceIndex(chain).has("mv:not_exist")

    from src.evidence import EvidencePool  # noqa: PLC0415

    pool = EvidencePool()
    pool.add_from_retrieval(
        {"query": "质检", "mode": "hybrid", "items": [{"source_id": "mv:doc001", "score": 0.9}]}
    )
    card = check(good_draft(), pool)
    validator("scorecard.schema.json").validate(card)
    assert "CITATION_UNKNOWN" not in rule_ids(card)
