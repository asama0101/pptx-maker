# ruff: noqa: S101  # pytest の assert
"""案の選択ページでデザイン方向を選べる: 設計図への反映（choices-import）。"""

import json
import re
from pathlib import Path

import pytest
from pptx_maker import choices, cli, design_colors, directions, initdir, paths, review_page

from tests._flow import copied
from tests.test_review_page_render import CLIP, _slides

NAMES = {"R1": "標準型", "R2": "比較表中心型", "R3": "図解中心型"}
CANDIDATES = "- デザイン方向の候補: " + ", ".join(f"{k}={v}" for k, v in NAMES.items()) + "\n"
BLUE_RED = "- 基調色: #0E6B73\n- 強調色: #C0392B\n"


def _work(tmp_path: Path, design: str = CANDIDATES + "- デザイン方向: 標準型\n" + BLUE_RED) -> Path:
    """全ページに R1〜R3 の 3 案がある作業フォルダ（候補の行があると、全候補の案が要る）。"""
    base = tmp_path / "out" / "pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    s = work / "slides"
    s.mkdir(exist_ok=True)
    for name, text in _slides().items():
        if name.endswith("-R1.html"):
            nn = name[:2]
            for i, key in enumerate(NAMES):
                body = text.replace('<section class="slide"', f'<section class="slide" data-variant="案{i}"', 1)
                (s / f"{nn}-{key}.html").write_text(body, encoding="utf-8")
    (work / "design.md").write_text("# 設計図\n\n## 資料全体\n" + design, encoding="utf-8")
    return work


def _import(tmp_path, work, pick="R1", **over):
    f = tmp_path / "paste.txt"
    f.write_text(copied(work, {"02": {"pick": pick, "status": "saved", "comment": ""}}, **over), encoding="utf-8")
    return cli.entry(["choices-import", str(work), "--file", str(f)])


def test_choices_import_writes_direction_name_to_design(tmp_path, capsys):
    work = _work(tmp_path)
    capsys.readouterr()
    assert _import(tmp_path, work, direction="R2") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["direction"] == {"key": "R2", "name": "比較表中心型"}
    assert directions.current(work) == "比較表中心型"
    assert (work / "choices" / "02.json").is_file()


