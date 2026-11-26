# ruff: noqa: S101  # pytest の assert
"""案の選択ページの編集モードの操作: 選択・ドラッグ移動・リサイズ・矢印キー・文言編集・元に戻す。"""

import json

import pytest
from pptx_maker import review_page

from tests._flow import write_slide
from tests.test_fragedit import FRAG
from tests.test_review_page_checks import CLOSING, SCRIPT, _work
from tests.test_review_page_render import CLIP

pytestmark = pytest.mark.slow  # ブラウザ（Chromium）で開く

R2_FRAG = FRAG.replace("本文 A", "本文 A2")
BIG = "#pg-01 .rvbig"
TITLE = f"{BIG} .pp-text >> nth=0"  # data-chrome の題
BODY = f"{BIG} .pp-text >> nth=1"  # left:96 top:140 width:500 height:100
NESTED = f"{BIG} .pp-text >> nth=2"  # pp-shape の中の入れ子


@pytest.fixture
def page(tmp_path):
    from playwright.sync_api import sync_playwright

    work = _work(tmp_path)
    write_slide(work / "slides", "01", FRAG, R2_FRAG)
    write_slide(work / "slides", "03", CLOSING)
    (work / "script.md").write_text(SCRIPT, encoding="utf-8")
    review_page.build(work, measure=False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(CLIP)
        pg.goto((work / "review.html").as_uri())
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        pg.errors = errors
        pg.work = work
        pg.click("#pg-01 .rvthumb[data-k='R2']")
        yield pg
        browser.close()


def _share(pg):
    pg.evaluate("window.__copied = null")
    pg.click("#share")
    pg.wait_for_function("window.__copied")
    return json.loads(pg.evaluate("window.__copied"))


def _items(pg):
    return _share(pg)["pages"].get("01", {}).get("edits", {}).get("R2", {}).get("items", {})


def _edit_on(pg):
    pg.click("#pg-01 [data-act='edit']")


def _scale(pg):
    return pg.evaluate("document.querySelector('#pg-01 .rvbig .rvf').clientWidth / 1280")


def _center(pg, sel):
    pg.locator(sel).scroll_into_view_if_needed()
    b = pg.locator(sel).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _drag(pg, x, y, dx, dy):
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + dx / 2, y + dy / 2)
    pg.mouse.move(x + dx, y + dy)
    pg.mouse.up()


def test_編集ボタンで編集モードに入り出る(page):
    assert "rv-editing" not in page.get_attribute("#pg-01", "class")
    assert not page.is_visible("#pg-01 .rv-edit-reset")
    _edit_on(page)
    assert "rv-editing" in page.get_attribute("#pg-01", "class")
    assert page.is_visible("#pg-01 .rv-edit-reset")
    _edit_on(page)
    assert "rv-editing" not in page.get_attribute("#pg-01", "class")
    assert page.errors == []


def test_ドラッグで移動し_scale_で割った_px_になる(page):
    _edit_on(page)
    s = _scale(page)
    x, y = _center(page, BODY)
    _drag(page, x, y, 40, -30)
    items = _items(page)
    assert items == {"1": {"left": 96 + round(40 / s), "top": 140 + round(-30 / s)}}
    assert page.locator(BODY).evaluate("e => e.style.left") == f"{96 + round(40 / s)}px"
    assert "PPTX に反映するには、Claude に渡して、再承認してください" in page.text_content("#pg-01 .rv-edit-note")
    assert page.errors == []


def test_編集モードでないときはドラッグしても動かない(page):
    x, y = _center(page, BODY)
    _drag(page, x, y, 40, 40)
    assert _items(page) == {}


def test_矢印キーで動く(page):
    _edit_on(page)
    x, y = _center(page, BODY)
    page.mouse.click(x, y)
    assert "rv-sel" in page.locator(BODY).get_attribute("class")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    assert _items(page) == {"1": {"left": 97, "top": 150}}
    assert page.errors == []


def test_ハンドルでリサイズする(page):
    _edit_on(page)
    s = _scale(page)
    x, y = _center(page, BODY)
    page.mouse.click(x, y)
    hx, hy = _center(page, f"{BIG} .rv-handle")
    assert page.get_attribute(f"{BIG} .rv-handle", "data-h") == "se"
    _drag(page, hx, hy, 30, 20)
    assert _items(page) == {"1": {"width": 500 + round(30 / s), "height": 100 + round(20 / s)}}
    hx, hy = _center(page, f"{BIG} .rv-handle")
    _drag(page, hx, hy, -2000, -2000)  # 左上へ大きく引いても 0 で止まる
    assert _items(page) == {"1": {"width": 0, "height": 0}}
    assert page.errors == []


def test_題と入れ子と_left_top_のない部品は動かせない(page):
    _edit_on(page)
    for sel in (TITLE, NESTED, f"{BIG} .pp-text >> nth=3"):  # 題・入れ子・data-ph（left/top なし）
        x, y = _center(page, sel)
        _drag(page, x, y, 40, 40)
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Shift+ArrowDown")
        assert page.locator(f"{BIG} .rv-handle").count() == 0
    assert "edits" not in _share(page)["pages"].get("01", {})
    assert page.errors == []


def test_ダブルクリックで文言を直し確定する(page):
    _edit_on(page)
    page.locator(TITLE).dblclick()
    page.keyboard.press("Control+a")
    page.keyboard.type("新しい題")
    page.click("#pg-01 .rvta")  # フォーカスを外す
    assert _items(page) == {"0": {"text": ["新しい題"]}}
    assert page.locator(TITLE).text_content() == "新しい題"
    assert page.errors == []


def test_構造が変わる編集は取り消す(page):
    _edit_on(page)
    page.locator(BODY).dblclick()
    page.keyboard.press("Enter")
    page.click("#pg-01 .rvta")
    assert _items(page) == {}
    assert page.locator(BODY).inner_html() == "本文 A2<br>本文 B"
    assert "Claude に依頼してください" in page.text_content("#pg-01 .rv-edit-note")
    assert page.errors == []


def test_元に戻すと編集が消える(page):
    _edit_on(page)
    x, y = _center(page, BODY)
    _drag(page, x, y, 40, 40)
    assert _items(page) != {}
    page.click("#pg-01 .rv-edit-reset")
    assert _items(page) == {}
    assert page.locator(BODY).evaluate("e => e.style.left") == "96px"
    assert page.errors == []


def test_編集で承認が外れる(page):
    page.click("#pg-01 [data-act='approve']")
    assert page.text_content("#nav a[href='#pg-01'] em") == "承認済み"
    _edit_on(page)
    x, y = _center(page, BODY)
    _drag(page, x, y, 40, 40)
    assert page.text_content("#nav a[href='#pg-01'] em") != "承認済み"
