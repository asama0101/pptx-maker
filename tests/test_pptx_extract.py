"""pptx-extract: 既存の PPTX を読んで Markdown にする。

置き換えるものはない（PPTX は python-pptx で tmp_path の下に実物を作る）。
CLI は cli.main を直接呼び、終了コードと標準出力・標準エラーを確かめる。
"""

# ruff: noqa: S101  # pytest の assert
from pathlib import Path

import pytest
from pptx import Presentation
from pptx_maker import cli

OLE_HEAD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def make_deck(path: Path, build=None) -> Path:
    prs = Presentation()
    if build:
        build(prs)
    prs.save(str(path))
    return path


def run(capsys, *argv) -> tuple[int, str, str]:
    rc = cli.main(list(argv))
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _broken(tmp_path: Path) -> list[tuple[str, Path]]:
    """読めない 5 分類（拡張子・存在しない・空・暗号化・壊れ）の入力。"""
    ext = tmp_path / "a.ppt"
    ext.write_bytes(b"x")
    folder = tmp_path / "dir.pptx"
    folder.mkdir()
    empty = tmp_path / "empty.pptx"
    empty.write_bytes(b"")
    enc = tmp_path / "enc.pptx"
    enc.write_bytes(OLE_HEAD + b"\0" * 512)
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"not a zip")
    return [
        ("拡張子", ext),
        ("存在しない", tmp_path / "none.pptx"),
        ("空", empty),
        ("暗号化", enc),
        ("壊れ", bad),
        ("フォルダ", folder),
    ]


def test_存在しないパスは終了コード2でメッセージを出し標準出力は空(tmp_path, capsys):
    rc, out, err = run(capsys, "pptx-extract", str(tmp_path / "none.pptx"))
    assert (rc, out) == (2, "")
    assert err.startswith("エラー: ")


def test_フォルダを渡すと終了コード2(tmp_path, capsys):
    d = tmp_path / "dir.pptx"
    d.mkdir()
    rc, out, _ = run(capsys, "pptx-extract", str(d))
    assert (rc, out) == (2, "")


@pytest.mark.parametrize("ext", [".ppt", ".potx", ".pptm"])
def test_pptx以外の拡張子は終了コード2(tmp_path, capsys, ext):
    f = make_deck(tmp_path / f"a{ext}")
    rc, out, _ = run(capsys, "pptx-extract", str(f))
    assert (rc, out) == (2, "")


def test_空ファイルは終了コード2(tmp_path, capsys):
    f = tmp_path / "empty.pptx"
    f.write_bytes(b"")
    rc, out, _ = run(capsys, "pptx-extract", str(f))
    assert (rc, out) == (2, "")


def test_先頭がOLE形式なら暗号化のメッセージ(tmp_path, capsys):
    f = tmp_path / "enc.pptx"
    f.write_bytes(OLE_HEAD + b"\0" * 512)
    rc, out, err = run(capsys, "pptx-extract", str(f))
    assert (rc, out) == (2, "")
    assert "パスワード" in err


def test_zipでない壊れたファイルは終了コード2(tmp_path, capsys):
    f = tmp_path / "bad.pptx"
    f.write_bytes(b"not a zip")
    rc, out, err = run(capsys, "pptx-extract", str(f))
    assert (rc, out) == (2, "")
    assert "パスワード" not in err


def test_拡張子の大文字小文字は区別しない(tmp_path, capsys):
    f = make_deck(tmp_path / "deck.PPTX")
    rc, out, _ = run(capsys, "pptx-extract", str(f))
    assert rc == 0
    assert out.splitlines()[0] == "# deck.PPTX"


def test_5分類のメッセージは互いに違う(tmp_path, capsys):
    msgs = set()
    for name, f in _broken(tmp_path):
        if name == "フォルダ":
            continue
        rc, out, err = run(capsys, "pptx-extract", str(f))
        assert (rc, out) == (2, ""), name
        msgs.add(err)
    assert len(msgs) == 5


# --- スライドの見出し・題・本文 ---------------------------------------------------------------

_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _slide(prs, layout=1):
    return prs.slides.add_slide(prs.slide_layouts[layout])


def _extract(tmp_path, capsys, build) -> str:
    f = make_deck(tmp_path / "deck.pptx", build)
    rc, out, err = run(capsys, "pptx-extract", str(f))
    assert (rc, err) == (0, "")
    return out


def _add_ph(slide, text: str, ph_type: str):
    """スライド側に footer・date・slide number のプレースホルダーを足す。"""
    from lxml import etree
    from pptx.util import Emu

    box = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(100000), Emu(100000))
    box.text_frame.text = text
    ph = etree.SubElement(box._element.nvSpPr.nvPr, f"{{{_NS_P}}}ph")
    ph.set("type", ph_type)


