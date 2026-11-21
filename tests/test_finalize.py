# ruff: noqa: S101  # pytest の assert
"""finalize（選択結果 → final.html）のテスト。"""

import json

import pytest
from pptx_maker import cli, finalize, initdir, paths

from tests._flow import copied


def _slides(work, **frags):
    d = work / "slides"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.html"):
        f.unlink()
    for name, body in frags.items():
        (d / f"{name}.html").write_text(body, encoding="utf-8")


def _choice(base, nn, pick="R1", status="approved", comment=""):
    d = base / "choices"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{nn}.json").write_text(
        json.dumps({"at": "2026-11-08T00:00:00.000Z", "comment": comment, "pick": pick, "status": status}),
        encoding="utf-8",
    )


@pytest.fixture
def work(tmp_path):
    base = tmp_path / "out" / "pptx-maker-source" / "demo"
    initdir.init(base)
    w = paths.resolve_work(base)
    _slides(
        w,
        **{
            "01-R1": "<section>ONE</section>",
            "01-R2": "<section>ONE2</section>",
            "02-R1": "<section>TWO1</section>",
            "02-R2": "<section>TWO2</section>",
        },
    )
    return w


def test_all_approved(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "02", "R2")
    _choice(ch, "01", "R1")
    out = finalize.finalize(work, ch)
    html = out.read_text(encoding="utf-8")
    assert out == work / "final.html"
    assert html.index("ONE") < html.index("TWO2")
    assert "TWO1" not in html
    assert html.endswith("</body></html>")


