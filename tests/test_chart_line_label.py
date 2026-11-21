"""折れ線のデータラベルは線の上（t）に置く。棒グラフには位置を指定しない。"""

# ruff: noqa: S101  # pytest の assert
from types import SimpleNamespace

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx_maker import charts

PAL = SimpleNamespace(accent="#00AA55", accent_mid="#55AA88", accent_dark="#005522", emphasis="#CC0000", text="#222222")


def _dlbl_pos(chart_type):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    spec = {"type": chart_type, "categories": ["a", "b"], "series": [{"name": "x", "values": [1, 2]}]}
    charts.add_chart(slide, {"chart": spec, "rect": {"x": 0, "y": 0, "w": 400, "h": 300}}, PAL)
    chart = next(s for s in slide.shapes if s.has_chart).chart
    return [e.get("val") for e in chart.plots[0]._element.iter(qn("c:dLblPos"))]


def test_折れ線のデータラベルは線の上に置く():
    assert _dlbl_pos("line") == ["t"]


@pytest.mark.parametrize("chart_type", ["bar", "barh"])
def test_棒グラフのデータラベルは位置を指定しない(chart_type):
    assert _dlbl_pos(chart_type) == []
