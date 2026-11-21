"""文字枠は HTML の行ボックス（line-height × 文字サイズ）に合わせる。
1 行の文字は枠を行ボックスの高さにして上下中央、複数行は固定ポイントの行間で、余りの分だけ枠を上へずらす。"""

# ruff: noqa: S101  # pytest の assert
import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx_maker import build, check, paths, template

from tests._measure import model_of

pytestmark = pytest.mark.slow  # ブラウザ（Chromium）で測る

PX = 9525
BAR = (
    '<div class="pp-shape" style="position:absolute;left:100px;top:100px;'
    'width:200px;height:36px;background:#336699"></div>'
)
LABEL = (
    '<div class="pp-text" style="position:absolute;left:110px;top:100px;width:180px;height:36px;'
    'font-size:20px;line-height:36px">四半期</div>'
)
THREE_LINES = (
    '<div class="pp-text" style="position:absolute;left:100px;top:300px;width:120px;height:200px;'
    'font-size:20px;line-height:1.8">あいうえおかきくけこさしすせそたちつてと</div>'
)


def _pptx(inner, tmp_path):
    tpl = paths.ASSETS / "template" / "standard.potx"
    out = build.build(model_of(inner), tpl, template.analyze(tpl), None, tmp_path / "o.pptx", base_dir=tmp_path)
    return Presentation(str(out)).slides[0]


def _px(shape):
    return {k: getattr(shape, k) / PX for k in ("left", "top", "width", "height")}


def _text_shape(slide, text):
    return next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text.startswith(text))


def _lnspc(shape):
    child = shape.text_frame.paragraphs[0]._p.pPr.find(qn("a:lnSpc"))[0]
    return child.tag.split("}")[1], child.get("val")


def test_1行の文字は行ボックスの高さの枠で上下中央に置く(tmp_path):
    slide = _pptx(BAR + LABEL, tmp_path)
    label = _text_shape(slide, "四半期")
    r = _px(label)
    assert r["top"] == pytest.approx(100, abs=1)
    assert r["height"] == pytest.approx(36, abs=1)  # line-height 36px の行ボックス。文字の範囲（約 27px）ではない
    assert label.text_frame.vertical_anchor == 3  # MSO_ANCHOR.MIDDLE
    assert _lnspc(label) == ("spcPct", "100000")


def test_複数行の文字は行数分の高さの枠で固定ポイントの行間にする(tmp_path):
    slide = _pptx(THREE_LINES, tmp_path)
    box = _text_shape(slide, "あいうえお")
    lines = model_of(THREE_LINES)[0]["elements"][0]["paras"][0]["lines"]
    assert lines >= 3
    assert _px(box)["height"] == pytest.approx(lines * 36, abs=1)  # 行数 × 20px × 1.8
    assert _lnspc(box) == ("spcPts", "2700")


def test_複数行の枠は行間の余りの分だけ文字の範囲より上に置く(tmp_path):
    el = model_of(THREE_LINES)[0]["elements"][0]
    slide = _pptx(THREE_LINES, tmp_path)
    top = _px(_text_shape(slide, "あいうえお"))["top"]
    assert top < el["box"]["y"] - 5  # 固定の行間は余りを行の上に積むので、その分だけ枠を上げる
    assert top == pytest.approx(el["box"]["y"] - 2 * el["lead"], abs=1)


@pytest.mark.parametrize(
    ("height", "expected"),
    [(20, True), (36, False)],
    ids=["行ボックスより低い枠", "行ボックスが収まる枠"],
)
def test_overflow_は行ボックスの高さで判定する(height, expected):
    inner = (
        '<div class="pp-text" style="position:absolute;left:100px;top:100px;width:300px;'
        f'height:{height}px;font-size:20px;line-height:36px">あ</div>'
    )
    assert model_of(inner)[0]["elements"][0]["overflow"] is expected


def test_check_は行間込みの高さが足りない枠を_overflow_にする():
    info = template.analyze(paths.ASSETS / "template" / "standard.potx")
    inner = (
        '<div class="pp-text" style="position:absolute;left:100px;top:100px;width:300px;'
        'height:24px;font-size:20px;line-height:2">あ</div>'
    )
    vs = check.check_model(model_of(inner), info)
    assert {v["rule"] for v in vs} == {"overflow"}


TITLE_PLACED = (
    '<div class="pp-text" data-ph="title" style="top:120px;height:150px"><div>一段落目</div><div>二段落目</div></div>'
)
TITLE_DEFAULT = '<div class="pp-text" data-ph="title" style="height:100px">題</div>'


def _closing(inner, tmp_path):
    tpl = paths.ASSETS / "template" / "standard.potx"
    model = model_of(inner)
    model[0]["layout"] = "closing"
    out = build.build(model, tpl, template.analyze(tpl), None, tmp_path / "o.pptx", base_dir=tmp_path)
    return Presentation(str(out)).slides[0]


def test_題が_style_で_top_と_height_を明示すると_HTML_の位置に置く(tmp_path):
    el = model_of(TITLE_PLACED)[0]["elements"][0]
    title = _closing(TITLE_PLACED, tmp_path).shapes.title
    r = _px(title)
    assert r["top"] == pytest.approx(el["lbox"]["y"] - (el["lead"]), abs=1)
    assert r["height"] == pytest.approx(el["lbox"]["h"], abs=1)
    assert r["top"] < 135  # テンプレートの裏表紙の題（y300）ではなく、HTML の top:120px 付近


def test_題が位置を明示しなければテンプレートのレイアウトの位置に置く(tmp_path):
    tpl = paths.ASSETS / "template" / "standard.potx"
    index = template.layout_index(template.analyze(tpl), {"layout": "closing"})
    layout = template.open_template(tpl).slide_layouts[index]
    expected = next(p for p in layout.placeholders if p.placeholder_format.type in (1, 3))
    title = _closing(TITLE_DEFAULT, tmp_path).shapes.title
    assert (title.top, title.height) == (expected.top, expected.height)
