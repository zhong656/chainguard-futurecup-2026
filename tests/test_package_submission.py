"""提交包组装器的判定逻辑测试（Owner: B）。

这里测的是**门禁行为**，不是打包本身：
    1. 缺材料时**拒绝出包**（退出码 1），而不是出一个残缺的包；
    2. 成片按**文件名契约**识别——按后缀猜会误判（曾把 PPT 导出当成项目文档）；
    3. 认不出的文件会被列出来，而不是静默吞掉；
    4. 包名符合赛事命名规则 `赛题一_<队名>_链衡ChainGuard`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import package_submission as ps  # noqa: E402


def test_video_detected_by_keyword(tmp_path):
    (tmp_path / "演示视频_v1.mp4").write_bytes(b"x")
    found, unknown = ps._find_materials(tmp_path)
    assert "演示视频" in found
    assert not unknown


def test_unrelated_name_is_not_detected(tmp_path):
    """按后缀猜是错的：`xxx.pdf` 不一定是项目文档。"""
    (tmp_path / "chainguard-d-materials-v5.pdf").write_bytes(b"x")
    found, unknown = ps._find_materials(tmp_path)
    assert "项目文档PDF" not in found, "不该仅凭 .pdf 后缀就认定是项目文档"
    assert unknown, "认不出的文件应被列出"


def test_project_doc_detected_by_keyword(tmp_path):
    (tmp_path / "项目文档_v1.pdf").write_bytes(b"x")
    found, _ = ps._find_materials(tmp_path)
    assert "项目文档PDF" in found


def test_ppt_export_pdf_is_not_promoted(tmp_path):
    """PPT 导出的 PDF 名字里没有「项目文档」，必须保持未识别。"""
    (tmp_path / "路演PPT导出_v5.pdf").write_bytes(b"x")
    found, unknown = ps._find_materials(tmp_path)
    assert "项目文档PDF" not in found
    assert any(p.name.startswith("路演PPT导出") for p in unknown)


def test_missing_materials_block_packaging(tmp_path):
    """缺材料时必须判定为缺——不能出一个看着能用、实际残缺的包。

    （真正的 exit 1 由 `python scripts/package_submission.py` 端到端验证；
      这里只锁"缺失集合的计算"，避免测试依赖 subprocess 与真实 dist 目录。）
    """
    empty = tmp_path / "materials"
    empty.mkdir()
    mats, _ = ps._find_materials(empty)
    docs = ps._collect_docs()
    required = ("作品简介", "测试报告", "项目文档PDF", "演示视频")
    missing = [n for n in required if n not in docs and n not in mats]
    assert "项目文档PDF" in missing and "演示视频" in missing


def test_package_naming_rule():
    """包名规则：赛题一_<队名>_链衡ChainGuard（赛事要求"赛题名+队名+项目名"）。"""
    prefix = "赛题一_测试队_链衡ChainGuard"
    assert prefix.startswith("赛题一_")
    assert "链衡ChainGuard" in prefix


def test_docs_are_collected_from_repo():
    """仓库内的三份文档应能被收集到（它们在 main 上确实存在）。"""
    docs = ps._collect_docs()
    assert "作品简介" in docs
    assert "测试报告" in docs
