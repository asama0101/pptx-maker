"""スライド案の収集。`<作業フォルダ>/slides/` の断片を、スライド番号ごとの案にまとめる。

名前の規則は `NN-R1.html`〜`NN-R4.html`（どのページも 2〜4 案。レイアウトの違う案を並べる）。`NN-A.html` は使えない。
設計図の `デザイン方向の候補:` の行は読まない（古い作業フォルダに残っていても無視する）。"""

import html as _html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from . import paths, svgids

_NAME = re.compile(r"^(\d{2})-(R[1-4])\.html$")


def collect(work: Path) -> dict[str, dict[str, str]]:
    """スライド番号 → 案の名前（"R1"〜"R4"）→ 断片。不正な名前や組み合わせは、全件まとめて ValueError。"""
    d = Path(work) / "slides"
    if not d.is_dir():
        raise ValueError(f"{d} がありません（slides/NN-R1.html の形で案を置いてください）")
    # 数字で始まる（先頭の s・S は可）.html は断片のつもりとみなす（_NAME に合わなければ書き間違いか旧形式）。
    # draft-1.html・notes.html などは無視する
    files = sorted(f for f in d.iterdir() if f.suffix.lower() == ".html" and re.match(r"[sS]?\d", f.stem))
    errors: list[str] = []
    type_pages = [f.name for f in files if re.fullmatch(r"\d{2}-A\.html", f.name)]
    for n in type_pages:
        errors.append(f"{n}: 型のページも 2〜4 案（{n[:2]}-R1.html〜）にしてください")
    bad = [f.name for f in files if not _NAME.match(f.name) and f.name not in type_pages]
    if bad:
        errors.append(
            f"断片の名前として読めないファイルがあります: {', '.join(bad)}"
            "（旧形式の名前は使えません。どのページも NN-R1.html〜NN-R4.html。"
            "NN は 2 桁で、-d2・-d3 は付けません）"
        )
    found: dict[str, list[Path]] = {}
    for f in files:
        m = _NAME.match(f.name)
        if m:
            found.setdefault(m.group(1), []).append(f)
    for nn, fs in sorted(found.items()):
        if not 2 <= len(fs) <= 4:
            errors.append(f"{nn}: 2〜4 案（{nn}-R1.html〜{nn}-R4.html のうち 2〜4 個）が要ります")
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
    unsafe: list[str] = []
    for nn, fs in found.items():
        for f in fs:
            key = _NAME.match(f.name).group(2)
            text = paths.read_text(f)
            unsafe.extend(f"{nn}-{key}.html: {why}" for why in unsafe_parts(text))
            # 絵（pp-picture）の SVG の id は案ごとに一意にする（別の絵の定義に引かれて、アイコンや矢じりが消えない）
            out.setdefault(nn, {})[key] = svgids.uniquify(text, f"s{nn}{key.lower()}-")
    if unsafe:
        raise ValueError("\n".join(sorted(unsafe)) + f"\n直し方: {_FIX}")
    return out


# 断片で使えないタグ（script・入れ子の文書・外へ出る・遷移するもの。title 以下は、HTMLParser とブラウザで
# 中身の読み方が違い（SVG の中では中の要素が実際の要素になる）、検査をすり抜けさせられるもの）。見本の断片は使っていない
_BAD_TAGS = {
    "script", "iframe", "frame", "frameset", "object", "embed", "applet",
    "meta", "base", "link", "form", "animate", "set",
    "title", "xmp", "plaintext", "textarea", "noembed", "noframes", "noscript", "template", "select", "math",
}  # fmt: skip
_URL_ATTRS = {
    "src", "href", "xlink:href", "poster", "action", "formaction", "data", "srcset",
    "ping", "background", "lowsrc", "dynsrc", "longdesc", "cite", "manifest", "codebase", "archive", "icon",
}  # fmt: skip
_CSS_BAD = re.compile(r"@import|image-set|cross-fade|\bimage\(|\bsrc\(|expression\(|-moz-binding|\\", re.IGNORECASE)
_CSS_URL_START = re.compile(r"url\(", re.IGNORECASE)
_CSS_URL_MAX = 2000  # url( の中身を見る長さ。閉じ括弧のない url( が大量に並んでも二次時間にしない
# `<img/src=x/onerror=…>` は、URL 属性の値の一部としても読める（読み方が違う）
_SLASH_ON = re.compile(r"/on[a-z]+\s*=", re.IGNORECASE)
_ON_ATTR = re.compile(r"on[a-z]+")
# 生のテキスト全体（コメント・RCDATA の中も含む）に出てはいけないもの。パース結果に関係なく誤りとみなす。
# 本文に `<meta` と書くときは `&lt;meta` と書く
_RAW_TAG = re.compile(r"<(?:" + "|".join(sorted(_BAD_TAGS)) + r")(?![\w-])|http-equiv|srcdoc", re.IGNORECASE)
# `<!-->`・`<!--->`・`<!--!>` と `--!>` は、ブラウザでは（空の）コメントの終わりで、HTMLParser とは読み方が違う
_ODD_COMMENT = re.compile(r"<!--(?:>|->|!>)|--!>")
_FIX = "画像は作業フォルダの相対パス（material/a.png など）で書く。外部 URL・script・iframe・meta などは使わない"


