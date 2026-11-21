"""既存の PPTX を読んで Markdown にする（pptx-extract）。CLI は知らない。"""

from collections.abc import Iterator
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape

_OLE_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # 暗号化された Office ファイルの先頭（OLE 形式）


_TITLES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
_SKIPPED = {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.SLIDE_NUMBER}


class ExtractError(Exception):
    """読めない PPTX。`str(e)` が利用者向けのメッセージ。"""


def _open(path: Path):
    """読めない入力を 5 分類（拡張子・存在しない・空・暗号化・壊れ）に分けて断り、読めれば Presentation を返す。"""
    if path.suffix.lower() != ".pptx":
        raise ExtractError(f"{path.name} は .pptx ではありません（.ppt・.potx・.pptm などは読めません）")
    if not path.is_file():
        raise ExtractError(f"{path} が見つかりません（存在しないか、フォルダです）")
    if path.stat().st_size == 0:
        raise ExtractError(f"{path.name} は空のファイルです")
    with path.open("rb") as f:
        head = f.read(len(_OLE_HEAD))
    if head == _OLE_HEAD:
        raise ExtractError(f"{path.name} はパスワード付きです。パスワードを外すか、PowerPoint で保存し直してください")
    try:
        return Presentation(str(path))
    except Exception as e:  # noqa: BLE001  python-pptx が開けなかった理由は、型が一定でないので 1 か所で束ねる
        raise ExtractError(f"{path.name} を開けませんでした（壊れている可能性があります）: {e}") from e


def _walk(shapes) -> Iterator[BaseShape]:
    """XML の順に図形を返す。グループは再帰して、中身だけを返す。"""
    for shape in shapes:
        if isinstance(shape, GroupShape):
            yield from _walk(shape.shapes)
        else:
            yield shape


def _ph_type(shape: BaseShape):
    return shape.placeholder_format.type if shape.is_placeholder else None


def _cell(cell) -> str:
    r"""表のセルの文字。結合された側は空。改行は `<br>`、`|` は `\|`。"""
    if cell.is_spanned:
        return ""
    text = cell.text.replace("|", "\\|")
    return text.replace("\r\n", "<br>").replace("\n", "<br>").replace("\v", "<br>")


def _render_table(table) -> list[str]:
    rows = [[_cell(c) for c in row.cells] for row in table.rows]
    lines = [f"| {' | '.join(row)} |" for row in rows]
    lines.insert(1, f"|{'---|' * len(rows[0])}")
    return lines


_CHART_KINDS = (  # chart_type.name の接頭辞 → 日本語名（上から順に当てる）
    ("XY_SCATTER", "散布図"),
    ("BUBBLE", "バブル"),
    ("DOUGHNUT", "円"),
    ("PIE", "円"),
    ("LINE", "折れ線"),
    ("AREA", "面"),
    ("COLUMN", "棒"),
    ("BAR", "棒"),
)
_NOT_READ = "[グラフ: 値を読めませんでした]"


def _chart_kind(chart) -> str:
    name = chart.chart_type.name
    if "OF_PIE" not in name:
        for prefix, kind in _CHART_KINDS:
            if name.startswith(prefix):
                return kind
    return name


def _num(value) -> str:
    """グラフに保存された数値のまま出す（整数値は整数で。空は空文字）。"""
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def _row(cells: list[str]) -> str:
    return f"| {' | '.join(cells)} |"


def _at(values, i: int) -> str:
    """系列の i 番目の値。系列ごとに点の数が違っても、足りない所は空にする。"""
    return _num(values[i]) if i < len(values) else ""


def _chart_lines(chart) -> list[str]:
    series = list(chart.series)
    if not any(v is not None for s in series for v in s.values):
        return [_NOT_READ]
    lines = [f"[グラフ: {_chart_kind(chart)}]"]
    if chart.chart_type.name.startswith(("XY_SCATTER", "BUBBLE")):
        for s in series:
            # X は idx で Y と対応づける（欠けた点があっても組がずれない）。文字列の X もそのまま出す
            xs = {pt.get("idx"): pt.xpath("string(./c:v)") for pt in s._element.xpath("./c:xVal//c:pt")}
            lines += [f"系列: {s.name}", "| X | Y |", "|---|---|"]
            lines += [_row([xs.get(str(i), ""), _num(y)]) for i, y in enumerate(s.values)]
        return lines
    categories = list(chart.plots[0].categories)
    lines += [_row(["カテゴリ", *[s.name for s in series]]), f"|{'---|' * (len(series) + 1)}"]
    for i, category in enumerate(categories):
        lines.append(_row([str(category), *[_at(s.values, i) for s in series]]))
    return lines


def _render_chart(chart) -> list[str]:
    """`[グラフ: <種類>]` と数値の表。読めないグラフは、ファイル全体を止めず、印を 1 行だけ出す。

    系列が 0 件・値がすべて空のほか、python-pptx が要素を扱えない種類（3-D・補助円付き・株価など）も印にする。
    """
    try:
        return _chart_lines(chart)
    except Exception:  # noqa: BLE001  グラフ 1 つの失敗でファイル全体を止めない（原因の型は一定でない）
        return [_NOT_READ]


def _text(paragraph) -> str:
    """段落の文字。段落内の改行（垂直タブ）は半角スペースにする。"""
    return paragraph.text.replace("\v", " ")


def _render_shape(shape: BaseShape) -> list[str]:
    """図形の Markdown の行。箇条書きと通常段落は区別せず、空でない段落をすべて `- ` で出す。"""
    if getattr(shape, "has_table", False) and shape.has_table:
        return _render_table(shape.table)
    if getattr(shape, "has_chart", False) and shape.has_chart:
        return _render_chart(shape.chart)
    if not shape.has_text_frame:
        return []
    return [f"{'  ' * p.level}- {_text(p)}" for p in shape.text_frame.paragraphs if p.text.strip()]


def _title(shapes: list[BaseShape]) -> str | None:
    for shape in shapes:
        if _ph_type(shape) in _TITLES:
            words = [_text(p) for p in shape.text_frame.paragraphs if p.text.strip()]
            return " ".join(words) or None
    return None


def extract(path: Path) -> str:
    """PPTX を読んで Markdown を返す。読めなければ ExtractError。"""
    prs = _open(path)
    lines = [f"# {path.name}"]
    for n, slide in enumerate(prs.slides, start=1):
        if slide._element.get("show") == "0":  # 非表示スライドは読まない（番号は元のまま）
            continue
        shapes = list(_walk(slide.shapes))
        lines += ["", f"## スライド {n}: {_title(shapes) or '（題なし）'}"]
        for shape in shapes:
            if _ph_type(shape) in _TITLES | _SKIPPED:
                continue
            lines += _render_shape(shape)
    return "\n".join(lines) + "\n"
