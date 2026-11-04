#!/usr/bin/env python3
"""Mock 端到端冒烟：生成一个最小交付包，并用 delivery_artifact 契约校验它。

断言口径（不是「跑完没报错」）：
    产物通过 contracts/delivery_artifact.schema.json。

产物写到 outputs/_e2e/（已在 .gitignore 中），不污染仓库。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "_e2e"
CONTRACT = ROOT / "contracts" / "delivery_artifact.schema.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)

    solution = "# 示例方案（Mock）\n\n## 现状痛点\n模拟内容，仅用于验证交付包结构。\n"
    sol_path = OUT / "solution.md"
    sol_path.write_text(solution, encoding="utf-8")
    sol_bytes = solution.encode("utf-8")

    evidence = [
        {"source_id": "mv:doc001", "doc_id": "doc001", "text": "示例证据片段"},
    ]
    (OUT / "evidence_chain.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    scorecard = {
        "run_id": "mock-e2e-0001",
        "round": 1,
        "score": 0.86,
        "threshold": 0.85,
        "metrics": {"citation": 0.9, "consistency": 0.85, "coverage": 1.0},
        "issues": [],
        "verdict": "pass",
    }
    (OUT / "scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    trace = [
        {
            "event_id": "e1",
            "trace_id": "mock-trace-0001",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "node_id": "plan",
            "kind": "start",
            "config_version": "mock-0.1",
        },
        {
            "event_id": "e2",
            "trace_id": "mock-trace-0001",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "node_id": "plan",
            "kind": "end",
            "duration_ms": 12,
            "config_version": "mock-0.1",
        },
    ]
    (OUT / "trace.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in trace) + "\n", encoding="utf-8"
    )

    artifact = {
        "solution": {
            "path": "solution.md",
            "sha256": sha256_bytes(sol_bytes),
            "sections": ["现状痛点"],
        },
        "evidence_chain": ["mv:doc001"],
        "scorecard": scorecard,
        "trace_bundle": trace,
        "manifest": {
            "genome_version": "mock-0.1",
            "commit_sha": "0000000",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mock": True,
            "files": [
                {
                    "path": "solution.md",
                    "sha256": sha256_bytes(sol_bytes),
                    "bytes": len(sol_bytes),
                }
            ],
        },
    }
    (OUT / "delivery_artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return artifact


def main() -> int:
    try:
        import jsonschema  # noqa: F401, PLC0415
    except ImportError:
        print("[FAIL] 缺少 jsonschema：pip install jsonschema", file=sys.stderr)
        return 2

    sys.path.insert(0, str(ROOT / "scripts"))
    from _schema import load_all, validator  # noqa: PLC0415

    artifact = build()
    docs = load_all()
    schema = docs["delivery_artifact.schema.json"]
    v = validator("delivery_artifact.schema.json", docs)
    errors = sorted(v.iter_errors(artifact), key=lambda e: list(e.path))

    print(f"root: {ROOT}")
    print(f"artifact: {OUT / 'delivery_artifact.json'}")

    # 证据链解析：每个 source_id 必须在语料清单里能找到（无清单时 Skip）
    sources = ROOT / "knowledge" / "sources.yaml"
    if sources.exists():
        try:
            import yaml  # noqa: PLC0415

            declared = {
                str(s.get("source_id"))
                for s in (yaml.safe_load(sources.read_text(encoding="utf-8")) or {}).get("sources", [])
            }
            unresolved = [s for s in artifact["evidence_chain"] if s not in declared]
            if unresolved:
                print(f"✘ 证据链无法解析：{unresolved}", file=sys.stderr)
                return 1
            print(f"✔ 证据链可解析：{len(artifact['evidence_chain'])} 条")
        except Exception as exc:  # noqa: BLE001
            print(f"! 语料清单解析失败，跳过证据链检查：{exc}")

    if errors:
        for e in errors:
            print(f"[FAIL] {'/'.join(map(str, e.path)) or '<root>'}: {e.message}", file=sys.stderr)
        return 1

    print("[OK] 交付包通过 delivery_artifact 契约")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
