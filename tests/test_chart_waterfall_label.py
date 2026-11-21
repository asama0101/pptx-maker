"""ウォーターフォールの小さい段のラベルが fmt（桁数・単位）に従う。"""

# ruff: noqa: S101  # pytest の assert
from types import SimpleNamespace

import pytest
from pptx import Presentation
from pptx_maker import charts

PAL = SimpleNamespace(accent="#00AA55", accent_mid="#55AA88", accent_dark="#005522", emphasis="#CC0000", text="#222222")


@pytest.mark.parametrize(
    ("value", "fmt", "want"),
    [
        (0.5, "#,##0.0", "0.5"),
        (300, '#,##0"万円"', "300万円"),
        (1234, "#,##0", "1,234"),
        (5, "0", "5"),
        (2.5, "0", "3"),
        (-2.5, "0", "-3"),
        (0.125, "0.00", "0.13"),
        (0.05, "0.0%", "5.0%"),
        (0.5, "0%", "50%"),
        (0.125, "0%", "13%"),
        (1234.5, '[>=2000]#,##0.0;""', "1,234.5"),
        (0.25, "General", "0.25"),
    ],
    ids=[
        "小数1桁",
        "引用符つきの単位",
        "桁区切り",
        "整数",
        "半分は0から遠い側へ丸める",
        "負の半分も0から遠い側",
        "小数2桁の丸め",
        "パーセント小数1桁",
        "パーセント整数",
        "パーセントの丸め",
        "条件と区画は無視",
        "解釈できない書式は素の数字",
    ],
)
def test_ラベル文字は書式の最初の区画に従う(value, fmt, want):
    assert charts._label_text(value, fmt) == want


def _waterfall(spec_extra, values):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    spec = {
        "type": "waterfall",
        "categories": ["a", "b", "c"],
        "series": [{"name": "x", "values": values}],
        **spec_extra,
    }
    charts.add_chart(slide, {"chart": spec, "rect": {"x": 0, "y": 0, "w": 400, "h": 300}}, PAL)
    return [s for s in slide.shapes if s.has_chart][0].chart


def test_小さい段のラベルは_fmt_の桁数に従う():
    chart = _waterfall({"fmt": "#,##0.0"}, [100, 0.5, 100.5])
    assert chart.plots[0].series[0].points[1].data_label.text_frame.text == "0.5"


def test_データラベルの書式は最初の区画だけを使う():
    chart = _waterfall({"fmt": "[>=1]#,##0;△#,##0"}, [100, 5, 105])
    assert chart.plots[0].series[1].data_labels.number_format == '[>=8.4]#,##0;""'


def test_強調した点のラベルにも_fmt_としきい値の書式が付く():
    spec = {"fmt": "#,##0", "totals": [0, 4], "highlight": [2, 3]}
    chart = _waterfall_n(spec, [10000, 5000, -300, -4000, 10700])
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    for idx in ("2", "3"):
        # 小さな段の文字ラベル（基準系列の c:tx つき）は対象外。強調した点のラベルだけ見る
        dlbls = [d for d in chart._chartSpace.xpath(f"//c:dLbl[c:idx/@val='{idx}']") if d.find("c:tx", ns) is None]
        assert dlbls, idx
        for d in dlbls:
            fmt = d.find("c:numFmt", ns)
            assert fmt is not None
            assert fmt.get("sourceLinked") == "0"
            code = fmt.get("formatCode")
            assert code.startswith("[>=")  # しきい値で隠す書式
            assert code.endswith(';""')
            assert "#,##0" in code
            kids = [c.tag.split("}")[1] for c in d]
            assert kids.index("numFmt") < kids.index("showVal")  # 子要素の順序
            for later in ("spPr", "txPr", "dLblPos"):
                if later in kids:
                    assert kids.index("numFmt") < kids.index(later)


def _waterfall_n(spec_extra, values):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    spec = {"type": "waterfall", "categories": list("abcde"), "series": [{"name": "x", "values": values}], **spec_extra}
    charts.add_chart(slide, {"chart": spec, "rect": {"x": 0, "y": 0, "w": 400, "h": 300}}, PAL)
    return [s for s in slide.shapes if s.has_chart][0].chart


def test_横棒は先頭のカテゴリを上に描き_値軸は下に残す():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    spec = {"type": "barh", "categories": ["先頭", "二番目", "三番目"], "series": [{"name": "x", "values": [3, 2, 1]}]}
    charts.add_chart(slide, {"chart": spec, "rect": {"x": 0, "y": 0, "w": 400, "h": 300}}, PAL)
    chart = [s for s in slide.shapes if s.has_chart][0].chart
    xml = chart._chartSpace
    assert xml.xpath("string(//c:catAx/c:scaling/c:orientation/@val)") == "maxMin"
    assert xml.xpath("string(//c:valAx/c:crosses/@val)") == "max"
    # 縦棒（bar）は変えない
    spec["type"] = "bar"
    charts.add_chart(slide, {"chart": spec, "rect": {"x": 0, "y": 0, "w": 400, "h": 300}}, PAL)
    bar = [s for s in slide.shapes if s.has_chart][1].chart
    assert bar._chartSpace.xpath("string(//c:catAx/c:scaling/c:orientation/@val)") == "minMax"


def test_累計の浮動小数の誤差ではエラーにしない一方_本当に負なら止める():
    w = charts.waterfall_series([0.3, -0.1, -0.2, 0, 5], [0, 4])
    assert min(w["base"]) >= 0  # -2.8e-17 は 0 に丸める
    with pytest.raises(ValueError, match="累計が 0 未満"):
        charts.waterfall_series([1, -2, 0], [0, 2])


def test_累計の許容誤差は値の大きさに比例する():
    w = charts.waterfall_series([1e12, -4e11 - 0.3, -6e11 + 0.3, 5], [0, 3])  # 1e12 台の足し引きの誤差は 1e-9 を超える
    assert min(w["base"]) >= 0