def test_final_html_has_no_review_markup(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01")
    _choice(ch, "02", "R1")
    finalize.finalize(work, ch)
    html = (work / "final.html").read_text(encoding="utf-8")
    assert "rv-" not in html
    assert not (work / "final-review.html").exists()


def test_unapproved_stops(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01")
    _choice(ch, "02", "R1", status="saved")
    with pytest.raises(ValueError, match="S02"):
        finalize.finalize(work, ch)


def test_empty_choices_stops(work, tmp_path):
    (tmp_path / "ch" / "choices").mkdir(parents=True)
    with pytest.raises(ValueError, match="空"):
        finalize.finalize(work, tmp_path / "ch")


def test_missing_page_stops(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01")
    with pytest.raises(ValueError, match="S02: 選択結果がありません"):
        finalize.finalize(work, ch)


def test_pick_missing_candidate(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01", "R3")
    _choice(ch, "02", "R1")
    with pytest.raises(ValueError, match="S01.*R3"):
        finalize.finalize(work, ch)


def test_pick_none_stops(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01", None)
    _choice(ch, "02", "R1")
    with pytest.raises(ValueError, match="S01"):
        finalize.finalize(work, ch)


def test_comment_stops_and_problems_are_collected(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01", "R1", comment="文言を直す")
    _choice(ch, "02", "R1", status="saved")
    with pytest.raises(ValueError, match="S01") as e:
        finalize.finalize(work, ch)
    assert "コメント未反映" in str(e.value)
    assert "S01" in str(e.value)
    assert "S02" in str(e.value)


def test_cli_choices(work, tmp_path, capsys):
    ch = tmp_path / "ch"
    _choice(ch, "01")
    _choice(ch, "02", "R1")
    assert cli.main(["finalize", str(work), "--choices", str(ch)]) == 0
    assert "TWO1" in (work / "final.html").read_text(encoding="utf-8")


def test_cli_choices_error_exit_2(work, tmp_path, capsys):
    ch = tmp_path / "ch"
    _choice(ch, "01", status="saved")
    _choice(ch, "02", "R1")
    assert cli.main(["finalize", str(work), "--choices", str(ch)]) == 2
    assert "エラー" in capsys.readouterr().err


def test_choices_なしは作業フォルダに触れず終了コード2(work, capsys):
    (work / "theme.css").unlink()
    assert cli.main(["finalize", str(work)]) == 2
    assert "--choices" in capsys.readouterr().err
    assert not (work / "theme.css").exists()  # 派生ファイルの再生成より先に止まる


def test_pick_が文字列でなければ_ValueError_で止まる(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01", pick=["R1"])
    _choice(ch, "02", "R1")
    with pytest.raises(ValueError, match="S01"):
        finalize.finalize(work, ch)


def _paste(work, name, pages, **over):
    f = work.parent / name
    f.write_text(copied(work, pages, **over), encoding="utf-8")
    return str(f)


def test_cli_choices_import_resolve_then_finalize(work, capsys):
    """ページがコピーした JSON → choices-import → コメントに応える → choices-resolve → 再承認 → finalize。"""
    _slides(work, **{"01-R1": '<section class="slide">ONE</section>', "01-R2": '<section class="slide">TWO</section>'})
    first = _paste(work, "p1.txt", {"01": {"pick": "R2", "status": "saved", "comment": "直す"}})
    capsys.readouterr()
    assert cli.main(["choices-import", str(work), "--file", first]) == 0
    assert json.loads(capsys.readouterr().out) == {"comments": [{"slide": "01", "comment": "直す"}]}
    assert cli.main(["finalize", str(work), "--choices", str(work)]) == 2  # コメント未反映
    assert cli.main(["choices-resolve", str(work), "01"]) == 0
    # ページを作り直して開き直した利用者が、承認して渡す。古いページ（first）からの貼り付けは断る
    assert cli.main(["choices-import", str(work), "--file", first]) == 2
    assert "古いページ" in capsys.readouterr().err
    second = _paste(work, "p2.txt", {"01": {"pick": "R2", "status": "approved", "comment": ""}})
    assert cli.main(["choices-import", str(work), "--file", second]) == 0
    assert cli.main(["finalize", str(work), "--choices", str(work)]) == 0
    assert "TWO" in (work / "final.html").read_text(encoding="utf-8")


def test_cli_choices_import_rejects_unknown_slide_or_pick(work, capsys):
    _slides(work, **{"01-R1": "<section>ONE</section>", "01-R2": "<section>TWO</section>"})
    bad = _paste(work, "p.txt", {"01": {"pick": "R3", "status": "saved", "comment": ""}})
    capsys.readouterr()
    assert cli.main(["choices-import", str(work), "--file", bad]) == 2
    assert "案 R3 はありません" in capsys.readouterr().err
    assert not (work / "choices").exists()


def test_cli_choices_import_reports_bad_file(work, capsys):
    bad = work.parent / "bad.txt"
    bad.write_text("ただの文章", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["choices-import", str(work), "--file", str(bad)]) == 2
    assert capsys.readouterr().err.startswith("エラー:")


# --- AI 判定の関門 ---

_SCRIPT = (
    "# 題\n"
    "## S01 表紙\n- layout: cover\n- ヘッドメッセージ: 表紙のメッセージです\n\n"
    "## S02 本文\n- layout: content\n- 章名: 何が変わるか\n- ヘッドメッセージ: 原価を絞れば利益が増える\n"
    "- 本文:\n  - 要点\n- 主役の図表: 表 — 比較\n- 読み手にさせたいこと: 承認\n"
)


def _ai_reviews(pending):
    """pending_ai の「R01 全体」「R35 S02」を、全部 ok の判定にする。"""
    items = []
    for label in pending:
        rule, place = label.split()
        items.append({"rule": rule, "page": "deck" if place == "全体" else place[1:], "status": "ok", "message": ""})
    return {"reviews": items}


def test_AI判定が未実施なら_finalize_は止まる(work, tmp_path):
    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    ch = tmp_path / "ch"
    _choice(ch, "01")
    _choice(ch, "02")
    with pytest.raises(ValueError, match="AI 判定が済んでいません") as e:
        finalize.finalize(work, ch, home=tmp_path / "none")
    assert "R01 全体" in str(e.value)
    assert "R35 S02" in str(e.value)  # 本文スライドごとの判定も求める
    assert not (work / "final.html").exists()


def test_cli_AI判定が未実施なら_finalize_は終了コード2で止まる(work, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PPTX_MAKER_HOME", str(tmp_path / "home"))
    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    ch = tmp_path / "ch"
    _choice(ch, "01")
    _choice(ch, "02")
    assert cli.main(["finalize", str(work), "--choices", str(ch)]) == 2
    assert "AI 判定が済んでいません" in capsys.readouterr().err
    assert not (work / "final.html").exists()


def test_AI判定を全部記録すれば_finalize_は通る(work, tmp_path):
    from pptx_maker import consulting, rulebook

    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    ch = tmp_path / "ch"
    _choice(ch, "01")
    _choice(ch, "02")
    home = tmp_path / "none"
    rulebook.import_reviews(work, _ai_reviews(consulting.pending_ai(work, home)), home)
    assert consulting.pending_ai(work, home) == []
    assert finalize.finalize(work, ch, home=home) == work / "final.html"


def test_script_md_がなければ_AI判定は求めない(work):
    from pptx_maker import consulting

    assert consulting.pending_ai(work, None) == []


def test_原稿にあるスライドの断片がなければ_承認済みでも止まる(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(ch, "01", "R1")
    _choice(ch, "02", "R1")
    script = "## S01 表紙\n- layout: cover\n\n## S02 本文\n\n## S03 まとめ\n"
    (work / "script.md").write_text(script, encoding="utf-8")
    with pytest.raises(ValueError, match="S03.*断片"):
        finalize.finalize(work, ch)
    assert not (work / "final.html").exists()
