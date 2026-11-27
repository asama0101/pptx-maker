# ruff: noqa: S101  # pytest の assert
"""案を選ぶページ（review.html）をブラウザで開いて確かめる: shadow root の中の書体・表紙の色、
案の選択・承認・コメント、「Claude に渡す」のコピー、開いたときの状態（choices/ から）。"""

import json

import pytest
from pptx_maker import candidates, choices, initdir, paths, review_page

from tests._flow import copied
from tests._paths import PKG

pytestmark = pytest.mark.slow  # ブラウザ（Chromium）で開く

COMP = PKG / "assets" / "components"
NO_SHEET = "window.CSSStyleSheet = undefined;"  # 共有シートが使えないブラウザ（<style> で代える）
# クリップボードの偽物: コピーした文字を window.__copied に残す。CLIP_FAIL はコピーに失敗する環境
CLIP = (
    "Object.defineProperty(navigator, 'clipboard',"
    " {configurable: true, value: {writeText: async t => { window.__copied = t; }}});"
)
CLIP_FAIL = (
    "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => { throw new Error('no'); }}});"
)
EVIL = '<img src=x onerror="window.__xss=1"><b id="evil">太字</b>'
EVIL_TEXT = "&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;&lt;b id=&quot;evil&quot;&gt;太字&lt;/b&gt;"


def _open(p, tmp_path, init_script, slides, state=None):
    """state: 開く前に choices/ に取り込む選択結果（{"01": {"pick", "status", "comment"}}）。"""
    base = tmp_path / "out" / ".pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    # 表紙の色が違うテンプレートの代わり。この規則は文書の <style> からは shadow の中に届かない
    with (work / "theme.css").open("a", encoding="utf-8") as f:
        f.write('\n.slide[data-layout="cover"] { --bg: #123456; }\n')
    s = work / "slides"
    s.mkdir(exist_ok=True)
    for name, text in slides.items():
        (s / name).write_text(text, encoding="utf-8")
    if state:
        choices.import_text(work, copied(work, state), cands=candidates.collect(work))
    review_page.build(work)
    pg = p.chromium.launch().new_page()
    errors = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.add_init_script(CLIP + init_script)
    pg.goto((work / "review.html").as_uri())  # 利用者と同じ、ローカルのファイルとして開く
    pg.work = work
    return pg, errors


def _slides():
    text = (COMP / "layouts" / "text.html").read_text(encoding="utf-8")
    cover = (COMP / "layouts" / "cover.html").read_text(encoding="utf-8")
    bar = (COMP / "charts" / "bar.html").read_text(encoding="utf-8")
    return {
        "01-R1.html": cover,
        "01-R2.html": cover.replace('<section class="slide"', '<section class="slide" data-variant="別の表紙"', 1),
        "02-R1.html": bar,
        "02-R2.html": bar.replace('<section class="slide"', '<section class="slide" data-variant="別のグラフ"', 1),
        "03-R1.html": text,
        "03-R2.html": text.replace(
            '<section class="slide"', '<section class="slide" data-variant="自由設計｜縦の流れ"', 1
        ),
    }


@pytest.fixture
def page(tmp_path, request):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        pg, errors = _open(p, tmp_path, getattr(request, "param", ""), _slides())
        # 大きな表示 3 枚（ページごと）と、各ページの案の縮小 6 枚
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        yield pg, errors


def _share(pg):
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    return json.loads(pg.evaluate("window.__copied"))


def test_no_console_errors(page):
    pg, errors = page
    assert errors == []


@pytest.mark.parametrize("page", ["", NO_SHEET], indirect=True, ids=["共有シート", "style要素"])
def test_text_in_shadow_uses_slide_font(page):
    pg, errors = page
    assert errors == []
    font = pg.evaluate(
        "getComputedStyle(document.querySelector('.rvh').shadowRoot.querySelector('.pp-text')).fontFamily"
    )
    assert font.replace('"', "'").startswith("'BIZ UDPGothic'")


def test_cover_color_rule_applies_in_shadow(page):
    pg, _ = page
    bg = pg.evaluate(
        "getComputedStyle(document.querySelector('.rvh').shadowRoot.querySelector('.slide')).backgroundColor"
    )
    assert bg == "rgb(18, 52, 86)"


