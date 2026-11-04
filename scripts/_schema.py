"""契约加载与 $ref 解析（完全离线，不访问网络）。

jsonschema 默认会把相对 $ref 拼到 $id 的基址上再联网取；
这里把 10 份契约按各自 $id 预注册进 Registry，解析全部在本地完成。
"""
from __future__ import annotations

import json
from pathlib import Path

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts"


def load_all() -> dict[str, dict]:
    return {
        f.name: json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(CONTRACT_DIR.glob("*.schema.json"))
    }


def build_registry(docs: dict[str, dict] | None = None):
    from referencing import Registry, Resource  # noqa: PLC0415
    from referencing.jsonschema import DRAFT202012  # noqa: PLC0415

    docs = docs if docs is not None else load_all()
    registry = Registry()
    for name, doc in docs.items():
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        # 相对 $ref（如 "source_ref.schema.json#/$defs/source_id"）按 $id 基址解析，
        # 因此必须用 $id 注册，才能命中预注册资源而不是走网络。
        if "$id" in doc:
            registry = registry.with_resource(uri=doc["$id"], resource=resource)
        registry = registry.with_resource(uri=name, resource=resource)
    return registry


def validator(name: str, docs: dict[str, dict] | None = None):
    from jsonschema import Draft202012Validator  # noqa: PLC0415

    docs = docs if docs is not None else load_all()
    return Draft202012Validator(docs[name], registry=build_registry(docs))
