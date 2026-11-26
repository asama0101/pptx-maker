# ruff: noqa: S101  # pytest の assert
"""断片の pp-* 要素の番号づけ・検査・書き換え（fragedit）のテスト。"""

import pytest
from pptx_maker.fragedit import apply, parts, validate

FRAG = """<section class="slide" data-layout="body" data-type="body">
  <div class="pp-text" data-role="title" data-chrome style="left:96px;top:40px;width:1088px;height:48px">題</div>
  <div class="pp-text" data-role="body" style="left:96px;top:140px;width:500px;height:100px">本文 A<br>本文 B</div>
  <div class="pp-shape" style="left:640px;top:140px;width:300px;height:100px"><div class="pp-text" style="left:10px;top:10px;width:100px;height:30px">入れ子</div></div>
  <div class="pp-line" style="left:96px;top:300px;width:400px;height:0"></div>
  <div class="pp-text" data-ph="title" style="height:120px">表紙の題</div>
</section>"""  # noqa: E501

POS = "left:96px;top:140px;width:500px;height:100px"


def test_parts_文書順に番号を振る():
    ps = parts(FRAG)
    assert [p.kind for p in ps] == ["text", "text", "shape", "text", "line", "text"]
    assert [p.index for p in ps] == [0, 1, 2, 3, 4, 5]
    assert [p.nested for p in ps] == [False, False, False, True, False, False]
    assert [p.fixed for p in ps] == [True, False, False, False, False, True]
    assert len(ps[1].texts) == 2
    assert len(ps[2].texts) == 0
    assert len(ps[3].texts) == 1
    assert ps[1].style == {"left": "96px", "top": "140px", "width": "500px", "height": "100px"}
    s, e = ps[1].style_value
    assert FRAG[s:e] == POS
    assert [FRAG[a:b] for a, b in ps[1].texts] == ["本文 A", "本文 B"]


def test_apply_位置とサイズだけ書き換える():
    got = apply(FRAG, {1: {"left": 100, "width": 420}})
    assert got == FRAG.replace(POS, "left:100px;top:140px;width:420px;height:100px")
    assert apply(FRAG, {4: {"height": 0}}) == FRAG.replace("width:400px;height:0", "width:400px;height:0px")
    assert apply(FRAG, {4: {"width": 0}}) == FRAG.replace("width:400px;height:0", "width:0px;height:0")


def test_apply_文言を書き換えエスケープする():
    got = apply(FRAG, {1: {"text": ["A & <B> </script>", "本文 B"]}})
    assert "A &amp; &lt;B&gt; &lt;/script&gt;<br>本文 B" in got
    assert got == FRAG.replace("本文 A<br>", "A &amp; &lt;B&gt; &lt;/script&gt;<br>")


def test_apply_実体参照をまたいだ文言は_1_つのテキストとして置き換える():
    html = '<div class="pp-text" style="left:1px">a &amp; b<br>c</div>'
    ps = parts(html)
    assert [html[a:b] for a, b in ps[0].texts] == ["a &amp; b", "c"]
    assert apply(html, {0: {"text": ["x", "y"]}}) == '<div class="pp-text" style="left:1px">x<br>y</div>'


@pytest.mark.parametrize(
    ("html", "items", "index"),
    [
        (FRAG, {0: {"left": 1}}, 0),
        (FRAG, {3: {"top": 1}}, 3),
        (FRAG, {99: {"left": 1}}, 99),
        (FRAG, {2: {"text": ["x"]}}, 2),
        (FRAG, {1: {"text": ["x"]}}, 1),
        (FRAG, {1: {"text": ["x", 2]}}, 1),
        (FRAG, {1: {"left": 1.5}}, 1),
        (FRAG, {1: {"left": True}}, 1),
        (FRAG, {1: {"width": -1}}, 1),
        (FRAG, {1: {"height": -1}}, 1),
        (FRAG, {1: {"color": 1}}, 1),
        ('<div class="pp-text" style="left:1px;top:2px">x</div>', {0: {"width": 5}}, 0),
        ('<div class="pp-text" style="margin-left:1px">x</div>', {0: {"left": 5}}, 0),
    ],
)
def test_validate_直せないものを断る(html, items, index):
    errs = validate(html, items)
    assert errs
    assert all(e.startswith(f"要素 {index}:") for e in errs)
    with pytest.raises(ValueError, match=f"要素 {index}:"):
        apply(html, items)


def test_validate_題の文言は直せる():
    assert validate(FRAG, {0: {"text": ["新しい題"]}}) == []
    assert validate(FRAG, {5: {"text": ["新"]}}) == []
    assert validate(FRAG, {}) == []


def test_改行コードと_BOM_を保つ():
    crlf = FRAG.replace("\n", "\r\n")
    got = apply(crlf, {1: {"left": 100, "text": ["X", "本文 B"]}})
    assert got == crlf.replace("left:96px;top:140px", "left:100px;top:140px").replace("本文 A", "X")
    bom = "\ufeff" + crlf
    got = apply(bom, {4: {"width": 7}, 1: {"text": ["X", "Y"]}})
    assert got == bom.replace("width:400px", "width:7px").replace("本文 A<br>本文 B", "X<br>Y")


def test_開始タグの属性に大なりや単一引用符や大文字の_STYLE_があっても番号がずれない():
    html = '<div class="pp-text" data-note="a>b" STYLE=\'left:1px;top:2px;width:3px;height:4px\'>x</div>'
    assert len(parts(html)) == 1
    assert apply(html, {0: {"left": 9}}) == html.replace("left:1px", "left:9px")
    assert apply(html, {0: {"left": 9}}).count("STYLE='left:9px;top:2px;width:3px;height:4px'") == 1