def _bad_url(value: str) -> bool:
    """断片に書けない URL か。許可は、空・#id・スキームのない相対パス・data:image/ だけ。
    ブラウザが無視する制御文字・空白（java<TAB>script: など）は除いてから見る。
    `file:` は作業フォルダ限定にできないので許さない（画像は相対パスで書く）。"""
    v = re.sub(r"[\x00-\x20]", "", value).lower()
    if not v or v.startswith(("#", "data:image/")):
        return False
    if v.startswith(("\\", "//", "/\\")):
        return True
    return re.match(r"[^/?#]*:", v) is not None


def _strip_css_comments(css: str) -> str:
    out, i = [], 0
    while (a := css.find("/*", i)) >= 0:
        out.append(css[i:a])
        b = css.find("*/", a + 2)
        if b < 0:  # 閉じていないコメントは最後まで
            return "".join(out)
        i = b + 2
    out.append(css[i:])
    return "".join(out)


def _css_problem(css: str) -> str | None:
    """CSS に書けないもの（当たった語）。なければ None。"""
    c = _strip_css_comments(css)
    if m := _CSS_BAD.search(c):
        return "バックスラッシュ（CSS のエスケープ \\ は使わず、文字を直接書く）" if m.group() == "\\" else m.group()
    for m in _CSS_URL_START.finditer(c):
        v = c[m.end() : m.end() + _CSS_URL_MAX].split(")", 1)[0].lstrip(" \t\r\n\f'\"")
        if _bad_url(v):
            return f"url({v[:40]})"
    return None


class _UnsafeScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self._style: list[str] | None = None  # <style> の中身（閉じるまで集める）

    def _add(self, why: str) -> None:
        self.found.append(f"{self.getpos()[0]} 行目: {why}")

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _BAD_TAGS:
            self._add(f"<{tag}> は書けません")
        self._style = [] if tag == "style" else None
        for name, value in attrs:
            v = value or ""
            if _ON_ATTR.fullmatch(name) or name == "srcdoc":
                self._add(f"{name}= 属性は書けません")
            elif name in _URL_ATTRS and _SLASH_ON.search(v):
                self._add(f'{name}="{v.strip()[:40]}" は書けません（on…= 属性に読めるもの）')
            elif name in _URL_ATTRS and any(_bad_url(u) for u in (v.split(",") if name == "srcset" else [v])):
                self._add(f'{name}="{v.strip()[:40]}" は書けません（外部 URL・javascript: など）')
            elif name == "style" and (why := _css_problem(v)):
                self._add(f"style 属性に {why} は書けません")

    def handle_endtag(self, tag: str) -> None:
        if tag == "style" and self._style is not None:
            self._check_style()
        self._style = None

    def handle_data(self, data: str) -> None:
        if self._style is not None:
            self._style.append(data)

    def unknown_decl(self, data: str) -> None:
        self._add("<![ ... ]> は書けません（CDATA など。ブラウザと読み方が違い、検査をすり抜ける）")

    def _check_style(self) -> None:
        css = "".join(self._style or [])
        if "<" in css.replace("<![CDATA[", "").replace("]]>", ""):
            self._add("<style> の中に < は書けません（SVG の中では要素として読まれる）")
        elif why := _css_problem(css):
            self._add(f"<style> に {why} は書けません")

    def close(self) -> None:
        super().close()
        if self._style is not None:  # 閉じていない <style>
            self._check_style()


def unsafe_parts(html: str) -> list[str]:
    """断片に書けないもの（_BAD_TAGS のタグ・on*・srcdoc・許可外の URL と CSS）の説明。なければ空。
    SVG の xmlns のような名前空間宣言は URL 属性ではないので対象外。"""
    scan = _UnsafeScan()
    scan.feed(html)
    scan.close()
    found = scan.found
    # 第 2 の検査: パース結果に頼らず生のテキストを見る（読み方の差でパーサの目に入らないものを拾う）
    for m in _ODD_COMMENT.finditer(html):
        found.append(f"{_line(html, m.start())} 行目: {m.group()} は書けません（ブラウザと読み方が違うコメント）")
    for m in _RAW_TAG.finditer(html):
        found.append(
            f"{_line(html, m.start())} 行目: {m.group()} が書かれています（コメントでも不可。文字は &lt; で書く）"
        )
    if "javascript:" in re.sub(r"[\x00-\x1f]", "", html).lower():
        found.append("javascript: が書かれています（コメント・本文でも書けません）")
    return list(dict.fromkeys(found))


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


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