def test_スライドごとに見出しと題が出る(tmp_path, capsys):
    def build(prs):
        s = _slide(prs)
        s.shapes.title.text = "売上の推移"
        s.placeholders[1].text_frame.text = "前年比 +10%"

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines() == ["# deck.pptx", "", "## スライド 1: 売上の推移", "- 前年比 +10%"]


def test_題の図形は本文に重ねて出ない(tmp_path, capsys):
    def build(prs):
        s = _slide(prs)
        s.shapes.title.text = "唯一の題"

    assert _extract(tmp_path, capsys, build).count("唯一の題") == 1


def test_題のないスライドは題なしと出る(tmp_path, capsys):
    out = _extract(tmp_path, capsys, lambda prs: _slide(prs, 6))
    assert "## スライド 1: （題なし）" in out


def test_中央タイトルも題として読み_複数段落は半角スペースでつなぐ(tmp_path, capsys):
    def build(prs):
        s = _slide(prs, 0)
        s.shapes.title.text_frame.text = "第1行\n第2行"
        s.placeholders[1].text_frame.text = "副題"

    out = _extract(tmp_path, capsys, build)
    assert "## スライド 1: 第1行 第2行" in out
    assert "- 副題" in out


def test_箇条書きの階層はインデントで出る(tmp_path, capsys):
    def build(prs):
        s = _slide(prs)
        tf = s.placeholders[1].text_frame
        tf.text = "a"
        for text, level in (("b", 1), ("c", 2), ("", 0), ("d", 0)):
            p = tf.add_paragraph()
            p.text = text
            p.level = level

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-4:] == ["- a", "  - b", "    - c", "- d"]


def test_非表示スライドは読まず番号は元のまま(tmp_path, capsys):
    def build(prs):
        for n in (1, 2, 3):
            _slide(prs).shapes.title.text = f"題{n}"
        prs.slides[1]._element.set("show", "0")

    out = _extract(tmp_path, capsys, build)
    assert "## スライド 1: 題1" in out
    assert "題2" not in out
    assert "## スライド 3: 題3" in out


def test_ノートとマスターとスライド上のフッター日付番号は出ない(tmp_path, capsys):
    def build(prs):
        s = _slide(prs)
        s.shapes.title.text = "題"
        s.notes_slide.notes_text_frame.text = "ノートの文字"
        for text, t in (("フッター文字", "ftr"), ("日付文字", "dt"), ("番号文字", "sldNum")):
            _add_ph(s, text, t)

    out = _extract(tmp_path, capsys, build)
    for word in ("ノートの文字", "フッター文字", "日付文字", "番号文字", "Click to edit"):
        assert word not in out


def test_グループ内の図形の文字も読む(tmp_path, capsys):
    from pptx.util import Emu

    def build(prs):
        s = _slide(prs, 6)
        g = s.shapes.add_group_shape()
        g.shapes.add_textbox(Emu(0), Emu(0), Emu(100000), Emu(100000)).text_frame.text = "グループの中"

    assert "- グループの中" in _extract(tmp_path, capsys, build)


def test_画像とSmartArt相当の図形は出力に現れず例外にもならない(tmp_path, capsys):
    from lxml import etree
    from PIL import Image

    png = tmp_path / "p.png"
    Image.new("RGB", (4, 4)).save(png)

    def build(prs):
        s = _slide(prs, 6)
        s.shapes.add_picture(str(png), 0, 0)
        frame = etree.fromstring(
            f'<p:graphicFrame xmlns:p="{_NS_P}" xmlns:a="{_NS_A}"><p:nvGraphicFramePr>'
            '<p:cNvPr id="99" name="SmartArt"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
            '<p:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></p:xfrm><a:graphic>'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram"/>'
            "</a:graphic></p:graphicFrame>"
        )
        s.shapes._spTree.append(frame)

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines() == ["# deck.pptx", "", "## スライド 1: （題なし）"]


# --- 表 ----------------------------------------------------------------------------------------


def _table(shapes, rows, into=None):
    """rows（文字列の二次元リスト）を持つ表を足して、python-pptx の Table を返す。

    into にグループを渡すと、足した表をそのグループの中へ移す（グループには add_table がない）。
    """
    from pptx.util import Emu

    frame = shapes.add_table(len(rows), len(rows[0]), Emu(0), Emu(0), Emu(3000000), Emu(1000000))
    t = frame.table
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            t.cell(r, c).text = text
    if into is not None:
        into._element.append(frame._element)
    return t


def test_表はMarkdownの表になる(tmp_path, capsys):
    def build(prs):
        _table(_slide(prs, 6).shapes, [["項目", "値"], ["A", "1"]])

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-3:] == ["| 項目 | 値 |", "|---|---|", "| A | 1 |"]


