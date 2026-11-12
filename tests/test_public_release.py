"""公开前自检脚本的测试（Owner: B）。

公开仓库基本不可逆，所以检查脚本本身必须有测试——
**不能出现"脚本说没问题，其实没真检查"的情况**。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_public_release as cpr  # noqa: E402


def test_current_repo_has_no_tracked_binaries():
    """当前仓库不应提交任何二进制（PDF/Office/图片）。"""
    assert cpr.check_tracked_binaries()[0] == []


def test_current_repo_has_no_license():
    """未授权再分发——公开仓库不应带许可证文件。"""
    assert cpr.check_license_absent()[0] == []


def test_corpus_declares_no_third_party_text():
    """17 份语料必须逐条声明 third_party_text_included=false。"""
    assert cpr.check_corpus_flags()[0] == []


def test_current_repo_has_no_personal_info():
    assert cpr.check_personal_info([])[0] == []


def test_secret_pattern_detection_works(tmp_path, monkeypatch):
    """确保检测真的会命中——否则"通过"没有意义。"""
    fake = tmp_path / "leak.md"
    fake.write_text("key: sk-" + "a" * 24, encoding="utf-8")
    monkeypatch.setattr(cpr, "ROOT", tmp_path)
    hits = cpr.check_secrets(use_history=False)[0]
    assert hits, "构造的密钥没有被检测出来"


def test_binary_suffix_list_covers_common_types():
    for suffix in (".pdf", ".pptx", ".docx", ".mp4"):
        assert suffix in cpr.BINARY_SUFFIXES
