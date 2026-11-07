"""文档解析 —— 把 PDF / DOCX / Markdown / 纯文本统一成「页 + 文本」（Owner: B）。

为什么解析层要保留「页」
--------------------
证据链契约 `source_ref` 里有 `page` 字段，要求"这条引用来自第几页"。
如果解析只返回一整段字符串，下游就只剩 `char_range` 可用，
评审追问"这句在第几页"时答不上来。所以本模块的产物始终是：

    ParsedDoc(pages=[PageText(no=1, text="..."), ...])

Markdown / 纯文本没有物理页，用 `no=1` 并标记 `synthetic_page=True` —— 诚实标注，
不要假装它有页码。

依赖策略
--------
- **Markdown / 纯文本**：纯标准库，永远可用（Mock 与离线路径不依赖重库）。
- **PDF**：需要 `pymupdf`；**DOCX**：需要 `python-docx`。
- 库没装时抛 `DependencyError` 并给出**可执行的安装提示**，而不是裸 `ImportError`。

不做 OCR：扫描版 PDF 提取不到文字时直接报错。**返回空文本会让下游引用一个空证据，
比报错更糟** —— 那种错误要到答辩现场才会被发现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".md", ".markdown", ".txt", ".pdf", ".docx"}


class ParseError(RuntimeError):
    """文件无法解析（格式不支持、文件不存在、提取不到文本）。"""


class DependencyError(ParseError):
    """缺少可选依赖。"""


@dataclass(frozen=True)
class PageText:
    no: int
    text: str
    synthetic: bool = False  # True 表示这是文档级文本而非真实物理页


@dataclass
class ParsedDoc:
    path: Path
    kind: str  # md / txt / pdf / docx
    pages: list[PageText] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages).strip()

    @property
    def page_count(self) -> int:
        return len([p for p in self.pages if not p.synthetic])

    @property
    def is_empty(self) -> bool:
        return not self.text


def _clean(text: str) -> str:
    """压掉 PDF 常见的多余空行与行尾空白，保留段落分隔。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_text(path: Path, kind: str) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8", errors="replace")
    body = _clean(raw)
    if not body:
        raise ParseError(f"{path.name}: 文件为空或只有空白")
    return ParsedDoc(path=path, kind=kind, pages=[PageText(no=1, text=body, synthetic=True)])


def _parse_pdf(path: Path) -> ParsedDoc:
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise DependencyError(
            f"解析 PDF 需要 pymupdf：pip install pymupdf（当前无法解析 {path.name}）"
        ) from exc

    pages: list[PageText] = []
    with pymupdf.open(path) as doc:  # type: ignore[attr-defined]
        for index, page in enumerate(doc, start=1):
            text = _clean(page.get_text("text"))
            if text:
                pages.append(PageText(no=index, text=text))
    if not pages:
        raise ParseError(
            f"{path.name}: 未提取到任何文字。可能是扫描版 PDF，本模块不做 OCR；"
            "请改用带文字层的版本或先做 OCR 再入库。"
        )
    return ParsedDoc(path=path, kind="pdf", pages=pages)


def _parse_docx(path: Path) -> ParsedDoc:
    try:
        from docx import Document  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise DependencyError(
            f"解析 DOCX 需要 python-docx：pip install python-docx（当前无法解析 {path.name}）"
        ) from exc

    document = Document(str(path))  # type: ignore[attr-defined]
    paragraphs = [_clean(p.text) for p in document.paragraphs]
    body = "\n\n".join(p for p in paragraphs if p)
    if not body:
        raise ParseError(f"{path.name}: 文档里没有可提取的段落文本")
    return ParsedDoc(path=path, kind="docx", pages=[PageText(no=1, text=body, synthetic=True)])


def parse_document(path: str | Path) -> ParsedDoc:
    """统一入口：按扩展名分派。"""
    path = Path(path)
    if not path.exists():
        raise ParseError(f"文件不存在：{path}")
    if not path.is_file():
        raise ParseError(f"不是文件：{path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ParseError(f"不支持的格式 {suffix or '(无扩展名)'}；支持：{', '.join(sorted(SUPPORTED))}")

    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    return _parse_text(path, "md" if suffix.startswith(".md") else "txt")


def parse_corpus(directory: str | Path, *, skip_errors: bool = False) -> tuple[list[ParsedDoc], list[str]]:
    """批量解析一个目录，返回 (成功列表, 错误列表)。

    `skip_errors=True` 时遇到坏文件继续跑（入库阶段用），错误汇总后由调用方决定是否失败。
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ParseError(f"目录不存在：{directory}")
    docs: list[ParsedDoc] = []
    errors: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        try:
            docs.append(parse_document(path))
        except ParseError as exc:
            errors.append(str(exc))
            if not skip_errors:
                raise
    return docs, errors