def test_セルの結合は結合元の値を1回だけ出す(tmp_path, capsys):
    def build(prs):
        t = _table(_slide(prs, 6).shapes, [["見出し", ""], ["x", "y"]])
        t.cell(0, 0).merge(t.cell(0, 1))

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-3:] == ["| 見出し |  |", "|---|---|", "| x | y |"]


def test_セル内の改行はbrに_縦棒はエスケープする(tmp_path, capsys):
    def build(prs):
        _table(_slide(prs, 6).shapes, [["h", "h2"], ["a\nb|c", "d"]])

    assert r"| a<br>b\|c | d |" in _extract(tmp_path, capsys, build)


def test_グループ内の表も読む(tmp_path, capsys):
    def build(prs):
        slide = _slide(prs, 6)
        _table(slide.shapes, [["h", "h2"], ["グループ内", "1"]], into=slide.shapes.add_group_shape())

    assert "| グループ内 | 1 |" in _extract(tmp_path, capsys, build)


# --- グラフ ------------------------------------------------------------------------------------


def _chart(shapes, chart_type, data, into=None):
    from pptx.util import Emu

    frame = shapes.add_chart(chart_type, Emu(0), Emu(0), Emu(3000000), Emu(2000000), data)
    if into is not None:
        into._element.append(frame._element)
    return frame.chart


def _category_data(series):
    from pptx.chart.data import CategoryChartData

    d = CategoryChartData()
    d.categories = ["1Q", "2Q"]
    for name, values in series:
        d.add_series(name, values)
    return d


def test_棒グラフはカテゴリを行_系列を列にした表で出る(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        data = _category_data([("売上", (100, 120)), ("利益", (20, 30.5))])
        _chart(_slide(prs, 6).shapes, XL_CHART_TYPE.COLUMN_CLUSTERED, data)

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-5:] == [
        "[グラフ: 棒]",
        "| カテゴリ | 売上 | 利益 |",
        "|---|---|---|",
        "| 1Q | 100 | 20 |",
        "| 2Q | 120 | 30.5 |",
    ]


def test_散布図は系列ごとにXとYの組の表になる(tmp_path, capsys):
    from pptx.chart.data import XyChartData
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        d = XyChartData()
        s = d.add_series("実績")
        s.add_data_point(1, 2)
        s.add_data_point(3, 4.5)
        _chart(_slide(prs, 6).shapes, XL_CHART_TYPE.XY_SCATTER, d)

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-6:] == [
        "[グラフ: 散布図]",
        "系列: 実績",
        "| X | Y |",
        "|---|---|",
        "| 1 | 2 |",
        "| 3 | 4.5 |",
    ]


