# ruff: noqa: S101  # pytest の assert
"""案の選択ページの 2c-2: 測る検査（R20・R23・R26）、AI 判定の表示、人の確認のチェックと JSON の checks。"""

import json
import re
from pathlib import Path

import pytest
from pptx_maker import choices, cli, consulting, fragcheck, initdir, paths, review_page

from tests._flow import copied, write_slide
from tests.test_review_page_render import CLIP

SCRIPT = (
    "# 題\n- 論点:\n  - ① 現状\n\n"
    "## S01 表紙\n- layout: cover\n- ヘッドメッセージ: 表紙\n\n"
    "## S02 本文\n- layout: content\n- 題: 件数\n"
    "- ヘッドメッセージ: 導入により月次の集計作業が半分に縮むため、来期の人員計画を見直す必要がある\n\n"
    "## S03 裏表紙\n- layout: closing\n- ヘッドメッセージ: ご承認ください\n- 本文: ①現状\n"
)
GOOD = (
    '<section class="slide" data-layout="content">\n'
    '  <div class="pp-text" data-role="title" style="top:36px;height:50px">題</div>\n'
    '  <div class="pp-text" data-role="body" style="left:64px;top:200px;width:600px;height:60px">本文</div>\n'
    "</section>\n"
)
SMALL = GOOD.replace("height:60px", "height:60px;font-size:11px")
COVER = '<section class="slide" data-layout="cover"><div class="pp-text" data-role="title">表紙</div></section>\n'
CLOSING = '<section class="slide" data-layout="closing"><div class="pp-text" data-role="title">裏</div></section>\n'


def _work(tmp_path: Path, small=SMALL) -> Path:
    base = tmp_path / "out" / ".pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    write_slide(work / "slides", "01", COVER)
    write_slide(work / "slides", "02", small, GOOD)
    write_slide(work / "slides", "03", CLOSING)
    (work / "script.md").write_text(SCRIPT, encoding="utf-8")
    return work


def _status(r, nn, key, rid):
    return [x["status"] for x in r["pages"][nn]["variants"][key] if x["rule"] == rid]