def test_chart_is_drawn_with_theme_colors(page):
    """グラフは文書に入ってから描く（入る前に描くと、変数が読めず灰色 #333 になる）。"""
    pg, _ = page
    rects = "document.querySelector('#pg-02 .rvbig .rvh').shadowRoot.querySelectorAll('.pp-chart rect')"
    fills = pg.evaluate(f"[...{rects}].map(e => e.getAttribute('fill'))")
    assert fills
    assert "#333" not in fills


def test_cards_nav_and_titles(page):
    pg, _ = page
    assert pg.evaluate("[...document.querySelectorAll('section.rvpg')].map(s => s.id)") == ["pg-01", "pg-02", "pg-03"]
    assert pg.evaluate("document.querySelectorAll('section.rvpg textarea').length") == 3  # コメント欄はページごと
    assert pg.evaluate("[...document.querySelectorAll('#nav a')].map(a => a.getAttribute('href'))") == [
        "#pg-01",
        "#pg-02",
        "#pg-03",
    ]
    # 題は断片の data-role="title"・data-ph="title" から
    assert "夜間切替の運用ルール" in pg.text_content("#pg-03 h2")
    assert pg.text_content("#pg-03 h2").startswith("スライド 03")
    assert "夜間切替の運用ルール" in pg.text_content("#nav a[href='#pg-03']")
    # 案の縮小の見出しに、data-variant の特徴が出る
    assert pg.text_content("#pg-03 .rvthumb[data-k='R2'] small") == "R2　縦の流れ"
    # どのページにも案の縮小が出る
    assert pg.evaluate("document.querySelectorAll('#pg-01 .rvthumb').length") == 2


def test_initial_state_is_all_unapproved(page):
    pg, _ = page
    assert pg.text_content("#ptxt") == "承認 0/3　未承認 3"
    assert pg.get_attribute("#pg-03 .rvbig .rvf", "data-k") == "R1"  # 未選択のあいだは先頭の案を見せる


def test_pick_swaps_preview_and_marks_selected(page):
    pg, _ = page
    pg.click("#pg-03 .rvthumb[data-k='R2']")
    assert pg.get_attribute("#pg-03 .rvbig .rvf", "data-k") == "R2"
    assert "on" in pg.get_attribute("#pg-03 .rvthumb[data-k='R2']", "class")
    assert pg.text_content("#pg-03 .rvbd") == "選択中（未承認）"
    assert pg.text_content("#nav a[href='#pg-03'] em") == "選択中（未承認）"


def test_approve_is_disabled_without_pick(page):
    pg, _ = page
    assert pg.is_disabled("#pg-03 button[data-act='approve']")
    assert pg.is_disabled("#pg-01 button[data-act='approve']")  # 案を選ぶまでは承認できない


def test_approve_and_undo(page):
    pg, _ = page
    assert pg.is_hidden("#pg-01 button[data-act='undo']")
    pg.click("#pg-01 .rvthumb[data-k='R1']")
    pg.click("#pg-01 button[data-act='approve']")
    assert pg.text_content("#pg-01 .rvbd") == "承認済み"
    assert pg.text_content("#ptxt") == "承認 1/3　未承認 2"
    assert pg.is_visible("#pg-01 button[data-act='undo']")
    assert pg.is_disabled("#pg-01 button[data-act='approve']")
    pg.click("#pg-01 button[data-act='undo']")
    assert pg.text_content("#pg-01 .rvbd") == "選択中（未承認）"
    assert pg.text_content("#ptxt") == "承認 0/3　未承認 3"


def test_repick_on_approved_page_needs_approval_again(page):
    pg, _ = page
    pg.click("#pg-03 .rvthumb[data-k='R1']")
    pg.click("#pg-03 button[data-act='approve']")
    pg.click("#pg-03 .rvthumb[data-k='R2']")
    assert pg.text_content("#pg-03 .rvbd") == "選択中（未承認）"
    assert pg.is_enabled("#pg-03 button[data-act='approve']")