def test_choices_import_without_direction_leaves_design_unchanged(tmp_path, capsys):
    work = _work(tmp_path)
    before = (work / "design.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert _import(tmp_path, work) == 0
    assert "direction" not in json.loads(capsys.readouterr().out)
    assert directions.current(work) == "標準型"
    assert (work / "design.md").read_text(encoding="utf-8") == before


def test_choices_import_rejects_direction_outside_candidates(tmp_path, capsys):
    work = _work(tmp_path)
    capsys.readouterr()
    assert _import(tmp_path, work, direction="R4") == 2
    err = capsys.readouterr().err
    assert "R4" in err
    assert "R1" in err
    assert directions.current(work) == "標準型"
    assert not (work / "choices").exists()


def test_choices_import_rejects_direction_without_candidate_line(tmp_path, capsys):
    work = _work(tmp_path, design="- デザイン方向: 標準型\n")
    # 候補の行がなければ、案は R1・R2 だけでよい
    (work / "slides" / "02-R3.html").unlink()
    (work / "slides" / "01-R3.html").unlink()
    (work / "slides" / "03-R3.html").unlink()
    capsys.readouterr()
    assert _import(tmp_path, work, direction="R1") == 2
    assert capsys.readouterr().err
    assert directions.current(work) == "標準型"
    assert not (work / "choices").exists()


def test_choices_import_color_and_direction_together(tmp_path, capsys):
    work = _work(tmp_path)
    color = {"name": "紺とオレンジ", "accent": "#1F3A5F", "emphasis": "#D9730D"}
    capsys.readouterr()
    assert _import(tmp_path, work, direction="R3", color=color) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["color"] == color
    assert out["direction"] == {"key": "R3", "name": "図解中心型"}
    assert design_colors._read_design(work) == ("#1F3A5F", ["#D9730D"])  # noqa: SLF001
    assert directions.current(work) == "図解中心型"


def test_choices_import_bad_direction_does_not_write_color(tmp_path, capsys):
    work = _work(tmp_path)
    color = {"accent": "#1F3A5F", "emphasis": "#D9730D"}
    capsys.readouterr()
    assert _import(tmp_path, work, direction="R9", color=color) == 2
    assert design_colors._read_design(work) == ("#0E6B73", ["#C0392B"])  # noqa: SLF001
    assert directions.current(work) == "標準型"
    assert not (work / "choices").exists()


def test_choices_import_invalid_selection_does_not_write_direction(tmp_path, capsys):
    work = _work(tmp_path)
    capsys.readouterr()
    assert _import(tmp_path, work, pick="R9", direction="R2") == 2
    assert directions.current(work) == "標準型"
    assert not (work / "choices").exists()


# --- 埋め込むデータ ---


def _dirs_data(html: str):
    m = re.search(r'<script type="application/json" id="rv-dirs">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def test_build_embeds_directions_null_without_candidate_line(tmp_path):
    work = _work(tmp_path, design="- デザイン方向: 標準型\n")
    html = review_page.build(work, measure=False).read_text(encoding="utf-8")
    assert _dirs_data(html) is None
    assert 'id="rv-dir-panel"' not in html  # パネルは JS が DIRS のあるときだけ作る


def test_build_embeds_names_and_current(tmp_path):
    work = _work(tmp_path, design=CANDIDATES + "- デザイン方向: 比較表中心型\n")
    data = _dirs_data(review_page.build(work, measure=False).read_text(encoding="utf-8"))
    assert data == {"names": NAMES, "current": "R2"}


def test_build_current_is_null_when_design_name_is_not_a_candidate(tmp_path):
    work = _work(tmp_path, design=CANDIDATES + "- デザイン方向: 知らない型\n")
    data = _dirs_data(review_page.build(work, measure=False).read_text(encoding="utf-8"))
    assert data == {"names": NAMES, "current": None}


# --- ブラウザ ---


@pytest.fixture
def page(tmp_path):
    from playwright.sync_api import sync_playwright

    work = _work(tmp_path)
    review_page.build(work, measure=False)
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(CLIP)
        pg.goto((work / "review.html").as_uri())
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 12")  # 3 ページ x (大 1 + 縮小 3)
        pg.errors = errors
        pg.work = work
        yield pg


def _share(pg):
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    return json.loads(pg.evaluate("window.__copied"))


def _big(pg, nn):
    return pg.get_attribute(f"#pg-{nn} .rvbig .rvf", "data-k")


@pytest.mark.slow
def test_panel_marks_initial_direction_from_design(page):
    btns = page.locator("#rv-dir-panel button[data-dir]")
    assert btns.count() == 3
    assert btns.nth(1).inner_text() == "R2 比較表中心型"
    assert page.get_attribute("#rv-dir-panel button[data-dir='R1']", "aria-pressed") == "true"  # 現在の方向は標準型
    assert _big(page, "01") == "R1"
    assert page.errors == []


@pytest.mark.slow
def test_switch_changes_unpicked_pages_only(page):
    page.click("#pg-02 .rvthumb[data-k='R3']")
    page.click("#rv-dir-panel button[data-dir='R2']")
    assert _big(page, "01") == "R2"
    assert _big(page, "02") == "R3"
    assert _big(page, "03") == "R2"
    assert page.get_attribute("#rv-dir-panel button[data-dir='R2']", "aria-pressed") == "true"
    assert page.get_attribute("#rv-dir-panel button[data-dir='R1']", "aria-pressed") == "false"
    pages = _share(page)["pages"]
    assert pages["02"]["pick"] == "R3"
    assert "01" not in pages  # 切り替えでは pick を書かない


@pytest.mark.slow
def test_variant_labels_include_direction_name(page):
    assert "R2 比較表中心型" in page.inner_text("#pg-01 .rvthumb[data-k='R2']")


@pytest.mark.slow
def test_approve_without_explicit_pick_confirms_shown_variant(page):
    page.click("#rv-dir-panel button[data-dir='R2']")
    assert page.is_enabled("#pg-01 button[data-act='approve']")
    assert page.text_content("#pg-01 .rvbd") == "未承認"
    page.click("#pg-01 button[data-act='approve']")
    one = _share(page)["pages"]["01"]
    assert one["pick"] == "R2"
    assert one["status"] == "approved"
    page.click("#rv-dir-panel button[data-dir='R3']")  # 承認したページは、確定した案のまま
    assert _big(page, "01") == "R2"


@pytest.mark.slow
def test_comment_still_blocks_approval_with_direction(page):
    page.fill("#pg-01 textarea", "直して")
    assert page.is_disabled("#pg-01 button[data-act='approve']")


def _open(tmp_path, design):
    """指定の設計図でレビューページを開き、(ページ, 後始末の関数) を返す。"""
    from playwright.sync_api import sync_playwright

    work = _work(tmp_path, design=design)
    review_page.build(work, measure=False)
    pw = sync_playwright().start()
    pg = pw.chromium.launch().new_page()
    pg.add_init_script(CLIP)
    pg.goto((work / "review.html").as_uri())
    pg.wait_for_function("document.querySelectorAll('.rvh').length === 12")
    return pg, pw.stop


@pytest.mark.slow
def test_share_omits_direction_when_shown_equals_design_and_not_clicked(page):
    assert "direction" not in _share(page)  # 設計図の現在の方向（標準型 = R1）のまま


@pytest.mark.slow
def test_share_has_direction_when_design_has_no_current_direction(tmp_path):
    pg, stop = _open(tmp_path, CANDIDATES + BLUE_RED)  # 候補に合う デザイン方向: がない
    try:
        shared = _share(pg)
        assert shared["direction"] == "R1"  # 表示中の方向（既定の R1）を書き留める
        assert shared["check"] == choices.checksum(shared["pages"])
    finally:
        stop()


@pytest.mark.slow
def test_share_has_direction_when_design_name_differs_from_shown(tmp_path):
    pg, stop = _open(tmp_path, CANDIDATES + "- デザイン方向: 決定先行型（あとで書く）" + chr(10) + BLUE_RED)
    try:
        assert _share(pg)["direction"] == "R1"
    finally:
        stop()


@pytest.mark.slow
def test_share_has_direction_after_clicking_another(page):
    page.click("#rv-dir-panel button[data-dir='R2']")
    shared = _share(page)
    assert shared["direction"] == "R2"
    assert shared["check"] == choices.checksum(shared["pages"])  # 方向を足しても、ページの検査値は変わらない


@pytest.mark.slow
def test_thumbnail_highlights_shown_direction_unless_picked(page):
    page.click("#pg-02 .rvthumb[data-k='R3']")
    page.click("#rv-dir-panel button[data-dir='R2']")
    assert "on" in page.get_attribute("#pg-01 .rvthumb[data-k='R2']", "class").split()
    assert "on" not in page.get_attribute("#pg-01 .rvthumb[data-k='R1']", "class").split()
    assert "on" in page.get_attribute("#pg-02 .rvthumb[data-k='R3']", "class").split()  # 選んだページは自分の選択
    assert "on" not in page.get_attribute("#pg-02 .rvthumb[data-k='R2']", "class").split()


@pytest.mark.slow
def test_direction_restored_after_reload(page):
    page.click("#rv-dir-panel button[data-dir='R3']")
    page.reload()
    page.wait_for_function("document.querySelectorAll('.rvh').length === 12")
    assert page.get_attribute("#rv-dir-panel button[data-dir='R3']", "aria-pressed") == "true"
    assert _big(page, "01") == "R3"
    assert _share(page)["direction"] == "R3"
