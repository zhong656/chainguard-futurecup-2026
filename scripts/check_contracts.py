#!/usr/bin/env python3
"""一致性检查：契约 / 配置 / 归属 / 依赖锁定 / 语料 ID。

原则：任一项 ERROR 即非零退出。WARN 不阻断，但会写进 docs/consistency-report.md。

用法：
    python scripts/check_contracts.py          # 检查并刷新报告
    python scripts/check_contracts.py --quiet  # 只输出结论行
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
REPORT = ROOT / "docs" / "consistency-report.md"

ERROR, WARN, OK = "ERROR", "WARN", "OK"
results: list[dict] = []

# 运行产物 / 依赖目录：不需要在 owners.yaml 登记归属
IGNORED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "outputs",
    "chroma_db",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def add(level: str, name: str, detail: str, owner: str = "-") -> None:
    results.append({"level": level, "name": name, "detail": detail, "owner": owner})


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_refs(node, path=""):
    """递归收集 $ref 值及其位置。"""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield path, v
            else:
                yield from iter_refs(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_refs(v, f"{path}/{i}")


def resolve_pointer(doc, pointer: str):
    """解析 JSON Pointer（如 /$defs/source_id）。返回 (ok, value)。"""
    if pointer in ("", None):
        return True, doc
    if not pointer.startswith("/"):
        return False, None
    cur = doc
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and token in cur:
            cur = cur[token]
        elif isinstance(cur, list) and token.lstrip("-").isdigit():
            idx = int(token)
            if idx >= len(cur):
                return False, None
            cur = cur[idx]
        else:
            return False, None
    return True, cur


def check_contracts_parse() -> dict:
    """1) 所有契约可解析，且声明 $schema；同时登记每份的 Owner。"""
    docs, owners = {}, {}
    files = sorted(CONTRACTS.glob("*.schema.json"))
    if not files:
        add(ERROR, "契约存在性", "contracts/ 下没有任何 *.schema.json", "A")
        return {}
    for f in files:
        try:
            doc = load_json(f)
            docs[f.name] = doc
        except Exception as exc:  # noqa: BLE001
            add(ERROR, f"契约解析 {f.name}", str(exc), "A")
            continue
        if "$schema" not in doc:
            add(ERROR, f"契约元信息 {f.name}", "缺少 $schema", "A")
        desc = str(doc.get("description", ""))
        m = re.search(r"Owner:\s*([ABCD])", desc)
        owners[f.name] = m.group(1) if m else "-"
        if not m:
            add(WARN, f"契约 Owner {f.name}", "description 里未标注 Owner: A/B/C/D", "-")
    add(OK, "契约解析", f"{len(docs)} 份可解析")
    return {"docs": docs, "owners": owners}


def check_refs(ctx: dict) -> None:
    """2) 所有 $ref 目标存在（文件 + 片段）。"""
    docs = ctx.get("docs", {})
    bad = 0
    for name, doc in docs.items():
        for where, ref in iter_refs(doc):
            file_part, _, frag = ref.partition("#")
            target_name = file_part or name
            target = CONTRACTS / target_name
            if file_part and not target.exists():
                add(ERROR, f"$ref 目标 {name}", f"{where} → {ref}（文件不存在）", "A")
                bad += 1
                continue
            tdoc = docs.get(target_name)
            if tdoc is None:
                try:
                    tdoc = load_json(target)
                except Exception:  # noqa: BLE001
                    add(ERROR, f"$ref 目标 {name}", f"{where} → {ref}（目标无法解析）", "A")
                    bad += 1
                    continue
            ok, _ = resolve_pointer(tdoc, frag)
            if not ok:
                add(ERROR, f"$ref 片段 {name}", f"{where} → {ref}（片段不存在）", "A")
                bad += 1
    if bad == 0:
        add(OK, "$ref 可解析", "全部引用指向真实存在的文件与片段")


def check_configs(ctx: dict) -> None:
    """3) agents/*.yaml 与 workflows/*.yaml 符合契约；空文件仅告警。"""
    try:
        import yaml  # noqa: PLC0415
        from _schema import validator as make_validator  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        add(ERROR, "依赖缺失", f"需要 pyyaml + jsonschema：{exc}", "A")
        return

    pairs = [
        ("agents/*.yaml", "agent_spec.schema.json", "C"),
        ("workflows/*.yaml", "workflow.schema.json", "D"),
    ]
    for pattern, schema_name, owner in pairs:
        if schema_name not in ctx["docs"]:
            add(ERROR, f"Schema 缺失 {schema_name}", "无法校验配置", "A")
            continue
        validator = make_validator(schema_name, ctx["docs"])
        files = sorted(ROOT.glob(pattern))
        empty, passed = [], 0
        for f in files:
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                add(ERROR, f"YAML 解析 {f.relative_to(ROOT)}", str(exc)[:200], owner)
                continue
            if data is None:
                empty.append(f.relative_to(ROOT).as_posix())
                continue
            errs = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            if errs:
                first = errs[0]
                add(
                    ERROR,
                    f"配置校验 {f.relative_to(ROOT)}",
                    f"{len(errs)} 处不符合 {schema_name}；首个：{'/'.join(map(str, first.path)) or '<root>'} {first.message[:120]}",
                    owner,
                )
            else:
                passed += 1
        if passed:
            add(OK, f"配置校验 {pattern}", f"{passed} 份通过")
        if empty:
            add(WARN, f"配置待填 {pattern}", f"{len(empty)} 份仍是注释占位：{', '.join(empty)}", owner)


def check_examples(ctx: dict) -> None:
    """8) 正反例：good 必须通过、bad 必须被拒（反例不过 = schema 太松）。"""
    try:
        from _schema import validator as make_validator  # noqa: PLC0415
    except ImportError:
        return

    ex_dir = CONTRACTS / "examples"
    if not ex_dir.exists():
        add(WARN, "正反例", "contracts/examples/ 尚未建立", "A")
        return

    pairs: dict[str, dict[str, Path]] = {}
    for f in sorted(ex_dir.glob("*.json")):
        stem = f.name[: -len(".json")]
        if stem.endswith(".good"):
            pairs.setdefault(stem[: -len(".good")], {})["good"] = f
        elif stem.endswith(".bad"):
            pairs.setdefault(stem[: -len(".bad")], {})["bad"] = f
        else:
            add(WARN, f"正反例命名 {f.name}", "应以 .good.json / .bad.json 结尾", "A")

    ok_count = 0
    for name, pair in sorted(pairs.items()):
        schema_name = f"{name}.schema.json"
        if schema_name not in ctx["docs"]:
            add(ERROR, f"正反例 {name}", f"找不到契约 {schema_name}", "A")
            continue
        v = make_validator(schema_name, ctx["docs"])
        good, bad = pair.get("good"), pair.get("bad")
        if good is None or bad is None:
            add(WARN, f"正反例 {name}", f"缺少 {'.good' if good is None else '.bad'} 样例", "-")
            continue

        passed = True
        for kind, path in (("good", good), ("bad", bad)):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                add(ERROR, f"正反例 {name}.{kind}", f"JSON 解析失败：{exc}", "-")
                passed = False
                continue
            errs = list(v.iter_errors(data))
            if kind == "good" and errs:
                e = errs[0]
                where = "/".join(map(str, e.path)) or "<root>"
                add(ERROR, f"正例未通过 {name}", f"{where}: {e.message[:120]}", "-")
                passed = False
            elif kind == "bad" and not errs:
                add(ERROR, f"反例未被拒 {name}", "这份错误样例居然通过 → schema 过松", "-")
                passed = False
        if passed:
            ok_count += 1

    if ok_count:
        add(OK, "正反例", f"{ok_count} 组全部符合预期（正例通过、反例被拒）")


def check_owners() -> None:
    """4) docs/owners.yaml 覆盖全部一级目录。"""
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        add(ERROR, "依赖缺失", "需要 pyyaml", "A")
        return
    path = ROOT / "docs" / "owners.yaml"
    if not path.exists():
        add(ERROR, "归属表", "缺少 docs/owners.yaml", "A")
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    declared = set((data.get("directories") or {}).keys())
    actual = {
        p.name
        for p in ROOT.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in IGNORED_DIRS
    }
    missing = sorted(actual - declared)
    if missing:
        add(ERROR, "归属覆盖", f"以下一级目录未在 owners.yaml 登记：{', '.join(missing)}", "A")
    else:
        add(OK, "归属覆盖", f"{len(actual)} 个一级目录均已登记")


def check_requirements() -> None:
    """5) requirements.txt 依赖是否锁定版本（冻结前 WARN，冻结后应改 ERROR）。"""
    path = ROOT / "requirements.txt"
    if not path.exists():
        add(WARN, "依赖清单", "缺少 requirements.txt", "A")
        return
    deps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            deps.append(line)
    unpinned = [d for d in deps if "==" not in d]
    if unpinned:
        add(WARN, "依赖锁定", f"{len(unpinned)}/{len(deps)} 个依赖未锁版本（11/07 冻结前必须回填）", "A")
    else:
        add(OK, "依赖锁定", f"{len(deps)} 个依赖全部锁定")


def check_source_ids() -> None:
    """6) 语料声明中的 source_id 必须匹配 ^[a-z]+:[A-Za-z0-9_-]+$。"""
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return
    path = ROOT / "knowledge" / "sources.yaml"
    if not path.exists():
        add(WARN, "source_id", "knowledge/sources.yaml 尚未建立，跳过", "B")
        return
    pattern = re.compile(r"^[a-z]+:[A-Za-z0-9_-]+$")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    bad = [s.get("source_id", "<无>") for s in sources if not pattern.match(str(s.get("source_id", "")))]
    if bad:
        add(ERROR, "source_id 规范", f"{len(bad)} 个不合规：{', '.join(map(str, bad[:5]))}", "B")
    else:
        add(OK, "source_id 规范", f"{len(sources)} 条声明全部合规")


def write_report() -> int:
    errors = [r for r in results if r["level"] == ERROR]
    warns = [r for r in results if r["level"] == WARN]
    lines = [
        "# 一致性检查报告",
        "",
        "> 本文件由 `scripts/check_contracts.py` 自动生成，**禁止手改**。",
        "> 有异议请改脚本或改源文件后重跑 `make check`。",
        "",
        f"- 检查项：{len(results)}",
        f"- 失败：{len(errors)}",
        f"- 警告：{len(warns)}",
        f"- 结论：{'FAIL 未通过' if errors else 'PASS 通过'}",
        "",
        "| 判定 | 检查项 | 详情 | 归属 |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        detail = str(r["detail"]).replace("|", "\\|")
        lines.append(f"| {r['level']} | {r['name']} | {detail} | {r['owner']} |")
    lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return 1 if errors else 0


def main() -> int:
    quiet = "--quiet" in sys.argv
    ctx = check_contracts_parse()
    if ctx:
        check_refs(ctx)
        check_configs(ctx)
        check_examples(ctx)
    check_owners()
    check_requirements()
    check_source_ids()
    code = write_report()

    for r in results:
        tag = {"OK": "[OK]", "WARN": "[WARN]", "ERROR": "[FAIL]"}[r["level"]]
        if r["level"] != OK or not quiet:
            print(f"{tag} {r['name']}: {r['detail']}")
    errors = sum(1 for r in results if r["level"] == ERROR)
    print(f"\ncheck_contracts: {len(results)} 项检查，{errors} 项失败 → 报告已写入 {REPORT.relative_to(ROOT)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
