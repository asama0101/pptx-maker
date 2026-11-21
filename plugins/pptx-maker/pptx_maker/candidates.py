"""スライド案の収集。`<作業フォルダ>/slides/` の断片を、スライド番号ごとの案にまとめる。

名前の規則は `NN-R1.html`〜`NN-R3.html`（どのページも 2〜3 案。構造の違う案を並べる）。`NN-A.html` は使えない。
設計図に `デザイン方向の候補:` の行があるときは、その数（3〜4）の案 `NN-R1.html`〜`NN-Rn.html` を、
どのページにもそろえる（R4 も使える）。"""

import html as _html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from . import directions, paths, svgids

_NAME = re.compile(r"^(\d{2})-(R[1-4])\.html$")


def collect(work: Path) -> dict[str, dict[str, str]]:
    """スライド番号 → 案の名前（"R1"〜"R4"）→ 断片。不正な名前や組み合わせは、全件まとめて ValueError。"""
    d = Path(work) / "slides"
    if not d.is_dir():
        raise ValueError(f"{d} がありません（slides/NN-R1.html の形で案を置いてください）")
    # 数字で始まる（先頭の s・S は可）.html は断片のつもりとみなす（_NAME に合わなければ書き間違いか旧形式）。
    # draft-1.html・notes.html などは無視する
    files = sorted(f for f in d.iterdir() if f.suffix.lower() == ".html" and re.match(r"[sS]?\d", f.stem))
    cands = directions.candidate_list(work)
    last = "Rn" if cands else "R3"  # 名前の案内。候補の行があれば方向の数まで
    errors: list[str] = []
    type_pages = [f.name for f in files if re.fullmatch(r"\d{2}-A\.html", f.name)]
    for n in type_pages:
        errors.append(f"{n}: 型のページも 2〜3 案（{n[:2]}-R1.html〜）にしてください")
    bad = [f.name for f in files if not _NAME.match(f.name) and f.name not in type_pages]
    if bad:
        errors.append(
            f"断片の名前として読めないファイルがあります: {', '.join(bad)}"
            f"（旧形式の名前は使えません。どのページも NN-R1.html〜NN-{last}.html。"
            "NN は 2 桁で、-d2・-d3 は付けません）"
        )
    found: dict[str, list[Path]] = {}
    for f in files:
        m = _NAME.match(f.name)
        if m:
            found.setdefault(m.group(1), []).append(f)
    names = ", ".join(cands) if cands else ""
    for nn, fs in sorted(found.items()):
        keys = {_NAME.match(f.name).group(2) for f in fs}
        if cands is None:
            if "R4" in keys:
                errors.append(f"{nn}-R4.html: 設計図に デザイン方向の候補 がないと R4 は使えません")
            if len(keys - {"R4"}) < 2:
                errors.append(f"{nn}: 2〜3 案（{nn}-R1.html〜{nn}-R3.html のうち 2〜3 個）が要ります")
            continue
        errors.extend(f"{nn}-{k}.html: 設計図の候補（{names}）にない案です" for k in sorted(keys - set(cands)))
        errors.extend(f"{nn}: 案 {k} が足りません（設計図の候補: {names}）" for k in cands if k not in keys)
    nums = {int(f[:2]) for f in [*found, *type_pages]}
    missing = [f"{i:02d}" for i in range(1, max(nums, default=0) + 1) if i not in nums]
    if missing:
        errors.append(f"スライド番号が連続していません。足りない番号: {', '.join(missing)}")
    if 0 in nums:
        errors.append("スライド番号は 01 から始めます（00 は使えません）")
    if errors:
        raise ValueError("\n".join(errors))
    if not found:
        raise ValueError(f"{d} に NN-R1.html の形のファイルがありません")
    out: dict[str, dict[str, str]] = {}
    for nn, fs in found.items():
        for f in fs:
            key = _NAME.match(f.name).group(2)
            # 絵（pp-picture）の SVG の id は案ごとに一意にする（別の絵の定義に引かれて、アイコンや矢じりが消えない）
            out.setdefault(nn, {})[key] = svgids.uniquify(paths.read_text(f), f"s{nn}{key.lower()}-")
    return out


_MAIN_CLASS = re.compile(r"""class\s*=\s*["'][^"']*\bpp-(?:chart|table|picture|image)(?![\w-])""")


# 図形・線で組んだ図とみなす基準: pp-shape と pp-line の合計が DIAGRAM_MIN_PARTS 個以上で、
# その面積（幅×高さ）の合計がスライドの本体領域（1152×500px）の DIAGRAM_MIN_AREA 以上。
# 文字中心の案に付く飾り（見出しの帯・数個のカード）や、小さな点の数合わせを図とみなさないため。
DIAGRAM_MIN_PARTS = 8
DIAGRAM_MIN_AREA = 0.10
_BODY_AREA = 1152 * 500


def _is_shape_diagram(html: str) -> bool:
    parts = area = 0
    for tag in re.findall(r"<[^>]*>", html):
        if not re.search(r"""class\s*=\s*["'][^"']*\bpp-(?:shape|line)(?![\w-])""", tag):
            continue
        parts += 1
        w, h = (re.search(rf"(?<![\w-]){k}\s*:\s*(\d+(?:\.\d+)?)px", tag) for k in ("width", "height"))
        if w and h:
            area += float(w.group(1)) * float(h.group(1))
    return parts >= DIAGRAM_MIN_PARTS and area >= _BODY_AREA * DIAGRAM_MIN_AREA