def _data(work):
    html = (work / "review.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'id="rv-data">(.*?)</script>', html, re.S)[1])


# --- (a) 測る検査 ---


def test_summarize_maps_only_rule_violations():
    v = [
        {"rule": "fontMin", "message": "text#2: 8pt は下限 14pt 未満です"},
        {"rule": "overlap", "message": "重なり"},
        {"rule": "colorNeon", "message": "蛍光色"},
        {"rule": "chromeSpec", "message": "規約と違います"},
    ]
    s = fragcheck.summarize(v)
    assert set(s) == {"R26", "R23", "R20"}
    assert s["R26"] == "text#2: 8pt は下限 14pt 未満です（fontMin）"


@pytest.mark.slow
def test_measure_true_reports_r26_on_small_text_only(tmp_path):
    r = consulting.evaluate(_work(tmp_path), measure=True)
    assert _status(r, "02", "R1", "R26") == ["ng"]  # 必須の機械検査
    assert _status(r, "02", "R2", "R26") == ["ok"]
    assert "fontMin" in next(x["message"] for x in r["pages"]["02"]["variants"]["R1"] if x["rule"] == "R26")
    assert _status(r, "02", "R2", "R20") == ["ok"]
    assert not [x for x in r["pages"]["02"]["deck_rules"] if x["status"] == "build"]


@pytest.mark.slow
def test_measure_false_keeps_build(tmp_path):
    r = consulting.evaluate(_work(tmp_path))
    assert {x["status"] for x in r["pages"]["02"]["deck_rules"] if x["rule"] == "R26"} == {"build"}
    assert _status(r, "02", "R1", "R26") == []


@pytest.mark.slow
def test_review_page_cli_measures_and_no_measure_flag(tmp_path):
    work = _work(tmp_path)
    assert cli.main(["review-page", str(work)]) == 0
    data = _data(work)
    assert data["measured"] is True
    assert data["pages"]["02"]["variants"]["R1"]
    assert cli.main(["review-page", str(work), "--no-measure"]) == 0
    assert not _data(work).get("measured")


def test_measure_failure_falls_back_to_build_with_note(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("chromium がありません")

    monkeypatch.setattr(fragcheck, "check_variants", boom)
    work = _work(tmp_path)
    notes: list[str] = []
    review_page.build(work, notes=notes)
    assert any("chromium がありません" in n for n in notes)
    r = consulting.evaluate(work, measure=True)
    assert {x["status"] for x in r["pages"]["02"]["deck_rules"] if x["rule"] == "R26"} == {"build"}


def test_variant_measure_failure_keeps_its_reason(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from pptx_maker import measure

    @contextmanager
    def no_browser(browser=None):
        yield None

    def boom(*a, **k):
        raise RuntimeError("SVG が壊れています")

    monkeypatch.setattr(measure, "open_browser", no_browser)
    monkeypatch.setattr(measure, "measure", boom)
    work = _work(tmp_path)
    failed: dict[str, str] = {}
    assert fragcheck.check_variants(work, {"02": ["R1"]}, failed) == {("02", "R1"): None}
    assert "RuntimeError: SVG が壊れています" in failed["02-R1"]
    assert "02-R1" in consulting.evaluate(work, measure=True)["measure_error"]


# --- (b)(c) checks の JSON ---

CHECKS = {"R32": True, "R34": True}


def test_checksum_covers_checks():
    a = {"02": {"pick": "R1", "status": "saved", "comment": ""}}
    b = {"02": {**a["02"], "checks": CHECKS}}
    assert choices.checksum(a) != choices.checksum(b)


def test_import_writes_checks_only_when_present(tmp_path):
    pages = {
        "01": {"pick": "R1", "status": "saved", "comment": "", "checks": CHECKS},
        "02": {"pick": "R1", "status": "saved", "comment": ""},
    }
    choices.import_text(tmp_path, copied(tmp_path, pages))
    assert json.loads((tmp_path / "choices" / "01.json").read_text("utf-8"))["checks"] == CHECKS
    assert "checks" not in json.loads((tmp_path / "choices" / "02.json").read_text("utf-8"))
    assert choices.load(tmp_path)["01"]["checks"] == CHECKS
    assert "checks" not in choices.load(tmp_path)["02"]


@pytest.mark.parametrize("bad", [["R32"], {"R32": "yes"}, {"R32": 1}, "R32"])
def test_import_rejects_bad_checks_and_writes_nothing(tmp_path, bad):
    pages = {"01": {"pick": "R1", "status": "saved", "comment": "", "checks": bad}}
    with pytest.raises(ValueError, match="01: checks"):
        choices.import_text(tmp_path, copied(tmp_path, pages))
    assert not (tmp_path / "choices").exists()


def test_resolve_keeps_checks(tmp_path):
    pages = {"01": {"pick": "R1", "status": "saved", "comment": "直す", "checks": CHECKS}}
    choices.import_text(tmp_path, copied(tmp_path, pages))
    choices.resolve(tmp_path, ["01"])
    assert choices.load(tmp_path)["01"]["checks"] == CHECKS


# --- (d) ブラウザ ---


@pytest.fixture
def page(tmp_path):
    from playwright.sync_api import sync_playwright

    work = _work(tmp_path)
    reviews = [
        {"rule": "R19", "page": "02", "status": "warn", "message": "主役が 2 つある"},
        {"rule": "R01", "page": "deck", "status": "ok", "message": ""},
    ]
    (work / "rule-review.json").write_text(json.dumps({"reviews": reviews}), encoding="utf-8")
    review_page.build(work, measure=False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(CLIP)
        pg.goto((work / "review.html").as_uri())
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        pg.errors = errors
        pg.work = work
        yield pg
        browser.close()


def _share(pg):
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    return json.loads(pg.evaluate("window.__copied"))


@pytest.mark.slow
def test_human_items_only_on_body_pages(page):
    assert page.locator("#pg-02 .rv-hc").count() == 3
    assert page.locator("#pg-01 .rv-hc, #pg-03 .rv-hc").count() == 0
    assert "数値・前提の正しさ" in page.text_content("#pg-02 .rv-human")
    assert "人の確認 未了 3 件" in page.text_content("#ptxt")


@pytest.mark.slow
def test_checking_goes_to_storage_and_json_only_for_checked_pages(page):
    page.check("#pg-02 .rv-hc[data-rule='R32'] input")
    j = _share(page)
    assert j["pages"]["02"]["checks"] == {"R32": True}
    assert j["check"] == choices.checksum(j["pages"])  # JS の fnv と Python の checksum が一致
    stored = json.loads(page.evaluate("localStorage.getItem(Object.keys(localStorage)[0])"))
    assert stored["02"]["checks"] == {"R32": True}
    assert all("checks" not in v for k, v in j["pages"].items() if k != "02")
    assert "人の確認 未了 2 件" in page.text_content("#ptxt")
    page.uncheck("#pg-02 .rv-hc[data-rule='R32'] input")
    assert "checks" not in _share(page)["pages"].get("02", {})


@pytest.mark.slow
def test_approve_with_unchecked_items_warns_but_approves(page):
    page.click("#pg-02 .rvthumb[data-k='R2']")
    page.click("#pg-02 button[data-act='approve']")
    assert "未確認の項目があります" in page.text_content("#pg-02 .rv-hwarn")
    assert "R32" in page.text_content("#pg-02 .rv-hwarn")
    assert _share(page)["pages"]["02"]["status"] == "approved"
    for r in ("R32", "R33", "R34"):
        page.check(f"#pg-02 .rv-hc[data-rule='{r}'] input")
    assert page.locator("#pg-02 .rv-hwarn").is_hidden()
    assert "確認済み 3/3" in page.text_content("#pg-02 .rv-hdone")


@pytest.mark.slow
def test_rules_tab_shows_human_status_and_ai_cells(page):
    page.click("#rv-tab-rules")
    cell = page.locator("#rv-rules tr[data-rule='R32'] td[data-pg='02']")
    assert cell.text_content().strip() == "未確認"
    page.click("#rv-tab-pick")
    page.check("#pg-02 .rv-hc[data-rule='R32'] input")
    page.click("#rv-tab-rules")
    assert cell.text_content().strip() == "確認済み"
    ai = page.locator("#rv-rules tr[data-rule='R19'] td[data-pg='02']")
    assert ai.get_attribute("title").startswith("R19: AI 判定: ")
    assert page.locator("#rv-rules tr[data-rule='R21'] td[data-pg='02']").text_content().strip() == "AI判定待ち"
    assert "AI判定待ち" in page.text_content("#rv-legend")
    page.click("#rv-rules tr[data-rule='R19'] th")
    assert "ok:" in page.text_content("#rv-detail")  # 採点表
    page.click("#rv-rules tr[data-rule='R32'] th")
    assert "事実と社内の基準" in page.text_content("#rv-detail")  # 質問
    assert page.errors == []


@pytest.mark.slow
def test_page_rules_table_has_judge_column_and_fix_button_for_ai(page):
    page.click("#pg-02 details.rv-prules summary")
    row = page.locator("#pg-02 .rv-prules tr[data-rule='R19']")
    assert "AI" in row.text_content()
    assert row.locator("button").count() == 1
    assert "判定者" in page.text_content("#pg-02 .rv-prules thead")