def test_comment_blocks_approval_and_unapproves(page):
    pg, _ = page
    pg.click("#pg-03 .rvthumb[data-k='R1']")
    pg.click("#pg-03 button[data-act='approve']")
    pg.fill("#pg-03 textarea", "色を落としてください")
    assert pg.text_content("#pg-03 .rvbd") == "コメントあり"
    assert pg.text_content("#nav a[href='#pg-03'] em") == "コメントあり"
    assert pg.is_disabled("#pg-03 button[data-act='approve']")
    assert pg.is_hidden("#pg-03 button[data-act='undo']")
    pg.fill("#pg-03 textarea", "  ")  # 空白だけならコメントなし
    assert pg.is_enabled("#pg-03 button[data-act='approve']")


def test_share_copies_choices_and_comments(page):
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R1']")
    pg.click("#pg-01 button[data-act='approve']")
    pg.click("#pg-03 .rvthumb[data-k='R2']")
    pg.fill("#pg-03 textarea", " 直す ")
    data = _share(pg)
    assert data["pptx-maker-review"] == 1
    assert data["pages"] == {
        "01": {"pick": "R1", "status": "approved", "comment": "", "fr": data["pages"]["01"]["fr"]},
        "03": {"pick": "R2", "status": "saved", "comment": "直す"},
    }
    assert data["pages"]["01"]["fr"] == choices.fragment_hash(candidates.collect(pg.work)["01"]["R1"])
    assert "コピーしました" in pg.text_content("#st")
    assert pg.is_hidden("#out")


@pytest.mark.parametrize("page", [CLIP_FAIL], indirect=True, ids=["コピー失敗"])
def test_share_shows_text_box_when_clipboard_fails(page):
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R1']")
    pg.click("#share")
    pg.wait_for_function("!document.getElementById('out').hidden")
    assert "自動でコピーできませんでした" in pg.text_content("#st")
    assert json.loads(pg.input_value("#out"))["pages"]["01"]["pick"] == "R1"


def test_change_after_share_clears_copy_message(page):
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R1']")
    _share(pg)
    pg.click("#pg-01 .rvthumb[data-k='R2']")
    assert pg.text_content("#st") == ""  # 渡したあとに変えたら、渡した表示を消す


def test_large_preview_is_same_size_for_single_and_multi_candidate_pages(page):
    pg, _ = page
    single, multi = pg.evaluate(
        "['#pg-01', '#pg-03'].map(s => { const b = document.querySelector(s + ' .rvbig');"
        " return [b.className, getComputedStyle(b).maxWidth, b.getBoundingClientRect().width]; })"
    )
    assert single == multi
    assert single[1] == "980px"


def test_opens_with_state_from_choices_files(tmp_path):
    from playwright.sync_api import sync_playwright

    state = {
        "01": {"pick": "R2", "status": "approved", "comment": ""},
        "03": {"pick": "R2", "status": "saved", "comment": "直す"},
    }
    with sync_playwright() as p:
        pg, errors = _open(p, tmp_path, "", _slides(), state)
        assert errors == []
        assert pg.text_content("#ptxt") == "承認 1/3　未承認 2"
        assert pg.text_content("#pg-01 .rvbd") == "承認済み"
        assert pg.get_attribute("#pg-01 .rvbig .rvf", "data-k") == "R2"
        assert pg.text_content("#pg-03 .rvbd") == "コメントあり"
        assert pg.input_value("#pg-03 textarea") == "直す"
        assert pg.text_content("#pg-02 .rvbd") == "未承認"


