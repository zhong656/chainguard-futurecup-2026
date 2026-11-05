"""A green smoke check must mean its evidence references were verified."""

from __future__ import annotations

from scripts import mock_e2e


def test_unknown_source_id_fails_smoke_check(monkeypatch) -> None:
    artifact = mock_e2e.build()
    artifact["evidence_chain"] = ["mv:unknown"]
    monkeypatch.setattr(mock_e2e, "build", lambda: artifact)
    assert mock_e2e.main() == 1
