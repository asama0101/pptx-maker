# ruff: noqa: S101  # pytest の assert
"""案を選ぶページ（review.html）のルール表示: 埋め込むデータ（build）と、タブ・ルール一覧・縦読み（ブラウザ）。"""

import json
import re
from pathlib import Path

import pytest
from pptx_maker import candidates, choices, initdir, paths, review_page

from tests._flow import copied
from tests.test_review_page_render import CLIP, _slides

SCRIPT = (
    "# 題\n- 論点:\n  - ① 現状\n  - ② 効果\n\n"
    "## S01 表紙\n- layout: cover\n- ヘッドメッセージ: 表紙\n\n"
    "## S02 グラフの題\n- layout: chart\n- 題: 件数の推移\n"
    "- ヘッドメッセージ: 導入により月次の集計作業が半分に縮むため、来期の人員計画を見直す必要がある\n\n"
    "## S03 裏表紙\n- layout: closing\n- ヘッドメッセージ: ご承認ください\n- 本文: ①現状 ②効果\n"
)
DESIGN = (
    "## 台帳\n| No | ヘッドメッセージ（ヘッド） | 文型 | 上位への集約 | 直前からの接続語 | 本体の型 | 論点 |\n"
    "|---|---|---|---|---|---|---|\n| S02 | 見出し | 提言 | 集約 | なぜなら | グラフ | ① |\n"
)


