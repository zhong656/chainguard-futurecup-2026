"""统计作品简介 A 版字数（提交表有 300 字硬限）。

口径：只统计 A 版正文（`## A 版` 到下一个 `---` 之间），
去掉 Markdown 标记与空白，按**字符**计（中文按 1 字）。
不把标题、说明、B 版算进去——那些不进提交表。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "作品简介.md"
LIMIT = 300


def extract_a(text: str) -> str:
    match = re.search(r"^## A 版.*?$\n(.*?)^---", text, flags=re.S | re.M)
    if not match:
        raise SystemExit("找不到 A 版段落（需要以 `## A 版` 开头、`---` 结束）")
    return match.group(1)


def count_chars(body: str) -> int:
    # 去掉 Markdown 记号与空白；保留中英文与数字
    cleaned = re.sub(r"[*_`>#\-\[\]()]", "", body)
    cleaned = re.sub(r"\s+", "", cleaned)
    return len(cleaned)


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    body = extract_a(text)
    n = count_chars(body)
    verdict = "OK" if n <= LIMIT else "超限"
    print(f"A 版字数：{n} / {LIMIT}  →  {verdict}")
    if n > LIMIT:
        print(f"需要删掉 {n - LIMIT} 字")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
