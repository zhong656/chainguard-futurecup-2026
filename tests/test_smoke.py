"""冒烟测试：保证 pytest 非空（空集合会让 pytest 以退出码 5 失败）。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repo_skeleton_exists() -> None:
    """仓库骨架的关键文件必须存在。"""
    for rel in ("README.md", "SECURITY.md", "CONTRIBUTING.md", "Makefile", "docs/owners.yaml"):
        assert (ROOT / rel).exists(), f"缺少 {rel}"


def test_contracts_present() -> None:
    """11 份契约必须齐全。"""
    contracts = sorted(p.name for p in (ROOT / "contracts").glob("*.schema.json"))
    assert len(contracts) == 11, f"契约数量应为 11，实际 {len(contracts)}：{contracts}"
    assert "delivery_artifact.schema.json" in contracts
    assert "draft.schema.json" in contracts


def test_no_secret_files_tracked() -> None:
    """仓库内不得出现明显的凭据文件。"""
    forbidden = [".env", "id_rsa", "id_ed25519"]
    for name in forbidden:
        assert not list(ROOT.rglob(name)), f"发现疑似凭据文件：{name}"