def test_値が空のグラフはエラーにせず印を出して続ける(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        s = _slide(prs, 6)
        _chart(s.shapes, XL_CHART_TYPE.COLUMN_CLUSTERED, _category_data([("空", (None, None))]))
        c = _chart(s.shapes, XL_CHART_TYPE.LINE, _category_data([("消す", (1, 2))]))
        for ser in c._chartSpace.xpath(".//c:ser"):  # 系列が 0 件のグラフ
            ser.getparent().remove(ser)
        _slide(prs).shapes.title.text = "次のスライド"

    out = _extract(tmp_path, capsys, build)
    assert out.count("[グラフ: 値を読めませんでした]") == 2
    assert "## スライド 2: 次のスライド" in out


def test_対応表にない種類はpython_pptxの名前のまま(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        _chart(_slide(prs, 6).shapes, XL_CHART_TYPE.RADAR, _category_data([("a", (1, 2))]))

    assert "[グラフ: RADAR]" in _extract(tmp_path, capsys, build)


def test_グラフのタイトルは出ない(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        c = _chart(_slide(prs, 6).shapes, XL_CHART_TYPE.PIE, _category_data([("a", (1, 2))]))
        c.has_title = True
        c.chart_title.text_frame.text = "秘密のタイトル"

    out = _extract(tmp_path, capsys, build)
    assert "[グラフ: 円]" in out
    assert "秘密のタイトル" not in out


def test_グループ内のグラフも読む(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        s = _slide(prs, 6)
        _chart(s.shapes, XL_CHART_TYPE.LINE, _category_data([("a", (1, 2))]), into=s.shapes.add_group_shape())

    assert "[グラフ: 折れ線]" in _extract(tmp_path, capsys, build)


# --- 全体 --------------------------------------------------------------------------------------


def test_固定のデッキの出力が期待するMarkdownと一致する(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Emu

    def build(prs):
        s1 = _slide(prs)
        s1.shapes.title.text = "概要"
        tf = s1.placeholders[1].text_frame
        tf.text = "a"
        tf.add_paragraph().text = "b"
        tf.paragraphs[1].level = 1
        g = s1.shapes.add_group_shape()
        g.shapes.add_textbox(Emu(0), Emu(0), Emu(100000), Emu(100000)).text_frame.text = "G"
        _slide(prs).shapes.title.text = "非表示"
        prs.slides[1]._element.set("show", "0")
        s3 = _slide(prs, 5)
        s3.shapes.title.text = "数値"
        _table(s3.shapes, [["項目", "値"], ["A", "1"]])
        _chart(s3.shapes, XL_CHART_TYPE.COLUMN_CLUSTERED, _category_data([("s", (5, 6))]))

    assert _extract(tmp_path, capsys, build) == (
        "# deck.pptx\n"
        "\n"
        "## スライド 1: 概要\n"
        "- a\n"
        "  - b\n"
        "- G\n"
        "\n"
        "## スライド 3: 数値\n"
        "| 項目 | 値 |\n"
        "|---|---|\n"
        "| A | 1 |\n"
        "[グラフ: 棒]\n"
        "| カテゴリ | s |\n"
        "|---|---|\n"
        "| 1Q | 5 |\n"
        "| 2Q | 6 |\n"
    )


# --- 最終レビューの指摘（読めないグラフ・散布図の X・段落内の改行） -------------------------------


def _qn(tag: str) -> str:
    from pptx.oxml.ns import qn

    return qn(tag)


def test_python_pptxが扱えない種類のグラフでも全体は落ちず印を出して続ける(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        s = _slide(prs, 6)
        c = _chart(s.shapes, XL_CHART_TYPE.COLUMN_CLUSTERED, _category_data([("a", (1, 2))]))
        for el in c._chartSpace.xpath(".//c:barChart"):  # 3-D 棒グラフ相当（python-pptx に要素クラスがない）
            el.tag = _qn("c:bar3DChart")
        _slide(prs).shapes.title.text = "次のスライド"

    out = _extract(tmp_path, capsys, build)
    assert "[グラフ: 値を読めませんでした]" in out
    assert "## スライド 2: 次のスライド" in out


def test_系列ごとに点の数が違っても落ちず足りない所は空になる(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        c = _chart(
            _slide(prs, 6).shapes,
            XL_CHART_TYPE.COLUMN_CLUSTERED,
            _category_data([("長い", (1, 2)), ("短い", (3, 4))]),
        )
        second = c._chartSpace.xpath(".//c:ser")[1]
        second.xpath(".//c:val//c:ptCount")[0].set("val", "1")
        for pt in second.xpath(".//c:val//c:pt[@idx='1']"):
            pt.getparent().remove(pt)

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-2:] == ["| 1Q | 1 | 3 |", "| 2Q | 2 |  |"]


def test_系列に値の要素がなくても落ちない(tmp_path, capsys):
    from pptx.enum.chart import XL_CHART_TYPE

    def build(prs):
        c = _chart(
            _slide(prs, 6).shapes,
            XL_CHART_TYPE.COLUMN_CLUSTERED,
            _category_data([("あり", (1, 2)), ("なし", (3, 4))]),
        )
        for val in c._chartSpace.xpath(".//c:ser")[1].xpath("./c:val"):
            val.getparent().remove(val)

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-2:] == ["| 1Q | 1 |  |", "| 2Q | 2 |  |"]


def _scatter(prs):
    from pptx.chart.data import XyChartData
    from pptx.enum.chart import XL_CHART_TYPE

    d = XyChartData()
    s = d.add_series("実績")
    s.add_data_point(1, 2)
    s.add_data_point(3, 4)
    return _chart(_slide(prs, 6).shapes, XL_CHART_TYPE.XY_SCATTER, d)


def test_散布図のXが文字列でも落ちずそのまま出る(tmp_path, capsys):
    def build(prs):
        c = _scatter(prs)
        c._chartSpace.xpath(".//c:xVal//c:v")[0].text = "東京"

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-2:] == ["| 東京 | 2 |", "| 3 | 4 |"]


def test_散布図のXに欠けた点があっても組がずれない(tmp_path, capsys):
    def build(prs):
        c = _scatter(prs)
        for pt in c._chartSpace.xpath(".//c:xVal//c:pt[@idx='0']"):
            pt.getparent().remove(pt)

    out = _extract(tmp_path, capsys, build)
    assert out.splitlines()[-2:] == ["|  | 2 |", "| 3 | 4 |"]


def test_段落の中の改行は題も本文も半角スペースになる(tmp_path, capsys):
    def build(prs):
        s = _slide(prs)
        p = s.shapes.title.text_frame.paragraphs[0]
        p.add_run().text = "上"
        p.add_line_break()
        p.add_run().text = "下"
        q = s.placeholders[1].text_frame.paragraphs[0]
        q.add_run().text = "本文1"
        q.add_line_break()
        q.add_run().text = "本文2"

    out = _extract(tmp_path, capsys, build)
    assert "\x0b" not in out
    assert "## スライド 1: 上 下" in out
    assert "- 本文1 本文2" in out
