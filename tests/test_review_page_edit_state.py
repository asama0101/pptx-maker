# ruff: noqa: S101  # pytest の assert
"""案の選択ページの編集モードの状態: 番号づけ（Python と一致）、貼り付けの edits、フレームへの反映、localStorage。"""

import json

import pytest
from pptx_maker import cli, fragedit, review_page, svgids

from tests._flow import write_slide
from tests._paths import PKG
from tests.test_fragedit import FRAG, POS
from tests.test_review_page_checks import CLOSING, SCRIPT, _work
from tests.test_review_page_render import CLIP

pytestmark = pytest.mark.slow  # ブラウザ（Chromium）で開く

R2_FRAG = FRAG.replace("本文 A", "本文 A2")


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


def _share(pg):
    pg.evaluate("window.__copied = null")
    pg.click("#share")
    pg.wait_for_function("window.__copied")
    return json.loads(pg.evaluate("window.__copied"))


def _lefts(pg, nn="01", k="R2"):
    js = (
        "([nn, k]) => [...document.querySelectorAll(`#pg-${nn} .rvf[data-k='${k}']`)]"
        ".map(f => f.firstChild.shadowRoot.querySelectorAll('.pp-text')[1].style.left)"
    )
    return pg.evaluate(js, [nn, k])


def test_番号の数え方が_Python_と一致する(page):
    files = sorted((PKG / "assets" / "components").rglob("*.html")) + sorted(
        (PKG / "assets" / "sample").rglob("*.html")
    )
    assert files
    js = "h => __rvEdit.parts(h).map(p => [p.kind, p.nested, p.fixed, p.texts.length])"
    for f in files:
        raw = f.read_text(encoding="utf-8")
        for text in (raw, svgids.uniquify(raw, "s01r1-")):
            want = [[p.kind, p.nested, p.fixed, len(p.texts)] for p in fragedit.parts(text)]
            assert page.evaluate(js, text) == want, f.name
    assert page.errors == []


def test_編集は貼り付けの_JSON_に入り_Python_が受け取れる(page, tmp_path):
    page.click("#pg-01 .rvthumb[data-k='R2']")
    page.click("#pg-01 [data-act='approve']")
    patch = {"left": 100, "text": ["新 🎉 A & <B>", "本文 B"]}
    page.evaluate("p => __rvEdit.set('01', 'R2', 1, p)", patch)
    data = _share(page)
    assert data["pages"]["01"]["status"] == "saved"
    assert "fr" not in data["pages"]["01"]
    edits = data["pages"]["01"]["edits"]
    assert list(edits) == ["R2"]
    assert edits["R2"]["items"] == {"1": patch}
    before = (page.work / "slides" / "01-R2.html").read_bytes().decode("utf-8")
    f = tmp_path / "paste.txt"
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["choices-import", str(page.work), "--file", str(f)]) == 0
    got = (page.work / "slides" / "01-R2.html").read_bytes().decode("utf-8")
    want = before.replace(POS, "left:100px;top:140px;width:500px;height:100px").replace(
        "本文 A2<br>本文 B", "新 🎉 A &amp; &lt;B&gt;<br>本文 B"
    )
    assert got == want
    assert page.errors == []


def test_編集はフレームに出て_localStorage_に残る(page):
    page.click("#pg-01 .rvthumb[data-k='R2']")
    page.evaluate("__rvEdit.set('01', 'R2', 1, {left: 100, text: ['新A', '本文 B']})")
    assert _lefts(page) == ["100px", "100px"]  # 大きな表示と縮小
    texts = page.evaluate(
        "document.querySelector('#pg-01 .rvbig .rvh').shadowRoot.querySelectorAll('.pp-text')[1].textContent"
    )
    assert texts == "新A本文 B"
    page.reload()
    page.wait_for_function("document.querySelectorAll('.rvh').length === 9")
    assert _lefts(page) == ["100px", "100px"]  # 選択も復元される
    assert page.errors == []


def test_断片が変わった案の古い編集は捨てる(page):
    key = page.evaluate("Object.keys(localStorage).find(k => k.startsWith('pptx-maker-review:'))")
    page.evaluate("__rvEdit.set('01', 'R2', 1, {left: 100})")
    page.evaluate(
        "k => { const s = JSON.parse(localStorage.getItem(k)); s['01'].edits.R2.ef = 'old';"
        " localStorage.setItem(k, JSON.stringify(s)); }",
        key,
    )
    page.reload()
    page.wait_for_function("document.querySelectorAll('.rvh').length === 9")
    assert "edits" not in _share(page)["pages"].get("01", {})


def test_値が元に戻った項目は編集から消える(page):
    page.evaluate("__rvEdit.set('01', 'R2', 1, {left: 100})")
    assert "edits" in _share(page)["pages"]["01"]
    page.evaluate("__rvEdit.set('01', 'R2', 1, {left: 96})")
    assert "edits" not in _share(page)["pages"].get("01", {})
    page.evaluate("__rvEdit.set('01', 'R2', 1, {text: ['本文 A2', '本文 B']})")
    assert "edits" not in _share(page)["pages"].get("01", {})
