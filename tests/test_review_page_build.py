# ruff: noqa: S101  # pytest の assert
"""案を選ぶページ（review_page.build）のテスト。"""

import json
import re
from pathlib import Path

import pytest
from pptx_maker import choices, cli, initdir, paths, review_page

from tests._flow import copied, write_slide


def _work(tmp_path: Path) -> Path:
    s = tmp_path / "slides"
    s.mkdir()
    for k in ("R1", "R2"):
        (s / f"01-{k}.html").write_text(f'<div class="pp-text">MARK-01{k}</div>', encoding="utf-8")
    for k in ("R1", "R2", "R3"):
        (s / f"02-{k}.html").write_text(f'<div class="pp-text">MARK-02{k}</div>', encoding="utf-8")
    (tmp_path / "theme.css").write_text(":root{--bg:#fff;}", encoding="utf-8")
    (tmp_path / "base.css").write_text(".pp-text{color:red}", encoding="utf-8")
    (tmp_path / "chart-preview.js").write_text("window.__chartPreview=function(){};", encoding="utf-8")
    return tmp_path


def test_contains_every_candidate(tmp_path):
    html = review_page.build(_work(tmp_path)).read_text(encoding="utf-8")
    for m in ("MARK-01R1", "MARK-01R2", "MARK-02R1", "MARK-02R2", "MARK-02R3"):
        assert m in html
    assert (tmp_path / "review.html").exists()


def test_page_has_comment_box_share_button_and_no_artifact_runtime(tmp_path):
    html = review_page.build(_work(tmp_path)).read_text(encoding="utf-8")
    assert "<title>スライド案の選択</title>" in html
    assert "<textarea" in html or 'h("textarea"' in html
    assert 'id="share"' in html
    assert '"pptx-maker-review"' in html
    for f in ("pick", "status", "comment", "approved", "saved"):
        assert f in html
    assert "window.claude" not in html
    assert "ArtifactData" not in html


def test_initial_state_comes_from_choices_files(tmp_path):
    work = _work(tmp_path)
    choices.import_text(work, copied(work, {"02": {"pick": "R3", "status": "saved", "comment": "直す</script>"}}))
    html = review_page.build(work).read_text(encoding="utf-8")
    state = json.loads(re.search(r"^var INIT = (.*);$", html, re.M).group(1))
    assert state["02"]["pick"] == "R3"
    assert state["02"]["comment"] == "直す</script>"
    assert "直す</script>" not in html  # <script> の中で終わりを見失わせない


def test_page_embeds_the_current_stamp_and_checksum_code(tmp_path):
    work = _work(tmp_path)
    html = review_page.build(work).read_text(encoding="utf-8")
    assert f'var STAMP = "{choices.stamp(work)}";' in html
    assert (
        "fnv(JSON.stringify(pages))" in html
    )  # choices.checksum と同じ計算（ブラウザでの突き合わせは render のテスト）


def test_initial_state_is_empty_without_choices(tmp_path):
    html = review_page.build(_work(tmp_path)).read_text(encoding="utf-8")
    assert re.search(r"^var INIT = \{\};$", html, re.M)


def test_declares_no_external_loads(tmp_path):
    html = review_page.build(_work(tmp_path)).read_text(encoding="utf-8")
    assert not re.search(r"<script[^>]+src=", html)
    assert not re.search(r"<link\b", html)
    assert "http://" not in html
    assert "https://" not in html


def test_fragment_cannot_break_out_of_script(tmp_path):
    work = _work(tmp_path)
    write_slide(work / "slides", "01", "<div></script><b>EVIL</b></div>")
    html = review_page.build(work).read_text(encoding="utf-8")
    assert "</script><b>EVIL" not in html


def test_missing_asset_is_error(tmp_path):
    work = _work(tmp_path)
    (work / "base.css").unlink()
    with pytest.raises(ValueError, match="base.css"):
        review_page.build(work)


def _page_data(html: str) -> list:
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


def test_shadow_css_has_theme_base_and_host_font(tmp_path):
    work = _work(tmp_path)
    (work / "theme.css").write_text(':root{--bg:#fff;}\n.slide[data-layout="cover"]{--bg:#123456;}', encoding="utf-8")
    html = review_page.build(work).read_text(encoding="utf-8")
    css = json.loads(re.search(r"^var BASE = (.*);$", html, re.M).group(1))
    # 表紙の色の規則と base.css は shadow root の中に要る（文書の <style> は shadow の中に届かない）
    assert '.slide[data-layout="cover"]{--bg:#123456;}' in css
    assert ".pp-text{color:red}" in css
    assert re.search(r":host\s*\{[^}]*font-family:\s*'BIZ UDPGothic'", css)
    # chart-preview.js が document の :root から変数を読むので、文書側にもテーマを残す
    assert html.index(":root{--bg:#fff;}") < html.index("var BASE")
    assert "adoptedStyleSheets" in html


