# ruff: noqa: S101  # pytest の assert
"""案の選択ページで配色セットを選べる: 埋め込むデータ、設計図への反映（choices-import）、ブラウザでの切り替え。"""

import json
import re
from pathlib import Path

import pytest
from pptx_maker import choices, cli, color_sets, design_colors, initdir, paths, review_page

from tests._flow import copied
from tests.test_review_page_render import CLIP, _slides

BLUE_RED = "- 基調色: #0E6B73\n- 強調色: #C0392B\n"


def _work(tmp_path: Path, design: str | None = BLUE_RED) -> Path:
    base = tmp_path / "out" / "pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    s = work / "slides"
    s.mkdir(exist_ok=True)
    for name, text in _slides().items():
        (s / name).write_text(text, encoding="utf-8")
    if design is not None:
        (work / "design.md").write_text("# 設計図\n\n## 資料全体\n" + design, encoding="utf-8")
    return work


def _color_data(html: str):
    m = re.search(r'<script type="application/json" id="rv-color">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


# --- 設計図への書き込み ---


def test_set_colors_replaces_existing_lines(tmp_path):
    work = _work(tmp_path)
    design_colors.set_colors(work, "#1F3A5F", ["#D9730D"])
    text = (work / "design.md").read_text(encoding="utf-8")
    assert text.count("基調色") == 1
    assert design_colors._read_design(work) == ("#1F3A5F", ["#D9730D"])  # noqa: SLF001


def test_set_colors_adds_lines_when_missing_and_keeps_other_text(tmp_path):
    work = _work(tmp_path, design="- 求める決定: 承認\n")
    design_colors.set_colors(work, "#1F3A5F", ["#D9730D"])
    text = (work / "design.md").read_text(encoding="utf-8")
    assert "- 求める決定: 承認" in text
    assert design_colors._read_design(work) == ("#1F3A5F", ["#D9730D"])  # noqa: SLF001


def test_set_colors_creates_design_md_when_absent(tmp_path):
    work = _work(tmp_path, design=None)
    design_colors.set_colors(work, "#1F3A5F", ["#D9730D"])
    assert design_colors._read_design(work) == ("#1F3A5F", ["#D9730D"])  # noqa: SLF001


def test_set_colors_rejects_bad_hex(tmp_path):
    work = _work(tmp_path)
    with pytest.raises(ValueError, match="#RRGGBB"):
        design_colors.set_colors(work, "navy", ["#D9730D"])


# --- 取り込み ---


def _paste(work, color):
    return copied(work, {"02": {"pick": "R1", "status": "saved", "comment": ""}}, color=color)


def test_choices_import_writes_color_to_design(tmp_path, capsys):
    work = _work(tmp_path)
    f = tmp_path / "paste.txt"
    f.write_text(_paste(work, {"name": "紺とオレンジ", "accent": "#1F3A5F", "emphasis": "#D9730D"}), encoding="utf-8")
    capsys.readouterr()
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["color"] == {"name": "紺とオレンジ", "accent": "#1F3A5F", "emphasis": "#D9730D"}
    assert design_colors._read_design(work) == ("#1F3A5F", ["#D9730D"])  # noqa: SLF001


def test_choices_import_without_color_leaves_design_and_output_unchanged(tmp_path, capsys):
    work = _work(tmp_path)
    before = (work / "design.md").read_text(encoding="utf-8")
    f = tmp_path / "paste.txt"
    f.write_text(copied(work, {"02": {"pick": "R1", "status": "saved", "comment": ""}}), encoding="utf-8")
    capsys.readouterr()
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 0
    assert json.loads(capsys.readouterr().out) == {"comments": []}
    assert (work / "design.md").read_text(encoding="utf-8") == before


def test_choices_import_rejects_bad_color_without_writing_anything(tmp_path, capsys):
    work = _work(tmp_path)
    f = tmp_path / "paste.txt"
    f.write_text(_paste(work, {"name": "x", "accent": "navy", "emphasis": "#D9730D"}), encoding="utf-8")
    capsys.readouterr()
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 2
    assert "#RRGGBB" in capsys.readouterr().err
    assert design_colors._read_design(work) == ("#0E6B73", ["#C0392B"])  # noqa: SLF001
    assert not (work / "choices").exists()  # 色が不正なら選択も書かない（全部か、何もしないか）


def test_choices_import_配色の書き込みに失敗したら選択も書かず再取り込みできる(tmp_path, capsys, monkeypatch):
    work = _work(tmp_path)
    f = tmp_path / "paste.txt"
    f.write_text(_paste(work, {"name": "x", "accent": "#1F3A5F", "emphasis": "#D9730D"}), encoding="utf-8")
    real = design_colors.set_colors

    def locked(*a, **k):
        raise OSError("design.md が使用中です")

    monkeypatch.setattr(design_colors, "set_colors", locked)
    capsys.readouterr()
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 2
    assert "design.md" in capsys.readouterr().err
    assert not (work / "choices").exists()  # 選択だけ反映された状態にならない（指紋が変わって再取り込みを断られない）
    monkeypatch.setattr(design_colors, "set_colors", real)
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 0  # そのまま貼り直せる
    assert design_colors._read_design(work) == ("#1F3A5F", ["#D9730D"])  # noqa: SLF001


def test_choices_import_選択が不正なら配色も書かない(tmp_path, capsys):
    work = _work(tmp_path)
    f = tmp_path / "paste.txt"
    bad = copied(
        work,
        {"02": {"pick": "R9", "status": "saved", "comment": ""}},
        color={"accent": "#1F3A5F", "emphasis": "#D9730D"},
    )
    f.write_text(bad, encoding="utf-8")
    capsys.readouterr()
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 2
    assert design_colors._read_design(work) == ("#0E6B73", ["#C0392B"])  # noqa: SLF001
    assert not (work / "choices").exists()


# --- 埋め込むデータ ---


def test_build_embeds_sets_and_current_color(tmp_path):
    data = _color_data(review_page.build(_work(tmp_path), measure=False).read_text(encoding="utf-8"))
    assert [s["name"] for s in data["sets"]] == [s[0] for s in color_sets.SETS]
    assert data["current"]["name"] == "青緑と赤"
    assert data["current"]["accent"] == "#0E6B73"
    assert data["sets"][0]["vars"]["accent"].startswith("#")
    assert "emphasis" in data["sets"][0]["vars"]


def test_build_current_color_without_design_has_no_set_name(tmp_path):
    data = _color_data(review_page.build(_work(tmp_path, design=None), measure=False).read_text(encoding="utf-8"))
    assert data["current"]["name"] is None
    assert data["current"]["accent"].startswith("#")


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
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        pg.errors = errors
        pg.work = work
        yield pg


def _share(pg):
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    return json.loads(pg.evaluate("window.__copied"))


def _var(pg, name):
    return pg.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('--{name}').trim()")


@pytest.mark.slow
def test_color_panel_marks_current_set_and_shares_no_color_until_changed(page):
    btns = page.locator("#rv-color-panel button[data-set]")
    assert btns.count() == len(color_sets.SETS)
    assert page.locator("#rv-color-panel button[data-set='青緑と赤']").get_attribute("aria-pressed") == "true"
    assert "color" not in _share(page)
    assert page.errors == []


@pytest.mark.slow
def test_choosing_a_set_recolors_the_page_and_adds_color_to_the_shared_json(page):
    before = _var(page, "accent")
    page.click("#rv-color-panel button[data-set='紺とオレンジ']")
    assert _var(page, "accent") != before
    assert page.locator("#rv-color-panel button[data-set='紺とオレンジ']").get_attribute("aria-pressed") == "true"
    shared = _share(page)
    assert shared["color"] == {"name": "紺とオレンジ", "accent": "#1F3A5F", "emphasis": "#D9730D"}
    assert shared["check"] == choices.checksum(shared["pages"])  # 色を足しても、ページの検査値は変わらない
    page.click("#rv-color-panel button[data-set='青緑と赤']")  # 元に戻すと、渡す JSON から色が消える
    assert "color" not in _share(page)


@pytest.mark.slow
def test_chosen_color_survives_reload(page):
    page.click("#rv-color-panel button[data-set='墨と青']")
    page.reload()
    page.wait_for_function("document.querySelectorAll('.rvh').length === 9")
    assert page.locator("#rv-color-panel button[data-set='墨と青']").get_attribute("aria-pressed") == "true"
    assert _share(page)["color"]["name"] == "墨と青"


@pytest.mark.slow
def test_color_panel_stays_visible_while_scrolling(page):
    page.evaluate("document.getElementById('pg-03').scrollIntoView()")
    top = page.evaluate("document.getElementById('rv-color-panel').getBoundingClientRect().top")
    assert page.is_visible("#rv-color-panel")
    assert 0 <= top < 200  # スクロールしても、上部（固定のヘッダー）に残る