def _rules_data(html: str):
    m = re.search(r'<script type="application/json" id="rv-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def _work(tmp_path: Path, script: str | None = SCRIPT, design: str | None = DESIGN) -> Path:
    base = tmp_path / "out" / "pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    s = work / "slides"
    s.mkdir(exist_ok=True)
    for name, text in _slides().items():
        (s / name).write_text(text, encoding="utf-8")
    if script is not None:
        (work / "script.md").write_text(script, encoding="utf-8")
    if design is not None:
        (work / "design.md").write_text(design, encoding="utf-8")
    return work


def test_build_embeds_rule_data_when_script_exists(tmp_path):
    data = _rules_data(review_page.build(_work(tmp_path)).read_text(encoding="utf-8"))
    assert len(data["rules"]) == 35
    r12 = [r for r in data["pages"]["02"]["deck_rules"] if r["rule"] == "R12"]
    assert [r["status"] for r in r12] == ["ng"]
    assert set(data["pages"]["02"]["variants"]) == {"R1", "R2"}
    assert data["meta"]["02"]["R1"]["kind"] == "グラフ"
    assert set(data["meta"]) == {"01", "02", "03"}


def test_build_embeds_vertical_reading_with_ledger_connective(tmp_path):
    data = _rules_data(review_page.build(_work(tmp_path)).read_text(encoding="utf-8"))
    rows = {r["nn"]: r for r in data["vertical"]["rows"]}
    assert list(rows) == ["02"]  # 本文スライドだけ
    assert rows["02"]["title"] == "件数の推移"
    assert rows["02"]["head"].startswith("導入により月次")
    assert rows["02"]["issue"] == ""
    assert rows["02"]["conn"] == "なぜなら"
    assert data["vertical"]["closing"] == "①現状 ②効果"


def test_build_without_design_leaves_connective_empty(tmp_path):
    work = _work(tmp_path, design="")  # 台帳の表がない設計図
    data = _rules_data(review_page.build(work).read_text(encoding="utf-8"))
    assert data["vertical"]["rows"][0]["conn"] == ""


def test_build_without_script_is_the_old_page(tmp_path):
    html = review_page.build(_work(tmp_path, script=None)).read_text(encoding="utf-8")
    assert _rules_data(html) is None


def test_build_ルール設定が壊れていてルール表示を出せないときは理由を_notes_に出す(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "rules").mkdir(parents=True)
    (home / "rules" / "custom.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("PPTX_MAKER_HOME", str(home))
    notes: list[str] = []
    html = review_page.build(_work(tmp_path), notes=notes).read_text(encoding="utf-8")
    assert _rules_data(html) is None
    assert any(n.startswith("ルール表示を出せません: ") and "custom.json" in n for n in notes), notes


def test_build_script_md_がなければ理由を出さず従来のページにする(tmp_path):
    notes: list[str] = []
    review_page.build(_work(tmp_path, script=None), notes=notes)
    assert not [n for n in notes if "ルール表示" in n]


# --- ブラウザ ---


@pytest.fixture
def page(tmp_path):
    from playwright.sync_api import sync_playwright

    work = _work(tmp_path)
    choices.import_text(
        work, copied(work, {"03": {"pick": "R1", "status": "approved", "comment": ""}}), cands=candidates.collect(work)
    )
    review_page.build(work, measure=False)
    with sync_playwright() as p:
        pg = p.chromium.launch().new_page()
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(CLIP)
        pg.goto((work / "review.html").as_uri())
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        pg.errors = errors
        yield pg


def _share(pg):
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    return json.loads(pg.evaluate("window.__copied"))


@pytest.mark.slow
def test_tabs_switch_and_rules_table_lists_r12(page):
    assert page.is_visible("#rv-tab-pick")
    assert page.is_visible("#rv-tab-rules")
    assert page.is_visible("#rv-tab-vert")
    assert page.is_visible("#pages")
    assert page.is_hidden("#rv-rules")
    page.click("#rv-tab-rules")
    assert page.is_hidden("#pages")
    assert page.is_visible("#rv-rules")
    assert page.locator("#rv-rules tbody tr").count() == 35
    cell = page.locator("#rv-rules tr[data-rule='R12'] td[data-pg='02']")
    assert cell.text_content().strip() == "NG"  # 色だけでなく文字でも出す
    assert "論点の欄がありません" in cell.get_attribute("title")
    assert page.locator("#rv-rules tr[data-rule='R32'] td[data-pg='02']").text_content().strip() == "未確認"
    assert "NG 1" in page.text_content("#rv-legend")
    assert page.errors == []


@pytest.mark.slow
def test_rules_table_is_ordered_r01_to_r35(page):
    page.click("#rv-tab-rules")
    ids = page.locator("#rv-rules tbody tr").evaluate_all("rows => rows.map(r => r.dataset.rule)")
    assert ids == [f"R{i:02d}" for i in range(1, 36)]  # 区分（必須・推奨）で並べ替えない


@pytest.mark.slow
def test_rule_row_shows_description_and_cell_jumps_to_page(page):
    page.click("#rv-tab-rules")
    page.click("#rv-rules tr[data-rule='R12'] th")
    assert "各ページに示す" in page.text_content("#rv-detail")
    page.click("#rv-rules tr[data-rule='R12'] td[data-pg='02']")
    assert page.is_visible("#pages")
    assert page.is_hidden("#rv-rules")
    assert page.evaluate("document.getElementById('pg-02').getBoundingClientRect().top < 200")


@pytest.mark.slow
def test_vertical_tab_lists_heads_and_closing(page):
    page.click("#rv-tab-vert")
    text = page.locator("#rv-vert tbody tr").first.text_content()
    assert "S02" in text
    assert "件数の推移" in text
    assert "なぜなら" in text
    assert "来期の人員計画" in text
    assert "①現状 ②効果" in page.text_content("#rv-vert")


@pytest.mark.slow
def test_badges_and_page_rules_fix_button_adds_comment_only(page):
    badges = page.text_content("#pg-02 .rvthumb[data-k='R1'] .rv-badges")
    assert "グラフ" in badges
    assert "ルール" in badges
    box = page.locator("#pg-02 details.rv-prules")
    assert box.get_attribute("open") is None
    assert "NG 1" in box.locator("summary").text_content()
    before = _share(page)
    page.click("#pg-02 details.rv-prules summary")
    page.click("#pg-02 .rv-prules tr[data-rule='R12'] button")
    ta = page.input_value("#pg-02 textarea")
    assert ta.startswith("R12（現在位置の表示）: ")
    assert ta.endswith("直してください")
    after = _share(page)
    assert after.keys() == before.keys()
    assert after["base"] == before["base"]
    assert after["pages"]["02"]["comment"] == ta  # 形式は同じ。コメント欄に文字が入るだけ
    assert after["pages"]["03"] == before["pages"]["03"]
    assert {k: v for k, v in before["pages"]["03"].items() if k != "fr"} == {
        "pick": "R1",
        "status": "approved",
        "comment": "",
    }
    assert page.is_disabled("#pg-02 button[data-act='approve']")  # コメントがあると承認できない
    assert after["check"] == choices.checksum(after["pages"])  # 取り込みが受け付ける検査値


@pytest.mark.slow
def test_selection_survives_tab_switch(page):
    page.click("#pg-02 .rvthumb[data-k='R2']")
    page.fill("#pg-02 textarea", "メモ")
    page.click("#rv-tab-rules")
    page.click("#rv-tab-pick")
    assert page.get_attribute("#pg-02 .rvbig .rvf", "data-k") == "R2"
    assert page.input_value("#pg-02 textarea") == "メモ"
    assert _share(page)["pages"]["02"] == {"pick": "R2", "status": "saved", "comment": "メモ"}


@pytest.mark.slow
def test_rules_table_shows_existing_checks_and_build_cells(page):
    page.click("#rv-tab-rules")
    r13 = page.locator("#rv-rules tr[data-rule='R13'] td[data-pg='02']").text_content().strip()
    assert r13 in {"OK", "NG"}  # 「・」ではない
    assert page.locator("#rv-rules tr[data-rule='R20'] td[data-pg='02']").text_content().strip() == "build時"
    assert page.locator("#rv-rules tr[data-rule='R20'] td[data-pg='all']").text_content().strip() == "build時"
    assert "build時＝PPTX を作るとき（build）に自動検査" in page.text_content("#rv-legend")


@pytest.mark.slow
def test_color_panel_shows_only_on_the_pick_tab(page):
    assert page.is_visible("#rv-color-panel")
    page.click("#rv-tab-rules")
    assert page.is_hidden("#rv-color-panel")
    page.click("#rv-tab-pick")
    assert page.is_visible("#rv-color-panel")