def test_placeholder_in_fragment_is_not_substituted(tmp_path):
    work = _work(tmp_path)
    write_slide(work / "slides", "01", '<div class="pp-text">__BASE__ __CHART__ __STATE__ __THEME__</div>')
    html = review_page.build(work).read_text(encoding="utf-8")
    assert _page_data(html)[0][1]["R1"] == '<div class="pp-text">__BASE__ __CHART__ __STATE__ __THEME__</div>'


def test_variant_label_is_shown(tmp_path):
    work = _work(tmp_path)
    s = work / "slides"
    (s / "02-R1.html").write_text('<section class="slide" data-variant="自由設計｜左右の対比">x</section>', "utf-8")
    (s / "02-R2.html").write_text('<section class="slide" data-variant="&lt;縦&gt;の流れ">x</section>', "utf-8")
    html = review_page.build(work).read_text(encoding="utf-8")
    pages = _page_data(html)
    assert pages[0][2] == {"R1": "", "R2": ""}
    assert pages[1][2] == {"R1": "左右の対比", "R2": "<縦>の流れ", "R3": ""}


def test_page_title_comes_from_fragment(tmp_path):
    work = _work(tmp_path)
    s = work / "slides"
    write_slide(
        s, "01", '<section class="slide"><div class="pp-text" data-ph="title">表紙の<br>題 &amp; 副</div></section>'
    )
    for k in ("R1", "R2", "R3"):
        (s / f"02-{k}.html").write_text(
            '<section class="slide"><div class="pp-text" data-role="head">ヘッド</div>'
            '<div class="pp-text" data-role="title"><span>とても長い題で二十四文字を</span>'
            "超えてしまうページの題です</div>"
            "</section>",
            "utf-8",
        )
    write_slide(s, "03", '<section class="slide"><div class="pp-text">題なし</div></section>')
    pages = _page_data(review_page.build(work).read_text(encoding="utf-8"))
    assert [p[3] for p in pages] == ["表紙の題 & 副", "とても長い題で二十四文字を超えてしまうページの…", ""]


def _cli(capsys, *argv):
    capsys.readouterr()
    rc = cli.entry(["review-page", *argv])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.fixture
def deck(tmp_path):
    base = tmp_path / "out" / "pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    write_slide(work / "slides", "01", '<section class="slide">ONE</section>')
    return work


def test_cli_review_page_prints_path(deck, capsys):
    rc, out, err = _cli(capsys, str(deck))
    assert rc == 0
    assert json.loads(out)["path"] == str(deck / "review.html")
    assert (deck / "review.html").is_file()
    assert err == ""


def test_review_page_prints_warnings_and_succeeds(deck, capsys):
    """文字だけの案があっても警告を出すだけで、終了コードは 0。表紙（script.md の cover）は免除。"""
    (deck / "script.md").write_text("## S01 表紙\n- layout: cover\n", encoding="utf-8")
    write_slide(deck / "slides", "02", '<div class="pp-text">x</div>', '<div class="pp-chart"></div>')
    rc, out, _ = _cli(capsys, str(deck), "--no-measure")  # 測定の通知は別のテストで見る
    assert rc == 0
    assert json.loads(out)["warnings"] == ["02-R1: 図・絵・表・グラフが主役になっていません"]


def test_cli_review_page_without_slides_dir(deck, capsys):
    (deck / "slides" / "01-R1.html").unlink()
    (deck / "slides" / "01-R2.html").unlink()
    (deck / "slides").rmdir()
    rc, out, err = _cli(capsys, str(deck))
    assert rc == 2
    assert err.startswith("エラー:")
    assert "slides" in err
    assert out == ""


def test_cli_review_page_with_bad_candidate_name(deck, capsys):
    (deck / "slides" / "02-B.html").write_text("<section>x</section>", encoding="utf-8")
    rc, _, err = _cli(capsys, str(deck))
    assert rc == 2
    assert err.startswith("エラー:")
    assert "02-B.html" in err
    assert not (deck / "review.html").exists()


def test_html_comment_open_is_neutralized_in_embedded_data(tmp_path):
    work = _work(tmp_path)
    write_slide(work / "slides", "01", "<div><!--<b>x</div>")
    html = review_page.build(work).read_text(encoding="utf-8")
    raw = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    assert "<!--" not in raw
    assert _page_data(html)[0][1]["R1"] == "<div><!--<b>x</div>"
