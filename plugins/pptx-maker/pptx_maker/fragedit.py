"""断片（`slides/NN-Rk.html`）の `pp-*` 要素を、文書順の番号で指して書き換える。

番号は、クラスに `pp-text|pp-shape|pp-line|pp-image|pp-table|pp-chart|pp-picture` を持つ要素を、開始タグの順に
0 から振る。直せるのは、文言（`pp-text` の自分のテキストノード）と、位置・大きさ（`style` の
`left|top|width|height`）だけ。
書き換えた箇所以外は 1 文字も変えない（改行コード・BOM もそのまま）。文字列だけを受け取り、ファイル I/O はしない。

`items` は `{番号: {"text": [文字列, …], "left"|"top"|"width"|"height": 整数}}`（項目は任意）。"""

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

_KINDS = ("text", "shape", "line", "image", "table", "chart", "picture")
_VOID = frozenset(
    ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr")
)
_GEOMETRY = ("left", "top", "width", "height")
_ATTR = re.compile(r"""\s([^\s"'>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]*))?""")
_DECL = re.compile(r"([^;:]+):([^;]*)")


@dataclass(frozen=True)
class Part:
    index: int
    kind: str
    nested: bool
    fixed: bool
    style: dict[str, str]
    texts: tuple[tuple[int, int], ...]
    style_value: tuple[int, int] | None


class _Scanner(HTMLParser):
    def __init__(self, src: str):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.starts = [0]
        for i, ch in enumerate(src):
            if ch == "\n":
                self.starts.append(i + 1)
        self.stack: list[tuple[str, int | None]] = []
        self.recs: list[dict] = []

    def _pos(self) -> int:
        line, col = self.getpos()
        return self.starts[line - 1] + col

    def _owner(self) -> int | None:
        for _, idx in reversed(self.stack):
            if idx is not None:
                return idx
        return None

    def _open(self, tag: str, attrs: list, selfclosing: bool) -> None:
        start = self._pos()
        raw = self.get_starttag_text() or ""
        names = dict(attrs)
        kinds = [c[3:] for c in (names.get("class") or "").split() if c[3:] in _KINDS and c.startswith("pp-")]
        idx = None
        if kinds:
            idx = len(self.recs)
            style_value = None
            style = ""
            for m in _ATTR.finditer(raw, len(tag) + 1):
                if m.group(1).lower() == "style" and m.group(2):
                    v = m.group(2)
                    q = v[0] in "\"'"
                    style_value = (start + m.start(2) + q, start + m.end(2) - q)
                    style = raw[m.start(2) + q : m.end(2) - q]
            self.recs.append(
                {
                    "kind": kinds[0],
                    "nested": self._owner() is not None,
                    "fixed": "data-chrome" in names or "data-ph" in names,
                    "style": style,
                    "style_value": style_value,
                    "pieces": [],
                }
            )
        if not selfclosing and tag not in _VOID:
            self.stack.append((tag, idx))

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def _piece(self, start: int, end: int) -> None:
        owner = self._owner()
        if owner is None:
            return
        pieces = self.recs[owner]["pieces"]
        if pieces and pieces[-1][1] == start:
            pieces[-1] = (pieces[-1][0], end)
        else:
            pieces.append((start, end))

    def handle_data(self, data):
        start = self._pos()
        self._piece(start, start + len(data))

    def _ref(self, prefix: str, name: str) -> None:
        start = self._pos()
        end = start + len(prefix) + len(name)
        if self.src[end : end + 1] == ";":
            end += 1
        self._piece(start, end)

    def handle_entityref(self, name):
        self._ref("&", name)

    def handle_charref(self, name):
        self._ref("&#", name)


def _style_dict(style: str) -> dict[str, str]:
    return {m.group(1).strip().lower(): m.group(2).strip() for m in _DECL.finditer(style)}


def parts(html: str) -> list[Part]:
    sc = _Scanner(html)
    sc.feed(html)
    sc.close()
    return [
        Part(
            index=i,
            kind=r["kind"],
            nested=r["nested"],
            fixed=r["fixed"],
            style=_style_dict(r["style"]),
            texts=tuple((s, e) for s, e in r["pieces"] if html[s:e].strip()),
            style_value=r["style_value"],
        )
        for i, r in enumerate(sc.recs)
    ]


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check(p: Part, item) -> list[str]:
    if not isinstance(item, dict):
        return ["値は辞書にしてください"]
    errs = []
    for key, v in item.items():
        if key == "text":
            if p.kind != "text":
                errs.append("text は pp-text にだけ書けます")
            elif not isinstance(v, list) or len(v) != len(p.texts):
                errs.append(f"text の数が違います（この要素のテキストは {len(p.texts)} 件）")
            elif not all(isinstance(s, str) for s in v):
                errs.append("text の要素は文字列にしてください")
        elif key in _GEOMETRY:
            if p.fixed or p.nested:
                errs.append(f"{key} は固定部分・入れ子の要素では直せません")
            elif key not in p.style:
                errs.append(f"{key} が style に書かれていません")
            elif not _is_int(v):
                errs.append(f"{key} は整数にしてください")
            elif key in ("width", "height") and v < 0:
                errs.append(f"{key} は 0 以上にしてください")
        else:
            errs.append(f"{key} は直せない項目です")
    return errs


def validate(html: str, items: dict[int, dict]) -> list[str]:
    ps = parts(html)
    errs = []
    for n, item in items.items():
        if not _is_int(n) or not 0 <= n < len(ps):
            errs.append(f"要素 {n}: 番号が範囲外です（0〜{len(ps) - 1}）")
            continue
        errs += [f"要素 {n}: {m}" for m in _check(ps[n], item)]
    return errs


def apply(html: str, items: dict[int, dict]) -> str:
    errs = validate(html, items)
    if errs:
        raise ValueError("\n".join(errs))
    ps = parts(html)
    edits: list[tuple[int, int, str]] = []
    for n, item in items.items():
        p = ps[n]
        if "text" in item:
            for (s, e), new in zip(p.texts, item["text"], strict=True):
                raw = html[s:e]
                lead = raw[: len(raw) - len(raw.lstrip())]
                trail = raw[len(raw.rstrip()) :]
                edits.append((s, e, lead + _esc(new) + trail))
        geo = {k: v for k, v in item.items() if k in _GEOMETRY}
        if geo:
            vs, ve = p.style_value
            style = html[vs:ve]
            for k, v in geo.items():
                last = [m for m in _DECL.finditer(style) if m.group(1).strip().lower() == k][-1]
                val = last.group(2)
                a = last.start(2) + len(val) - len(val.lstrip())
                b = last.start(2) + len(val.rstrip())
                edits.append((vs + a, vs + b, f"{v}px"))
    out = html
    for s, e, new in sorted(edits, reverse=True):
        out = out[:s] + new + out[e:]
    return out


def _esc(s: str) -> str:
    return html.escape(s, quote=False)
