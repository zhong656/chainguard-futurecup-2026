"""公开前自检的**负例测试**（Owner: B，A 在 #84 review 里要求）。

为什么必须有负例
----------------
只测"当前仓库是干净的"，等于只测了 happy path。
A 指出的三个假绿都是同一类问题：**检查没生效，但报告说 [PASS]**。

所以这里在临时目录里**故意造脏数据**，逐项确认检查真的会拦。

> 注意：本文件里的"脏数据"全部**运行时拼接**，不写字面量。
> 早期版本把「指导教师」标签与私钥文件头**按字面写进注释**，
> 结果扫描器把**测试文件本身**判成了泄露源——测试文件不该成为泄漏源，
> 也不该为此给扫描器开后门。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_public_release as cpr  # noqa: E402


def _sk() -> str:
    return "sk-" + "a" * 24


def _ghp() -> str:
    return "gh" + "p_" + "b" * 24


def _aws() -> str:
    return "AK" + "IA" + "C" * 16


def _pem() -> str:
    return "-----BEGIN " + "RSA PRIVATE KEY" + "-----"


def _pwd() -> str:
    return "pass" + "word = \"" + "hunter2" * 3 + "\""


def _teacher() -> str:
    return "指导" + "教师" + "：" + "张三"


def _school() -> str:
    return "学" + "校" + "：" + "某大学"


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """把 ROOT 指向临时目录，并造一个最小可用的仓库结构。"""
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "sources.yaml").write_text(
        "sources:\n"
        "  - source_id: kb:a\n"
        "    third_party_text_included: false\n",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(cpr, "ROOT", tmp_path)
    return tmp_path


# ── 密钥 ────────────────────────────────────────────────────
def test_secret_in_file_is_detected(sandbox):
    (sandbox / "config.md").write_text(f"key = {_sk()}\n", encoding="utf-8")
    assert cpr.check_secrets(use_history=False), "工作树里的 sk- 密钥没有被检出"


def test_other_pat_and_aws_key_detected(sandbox):
    (sandbox / "a.md").write_text(_ghp(), encoding="utf-8")
    (sandbox / "b.md").write_text(_aws(), encoding="utf-8")
    hits = cpr.check_secrets(use_history=False)
    assert len(hits) >= 2, f"新增的密钥模式没有生效：{hits}"


def test_private_key_block_detected(sandbox):
    (sandbox / "id.md").write_text(_pem() + "\nabc\n", encoding="utf-8")
    assert cpr.check_secrets(use_history=False), "私钥块未被检出"


def test_plaintext_password_detected(sandbox):
    (sandbox / "c.md").write_text(_pwd(), encoding="utf-8")
    assert cpr.check_secrets(use_history=False), "明文 password 未被检出"


# ── git 不可用必须阻断（A 指出的第一处假绿）─────────────────
def test_git_failure_blocks_instead_of_passing(sandbox, monkeypatch):
    """git 扫描失败时**不能**报 PASS —— 旧版在这里返回空字符串导致假绿。"""
    monkeypatch.setattr(cpr, "_git", lambda *a, **k: ("", False))
    problems = cpr.check_history_binaries()
    assert problems, "git 失败却返回空问题列表 = 假绿"
    assert any("历史未核验" in p or "失败" in p for p in problems)


def test_tracked_binaries_fail_when_git_unavailable(sandbox, monkeypatch):
    monkeypatch.setattr(cpr, "_git", lambda *a, **k: ("", False))
    assert cpr.check_tracked_binaries(), "git 不可用时无法确认工作树，必须报问题"


# ── 个人信息 ────────────────────────────────────────────────
def test_personal_label_detected(sandbox):
    (sandbox / "plan.md").write_text(_teacher() + "\n", encoding="utf-8")
    assert cpr.check_personal_info([]), "指导教师标签未被检出"


def test_school_label_detected(sandbox):
    (sandbox / "plan.md").write_text(_school() + "\n", encoding="utf-8")
    assert cpr.check_personal_info([]), "学校标签未被检出"


def test_forbid_words_detected(sandbox):
    word = "龙" + "在飞"
    (sandbox / "plan.md").write_text(f"本次由{word}提交\n", encoding="utf-8")
    assert cpr.check_personal_info([word]), "禁用词（真实队名/姓名）未被检出"


def test_forbid_word_in_prohibition_sentence_allowed(sandbox):
    """「不写某队名」这类说明句不该被判为泄露。"""
    word = "龙" + "在飞"
    (sandbox / "rule.md").write_text(f"规则：不写{word}等个人信息\n", encoding="utf-8")
    assert cpr.check_personal_info([word]) == []


# ── 其他阻断项 ──────────────────────────────────────────────
def test_license_present_fails(sandbox):
    (sandbox / "LICENSE").write_text("MIT", encoding="utf-8")
    assert cpr.check_license_absent(), "存在 LICENSE 却没有报错"


def test_corpus_flag_true_fails(sandbox):
    (sandbox / "knowledge" / "sources.yaml").write_text(
        "sources:\n  - source_id: kb:x\n    third_party_text_included: true\n",
        encoding="utf-8",
    )
    assert cpr.check_corpus_flags(), "声明含第三方原文却没有报错"


def test_corpus_flag_missing_fails(sandbox):
    (sandbox / "knowledge" / "sources.yaml").write_text(
        "sources:\n  - source_id: kb:x\n", encoding="utf-8")
    assert cpr.check_corpus_flags(), "缺少 third_party_text_included 声明却没有报错"


# ── 真实仓库仍应通过 ────────────────────────────────────────
def test_real_repo_is_clean():
    """跑真实仓库：确认改造后依然全绿（否则说明改出了假阳性）。

    `check_tracked_binaries()` 允许 `docs/images/`（本项目自己的截图）。
    """
    assert cpr.check_tracked_binaries() == []
    assert cpr.check_license_absent() == []
    assert cpr.check_corpus_flags() == []
    assert cpr.check_personal_info([]) == [], cpr.check_personal_info([])
    assert cpr.check_secrets(use_history=False) == [], cpr.check_secrets(use_history=False)