def _has_main_visual(html: str) -> bool:
    """グラフ・表・絵、またはアイコン以外の画像（写真など）があるか。図形・線で組んだ図でもよい。"""
    if _is_shape_diagram(html):
        return True
    for tag in re.findall(r"<[^>]*>", html):
        if not _MAIN_CLASS.search(tag):
            continue
        if re.search(r"""\bdata-role\s*=\s*["']icon["']""", tag) and not re.search(
            r"""class\s*=\s*["'][^"']*\bpp-(?:chart|table|picture)(?![\w-])""", tag
        ):
            continue
        return True
    return False


def main_visual_warnings(cands: dict[str, dict[str, str]], exempt: set[str]) -> list[str]:
    """図・絵・表・グラフが主役でない案を、"NN-Rk: …" の形で返す。表紙・裏表紙など免除の番号は見ない。"""
    return [
        f"{nn}-{key}: 図・絵・表・グラフが主役になっていません"
        for nn, variants in sorted(cands.items())
        if nn not in exempt
        for key, html in variants.items()
        if not _has_main_visual(html)
    ]


# R22: 強調色の要素の上限。設計図は「強調の 1 点」だが、1 点が数個の部品（枠・数字・矢印）でできるので、
# 数が 6 を超えて初めて「強調が散っている」とみなす（実際の案で過検出にならない値）
EMPHASIS_MAX = 6
TEXT_MAX = 700  # 1 枚（案の断片）の文字量の上限の目安（R25。pp-text の文字数。18 案のサンプルは最大 314 字）
_EMPH = re.compile(r"""class\s*=\s*["'][^"']*\b(?:f|t)-emph(?![\w-])|var\(--emphasis\)""")
_BAR_TYPES = {"bar", "barh", "stacked"}  # R28: 0 始まりを求める型（line・pie・waterfall は対象外）
_CHART = re.compile(r"""data-chart\s*=\s*(?:'([^']*)'|"([^"]*)")""")


def _bar_axis_cut(html: str) -> bool:
    for m in _CHART.finditer(html):
        try:
            spec = json.loads(_html.unescape(m.group(1) or m.group(2)))
            lo = spec["axis"]["min"]
        except (ValueError, KeyError, TypeError):
            continue
        if spec.get("type") in _BAR_TYPES and isinstance(lo, int | float) and lo > 0:
            return True
    return False


def fragment_findings(html: str, *, body: bool) -> list[dict]:
    """鉄板ルール（R22・R18・R31・R28・R25）の指摘を、断片 1 つについて返す。
    {"rule", "message"}。body は本文スライドか。"""
    tags = re.findall(r"<[^>]*>", html)
    out = []
    n_emph = sum(1 for t in tags if _EMPH.search(t))
    if n_emph > EMPHASIS_MAX:
        out.append(
            {
                "rule": "R22",
                "message": f"強調色の要素が {n_emph} 個あります（{EMPHASIS_MAX} 個以内。強調は 1 点に絞る）",
            }
        )
    n_dec = len(re.findall(r">[^<]*可否[^<]*<", html))
    if n_dec >= 2:
        out.append(
            {"rule": "R18", "message": f"「可否」を含む要素が {n_dec} 個あります（決定を求める文は 1 か所にする）"}
        )
    if body and not re.search(r"""data-part\s*=\s*["']注釈["']|data-role\s*=\s*["']caption["']""", html):
        out.append({"rule": "R31", "message": "注釈（出所・前提・単位）がありません"})
    if _bar_axis_cut(html):
        out.append({"rule": "R28", "message": "棒グラフの軸が 0 から始まっていません（axis.min を 0 にする）"})
    chars = variant_meta(html)["chars"]
    if chars > TEXT_MAX:
        out.append({"rule": "R25", "message": f"文字量が {chars} 字あります（{TEXT_MAX} 字以内。削るか別ページへ）"})
    return out


_PART_TAG = re.compile(r"""class\s*=\s*["'][^"']*\bpp-(chart|table|picture)(?![\w-])""")
_SMALL_COMPOSITION_MIN = 3  # 図とは言えないが、図形・線で組んだ構図とみなす最小の数


class _PpTextChars(HTMLParser):
    """class に pp-text を持つ要素の中の文字数（前後と間の空白を除く）を数える。"""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[bool] = []
        self.inside = 0
        self.chars = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _VOID_TAGS:
            return
        hit = bool(re.search(r"(?<![\w-])pp-text(?![\w-])", dict(attrs).get("class") or ""))
        self.stack.append(hit)
        self.inside += hit

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID_TAGS and self.stack:
            self.inside -= self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.chars += len("".join(data.split()))


_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def variant_meta(html: str) -> dict:
    """案のバッジ用の値: 主役の種類（kind）・強調の数（emph）・文字量（chars）。"""
    tags = re.findall(r"<[^>]*>", html)
    parts = {m.group(1) for t in tags if (m := _PART_TAG.search(t))}
    shapes = sum(1 for t in tags if re.search(r"""class\s*=\s*["'][^"']*\bpp-(?:shape|line)(?![\w-])""", t))
    if "chart" in parts:
        kind = "グラフ"
    elif "table" in parts:
        kind = "表"
    elif "picture" in parts:
        kind = "絵"
    elif _is_shape_diagram(html):
        kind = "図"
    elif shapes >= _SMALL_COMPOSITION_MIN:
        kind = "構図"
    else:
        kind = "文章"
    p = _PpTextChars()
    p.feed(html)
    return {"kind": kind, "emph": sum(1 for t in tags if _EMPH.search(t)), "chars": p.chars}
