# ruff: noqa: S101  # pytest の assert
"""案の選択ページの「選択済みを一括承認」: 条件を満たすページだけ承認し、残りは理由を出す。"""

import json

import pytest
from pptx_maker import cli, review_page

from tests._flow import write_slide
from tests.test_review_page_checks import CLOSING, COVER, SCRIPT, _work
from tests.test_review_page_render import CLIP


@pytest.fixture
def page(tmp_path):
    from playwright.sync_api import sync_playwright

    work = _work(tmp_path)
    write_slide(work / "slides", "01", COVER)
    write_slide(work / "slides", "03", CLOSING)
    (work / "script.md").write_text(SCRIPT, encoding="utf-8")
    review_page.build(work, measure=False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(CLIP)
        pg.goto((work / "review.html").as_uri())
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        pg.errors = errors
        pg.work = work
        yield pg
        browser.close()


def _state(pg, nn):
    return pg.text_content(f"#nav a[href='#pg-{nn}'] em")


def _pick(pg, nn, k="R1"):
    pg.click(f"#pg-{nn} .rvthumb[data-k='{k}']")


def _check_all(pg, nn):
    for r in ("R32", "R33", "R34"):
        pg.check(f"#pg-{nn} .rv-hc[data-rule='{r}'] input")


@pytest.mark.slow
def test_bulk_は条件を満たすページだけ承認し理由を出す(page):
    _pick(page, "01")  # 表紙: 確認項目なし
    _pick(page, "02")  # 本文: 確認項目が未チェック
    page.fill("#pg-01 .rvta", "")
    page.click("#rv-bulk")
    assert _state(page, "01") == "承認済み"
    assert _state(page, "02") != "承認済み"
    assert _state(page, "03") != "承認済み"  # 案を選んでいない
    msg = page.text_content("#rv-bulk-msg")
    assert "承認 1 件" in msg
    assert "確認項目が未チェック 1 件" in msg
    assert "案が未選択 1 件" in msg
    assert page.errors == []


@pytest.mark.slow
def test_bulk_はコメントのあるページを承認しない(page):
    _pick(page, "01")
    _pick(page, "02")
    _check_all(page, "02")
    page.fill("#pg-01 .rvta", "直してください")
    page.click("#rv-bulk")
    assert _state(page, "01") != "承認済み"
    assert _state(page, "02") == "承認済み"
    assert "コメントあり 1 件" in page.text_content("#rv-bulk-msg")
    page.fill("#pg-01 .rvta", "")
    page.click("#rv-bulk")
    assert _state(page, "01") == "承認済み"


@pytest.mark.slow
def test_bulk_の承認は_fr_つきで_choices_import_を通る(page, tmp_path):
    _pick(page, "01", "R2")
    _pick(page, "02")
    _check_all(page, "02")
    page.click("#rv-bulk")
    page.click("#share")
    page.wait_for_function("window.__copied")
    data = json.loads(page.evaluate("window.__copied"))
    assert data["pages"]["01"]["status"] == "approved"
    assert data["pages"]["01"]["fr"]
    f = tmp_path / "paste.txt"
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert cli.entry(["choices-import", str(page.work), "--file", str(f)]) == 0


@pytest.mark.slow
def test_bulk_は承認済みのページを変えず_取り消しも効く(page):
    _pick(page, "01")
    page.click("#pg-01 [data-act='approve']")
    assert _state(page, "01") == "承認済み"
    page.click("#rv-bulk")
    assert _state(page, "01") == "承認済み"
    page.click("#pg-01 [data-act='undo']")
    assert _state(page, "01") != "承認済み"