def test_pick_that_no_longer_exists_is_ignored(tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        pg, errors = _open(p, tmp_path, "", _slides(), {"03": {"pick": "R9", "status": "saved", "comment": ""}})
        assert errors == []
        assert pg.get_attribute("#pg-03 .rvbig .rvf", "data-k") == "R1"
        assert pg.is_disabled("#pg-03 button[data-act='approve']")  # 案がないので、選び直すまで承認できない


def test_text_from_fragments_and_choices_is_never_interpreted_as_html(tmp_path):
    """断片の題・data-variant の特徴、choices/ の値（コメント）を、HTML として解釈しない。"""
    text = (COMP / "layouts" / "text.html").read_text(encoding="utf-8")
    slides = {
        "01-R1.html": f'<section class="slide" data-variant="自由設計｜{EVIL_TEXT}">'
        f'<div class="pp-text" data-role="title">{EVIL_TEXT}</div></section>',
        "01-R2.html": text,
    }
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        pg, errors = _open(p, tmp_path, "", slides, {"01": {"pick": "R1", "status": "saved", "comment": EVIL}})
        pg.wait_for_timeout(200)  # 解釈されていれば、画像の読み込みの失敗（onerror）がここまでに起きる
        assert EVIL[:20] in pg.text_content("#pg-01 h2")
        assert EVIL[:20] in pg.text_content("#pg-01 .rvthumb[data-k='R1'] small")
        assert pg.input_value("#pg-01 textarea") == EVIL
        assert pg.evaluate("document.querySelectorAll('#evil, img[src=x]').length") == 0
        assert pg.evaluate("window.__xss") is None
        assert errors == []


def test_html_comment_open_in_fragment_does_not_break_page(tmp_path):
    """断片の <!--<script は、埋め込んだデータの <script> の終わりを見失わせない。"""
    from playwright.sync_api import sync_playwright

    # 後ろに --> があると壊れ方が隠れるので、HTML のコメントを持たない断片だけにする
    slides = {
        "01-R1.html": '<section class="slide"><div class="pp-text">x<!--<b>y</div></section>',
        "01-R2.html": '<section class="slide"><div class="pp-text">w</div></section>',
        "02-R1.html": '<section class="slide"><div class="pp-text">z</div></section>',
        "02-R2.html": '<section class="slide"><div class="pp-text">v</div></section>',
    }
    with sync_playwright() as p:
        pg, errors = _open(p, tmp_path, "", slides)
        assert pg.evaluate("document.querySelectorAll('section.rvpg').length") == 2
        assert errors == []


def test_copied_json_is_accepted_by_choices_import(page):
    """ブラウザが作る JSON（日本語のコメント・記号つき）を、Python 側の検査値と指紋が受け入れる。"""
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R1']")
    pg.click("#pg-01 button[data-act='approve']")
    pg.click("#pg-03 .rvthumb[data-k='R2']")
    pg.fill("#pg-03 textarea", '色を落として、"強調" は 1 つに。\n2 行目 \\ 𠮷 😀 <b>')
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    text = pg.evaluate("window.__copied")
    assert choices.import_text(pg.work, text) == [
        {"slide": "03", "comment": '色を落として、"強調" は 1 つに。\n2 行目 \\ 𠮷 😀 <b>'}
    ]
    assert choices.load(pg.work)["01"]["status"] == "approved"


def test_page_from_before_rebuild_is_rejected(page):
    """Claude が作り直したあとに、開きっぱなしの古いページから渡された内容は取り込まない。"""
    pg, _ = page
    pg.click("#pg-03 .rvthumb[data-k='R1']")
    pg.fill("#pg-03 textarea", "直して")
    pg.click("#share")
    pg.wait_for_function("document.getElementById('st').textContent !== ''")
    old = pg.evaluate("window.__copied")
    choices.import_text(pg.work, old)
    choices.resolve(pg.work, ["03"])  # 直して、ページを作り直した
    with pytest.raises(ValueError, match="古いページ"):
        choices.import_text(pg.work, old)


def test_approved_share_carries_fr_and_import_succeeds(page):
    """承認のページだけ、見た断片の指紋 fr が入る。check が合い、choices-import が通って frag が書かれる。"""
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R2']")
    pg.click("#pg-01 button[data-act='approve']")
    pg.click("#pg-03 .rvthumb[data-k='R2']")  # 承認前（saved）
    data = _share(pg)
    cands = candidates.collect(pg.work)
    assert data["pages"]["01"]["fr"] == choices.fragment_hash(cands["01"]["R2"])
    assert "fr" not in data["pages"]["03"]
    assert data["check"] == choices.checksum(data["pages"])
    choices.import_text(pg.work, json.dumps(data), cands=cands)
    assert choices.frag_of(pg.work, "01") == data["pages"]["01"]["fr"]


def test_repick_after_approval_drops_fr(page):
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R1']")
    pg.click("#pg-01 button[data-act='approve']")
    pg.click("#pg-01 .rvthumb[data-k='R2']")
    assert "fr" not in _share(pg)["pages"]["01"]


def test_edited_fragment_turns_restored_approval_into_saved(page):
    """断片だけ直して review-page をやり直すと、同じ localStorage の承認は saved で出る。直さないページは承認のまま。"""
    pg, _ = page
    for nn in ("01", "03"):
        pg.click(f"#pg-{nn} .rvthumb[data-k='R1']")
        pg.click(f"#pg-{nn} button[data-act='approve']")
    pg.reload()  # 承認が localStorage に保存された
    pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
    f = pg.work / "slides" / "01-R1.html"
    f.write_text(f.read_text(encoding="utf-8") + "<!-- 直した -->", encoding="utf-8")
    review_page.build(pg.work)  # choices/ は変わらないので、指紋（localStorage のキー）も同じ
    pg.reload()
    pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
    assert pg.text_content("#pg-01 .rvbd") != "承認済み"
    assert pg.text_content("#pg-03 .rvbd") == "承認済み"
    pages = _share(pg)["pages"]
    assert pages["01"]["status"] == "saved"
    assert "fr" not in pages["01"]
    assert pages["03"]["status"] == "approved"


def test_state_survives_reload(page):
    """誤って開き直しても、選択・承認・コメントが戻る（このブラウザに自動保存される）。"""
    pg, _ = page
    pg.click("#pg-01 .rvthumb[data-k='R2']")
    pg.click("#pg-01 button[data-act='approve']")
    pg.fill("#pg-03 textarea", "直す")
    pg.reload()
    pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
    assert pg.text_content("#pg-01 .rvbd") == "承認済み"
    assert pg.get_attribute("#pg-01 .rvbig .rvf", "data-k") == "R2"
    assert pg.input_value("#pg-03 textarea") == "直す"
    assert pg.text_content("#pg-03 .rvbd") == "コメントあり"


def test_saved_state_is_not_used_after_the_page_is_rebuilt(tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        pg, _ = _open(p, tmp_path, "", _slides())
        pg.fill("#pg-03 textarea", "直す")
        review_page.build(pg.work)  # 作り直し（choices/ が変わらなければ同じ指紋なので、変えてから）
        choices.import_text(pg.work, copied(pg.work, {"02": {"pick": "R1", "status": "saved", "comment": ""}}))
        review_page.build(pg.work)
        pg.reload()
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        assert pg.input_value("#pg-03 textarea") == ""
        assert pg.text_content("#pg-02 .rvbd") == "選択中（未承認）"


def test_dropped_pick_also_drops_approval(tmp_path):
    """choices/ の pick が今の案にないとき、承認済みの表示だけを残さない。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        pg, errors = _open(p, tmp_path, "", _slides(), {"03": {"pick": "R9", "status": "approved", "comment": ""}})
        assert errors == []
        assert pg.text_content("#pg-03 .rvbd") == "未承認"
        assert pg.text_content("#ptxt") == "承認 0/3　未承認 3"


def test_broken_chart_in_one_variant_does_not_stop_the_page(tmp_path):
    """案の 1 つの data-chart が壊れていても、ほかの案のグラフと「Claude に渡す」は動く。"""
    from playwright.sync_api import sync_playwright

    slides = _slides()
    slides["02-R2.html"] = slides["02-R2.html"].replace("data-chart='", "data-chart='{壊れた", 1)
    assert "{壊れた" in slides["02-R2.html"]
    with sync_playwright() as p:
        pg, _ = _open(p, tmp_path, "", slides)
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        hosts = "[...document.querySelectorAll('.rvh')].some(h => h.shadowRoot && "
        assert pg.evaluate(hosts + "h.shadowRoot.textContent.includes('グラフを描けません'))")
        # 壊れていない案（02-R1）のグラフは描かれている
        assert pg.evaluate(hosts + "h.shadowRoot.querySelector('.pp-chart svg'))")
        assert _share(pg)["pptx-maker-review"] == 1


def test_clearing_a_comment_on_a_page_without_pick_is_shared(tmp_path):
    """案を選ばずに書いたコメントを消したとき、消したことが渡る（古いコメントが choices/ に残らない）。"""
    from playwright.sync_api import sync_playwright

    state = {"01": {"pick": None, "status": "saved", "comment": "直したい"}}
    with sync_playwright() as p:
        pg, _ = _open(p, tmp_path, "", _slides(), state)
        pg.wait_for_function("document.querySelectorAll('.rvh').length === 9")
        pg.fill("#pg-01 textarea", "")
        shared = _share(pg)
        assert shared["pages"]["01"] == {"pick": None, "status": "saved", "comment": ""}
        work = pg.work
    choices.import_text(work, json.dumps(shared))
    assert choices.load(work)["01"]["comment"] == ""
