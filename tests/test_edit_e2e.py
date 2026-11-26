# ruff: noqa: S101  # pytest の assert
"""review.html の編集モード: 編集 → 「Claude に渡す」→ choices-import → 再承認 → finalize → build → PPTX までの通し。"""

import json

import pytest
from pptx import Presentation
from pptx_maker import cli, consulting, paths, rulebook

from tests._flow import write_choices, write_slide
from tests.test_review_page_render import CLIP

pytestmark = pytest.mark.slow  # ブラウザ（Chromium）で開く

SCRIPT = (
    "# 題\n"
    "## S01 表紙\n- layout: cover\n- ヘッドメッセージ: 表紙のメッセージです\n\n"
    "## S02 本文\n- layout: content\n- 章名: 何が変わるか\n- ヘッドメッセージ: 原価を絞れば利益が増える\n"
    "- 本文:\n  - 要点\n- 主役の図表: 表 — 比較\n- 読み手にさせたいこと: 承認\n"
)
OLD_TEXT = "切替は平日22時から翌5時に行い、営業時間内の作業は原則として行わない。1拠点あたりの停止は最大30分とする"
NEW_TEXT = "切替は平日22時から翌5時に行う。停止は最大30分"
BODY = 4  # text.html の pp-* を文書順に数えた、1 つ目の本文（OLD_TEXT）の番号
PATCH = {"left": 100, "width": 700, "text": [NEW_TEXT]}


@pytest.fixture
def run(capsys):
    def _run(*argv):
        capsys.readouterr()
        rc = cli.main(list(argv))
        cap = capsys.readouterr()
        return rc, cap.out, cap.err

    return _run


@pytest.fixture
def env(tmp_path, monkeypatch, run, pkg):
    """表紙と本文の 2 ページ（どちらも 2 案）の作業フォルダ。原稿もあり、AI 判定が要る。"""
    monkeypatch.setenv("PPTX_MAKER_HOME", str(tmp_path / "home"))
    comp = pkg / "assets" / "components" / "layouts"
    base = tmp_path / "out" / "pptx-maker-source" / "demo"
    assert run("init", str(base))[0] == 0
    work = paths.resolve_work(base)
    write_slide(work / "slides", "01", (comp / "cover.html").read_text(encoding="utf-8"))
    write_slide(work / "slides", "02", (comp / "text.html").read_text(encoding="utf-8"))
    (work / "script.md").write_text(SCRIPT, encoding="utf-8")
    return base, work, tmp_path / "home"


def _record_ai(work, home):
    """pending_ai の項目を全部 ok で記録する。"""
    items = []
    for label in consulting.pending_ai(work, home):
        rule, place = label.split()[0], label.split()[1][:3]  # 「（断片が変わった）」の印は落とす
        items.append({"rule": rule, "page": "deck" if place == "全体" else place[1:], "status": "ok", "message": ""})
    rulebook.import_reviews(work, {"reviews": items}, home)
    assert consulting.pending_ai(work, home) == []


def _edit_and_share(work):
    """review.html を開き、本文ページを編集して「Claude に渡す」がコピーした JSON を返す。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(CLIP)
        pg.goto((work / "review.html").as_uri())
        pg.wait_for_function("document.querySelectorAll('.rvh').length > 0")
        pg.evaluate("p => __rvEdit.set('02', 'R1', 4, p)", PATCH)
        pg.click("#share")
        pg.wait_for_function("window.__copied")
        data = json.loads(pg.evaluate("window.__copied"))
        browser.close()
    assert errors == []
    return data


def _paste(work, data, tmp_path):
    f = tmp_path / "paste.txt"
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return cli.main(["choices-import", str(work), "--file", str(f)])


def test_編集した位置と文言が_PPTX_に出る(env, run, tmp_path):
    base, work, home = env
    # 全ページ承認・AI 判定済みの状態から始める
    write_choices(work, {"01": "R1", "02": "R1"}, work)
    _record_ai(work, home)
    assert run("review-page", str(base), "--no-open", "--no-measure")[0] == 0

    data = _edit_and_share(work)
    assert data["pages"]["02"]["status"] == "saved"
    assert data["pages"]["02"]["edits"]["R1"]["items"] == {str(BODY): PATCH}
    assert _paste(work, data, tmp_path) == 0
    frag = (work / "slides" / "02-R1.html").read_text(encoding="utf-8")
    assert OLD_TEXT not in frag
    assert NEW_TEXT in frag
    assert json.loads((work / "choices" / "02.json").read_text(encoding="utf-8"))["status"] == "saved"

    # 取り込んだだけでは承認が外れていて finalize は止まる
    rc, _, err = run("finalize", str(base), "--choices", str(work))
    assert rc == 2, err
    assert "S02" in err
    assert not (work / "final.html").exists()

    # 再承認しても、AI 判定の記録は消えたままなので止まる
    assert run("review-page", str(base), "--no-open", "--no-measure")[0] == 0
    write_choices(work, {"01": "R1", "02": "R1"}, work)
    rc, _, err = run("finalize", str(base), "--choices", str(work))
    assert rc == 2, err
    assert "AI 判定が済んでいません" in err

    _record_ai(work, home)
    assert run("finalize", str(base), "--choices", str(work))[0] == 0
    rc, out, _ = run("build", str(base))
    assert rc == 0, out
    assert [v for v in json.loads(out)["violations"] if v["severity"] == "error"] == []

    slide = Presentation(str(base.parent.parent / "demo.pptx")).slides[1]
    hit = [s for s in slide.shapes if s.has_text_frame and s.text_frame.text == NEW_TEXT]
    assert len(hit) == 1
    assert abs(hit[0].left - round(100 * 9525)) <= 9525
    assert not [s for s in slide.shapes if s.has_text_frame and s.text_frame.text == OLD_TEXT]


def test_案を選ばないまま編集して貼り付けても_pick_は_null_のまま断片が書き換わる(env, tmp_path):
    base, work, _ = env
    assert cli.main(["review-page", str(base), "--no-open", "--no-measure"]) == 0
    data = _edit_and_share(work)
    assert data["pages"]["02"]["pick"] is None
    assert _paste(work, data, tmp_path) == 0
    saved = json.loads((work / "choices" / "02.json").read_text(encoding="utf-8"))
    assert (saved["pick"], saved["status"]) == (None, "saved")
    frag = (work / "slides" / "02-R1.html").read_text(encoding="utf-8")
    assert NEW_TEXT in frag
    assert "left:100px" in frag
    assert OLD_TEXT in (work / "slides" / "02-R2.html").read_text(encoding="utf-8")
