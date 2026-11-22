# ruff: noqa: S101  # pytest の assert
"""finalize（選択結果 → final.html）のテスト。"""

import json

import pytest
from pptx_maker import candidates, choices, cli, finalize, initdir, paths, rulebook

from tests._flow import copied


def _slides(work, **frags):
    d = work / "slides"
    d.mkdir(parents=True, exist_ok=True)
    for f in d.glob("*.html"):
        f.unlink()
    for name, body in frags.items():
        (d / f"{name}.html").write_text(body, encoding="utf-8")


def _choice(work, base, nn, pick="R1", status="approved", comment="", frag=True):
    """承認済みなら、いまの断片の指紋（frag）も書く。frag=False は旧形式の承認。"""
    d = base / "choices"
    d.mkdir(parents=True, exist_ok=True)
    data = {"at": "2026-11-08T00:00:00.000Z", "comment": comment, "pick": pick, "status": status}
    html = candidates.collect(work).get(nn, {}).get(pick) if isinstance(pick, str) else None
    if frag and status == "approved" and html is not None:
        data["frag"] = choices.fragment_hash(html)
    (d / f"{nn}.json").write_text(json.dumps(data), encoding="utf-8")


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
    _choice(work, ch, "02", "R2")
    _choice(work, ch, "01", "R1")
    out = finalize.finalize(work, ch)
    html = out.read_text(encoding="utf-8")
    assert out == work / "final.html"
    assert html.index("ONE") < html.index("TWO2")
    assert "TWO1" not in html
    assert html.endswith("</body></html>")


def test_final_html_has_no_review_markup(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02", "R1")
    finalize.finalize(work, ch)
    html = (work / "final.html").read_text(encoding="utf-8")
    assert "rv-" not in html
    assert not (work / "final-review.html").exists()


def test_unapproved_stops(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02", "R1", status="saved")
    with pytest.raises(ValueError, match="S02"):
        finalize.finalize(work, ch)


def test_empty_choices_stops(work, tmp_path):
    (tmp_path / "ch" / "choices").mkdir(parents=True)
    with pytest.raises(ValueError, match="空"):
        finalize.finalize(work, tmp_path / "ch")


def test_missing_page_stops(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    with pytest.raises(ValueError, match="S02: 選択結果がありません"):
        finalize.finalize(work, ch)


def test_pick_missing_candidate(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", "R3")
    _choice(work, ch, "02", "R1")
    with pytest.raises(ValueError, match="S01.*R3"):
        finalize.finalize(work, ch)


def test_pick_none_stops(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", None)
    _choice(work, ch, "02", "R1")
    with pytest.raises(ValueError, match="S01"):
        finalize.finalize(work, ch)


def test_comment_stops_and_problems_are_collected(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", "R1", comment="文言を直す")
    _choice(work, ch, "02", "R1", status="saved")
    with pytest.raises(ValueError, match="S01") as e:
        finalize.finalize(work, ch)
    assert "コメント未反映" in str(e.value)
    assert "S01" in str(e.value)
    assert "S02" in str(e.value)


def test_cli_choices(work, tmp_path, capsys):
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02", "R1")
    assert cli.main(["finalize", str(work), "--choices", str(ch)]) == 0
    assert "TWO1" in (work / "final.html").read_text(encoding="utf-8")


def test_cli_choices_error_exit_2(work, tmp_path, capsys):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", status="saved")
    _choice(work, ch, "02", "R1")
    assert cli.main(["finalize", str(work), "--choices", str(ch)]) == 2
    assert "エラー" in capsys.readouterr().err


def test_choices_なしは作業フォルダに触れず終了コード2(work, capsys):
    (work / "theme.css").unlink()
    assert cli.main(["finalize", str(work)]) == 2
    assert "--choices" in capsys.readouterr().err
    assert not (work / "theme.css").exists()  # 派生ファイルの再生成より先に止まる


def test_pick_が文字列でなければ_ValueError_で止まる(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", pick=["R1"])
    _choice(work, ch, "02", "R1")
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
        rule, place = label.split()[0], label.split()[1][:3]  # 「（断片が変わった）」の印は落とす
        items.append({"rule": rule, "page": "deck" if place == "全体" else place[1:], "status": "ok", "message": ""})
    return {"reviews": items}


def test_AI判定が未実施なら_finalize_は止まる(work, tmp_path):
    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02")
    with pytest.raises(ValueError, match="AI 判定が済んでいません") as e:
        finalize.finalize(work, ch, home=tmp_path / "none")
    assert "R01 全体" in str(e.value)
    assert "R35 S02" in str(e.value)  # 本文スライドごとの判定も求める
    assert not (work / "final.html").exists()


def test_cli_AI判定が未実施なら_finalize_は終了コード2で止まる(work, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PPTX_MAKER_HOME", str(tmp_path / "home"))
    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02")
    assert cli.main(["finalize", str(work), "--choices", str(ch)]) == 2
    assert "AI 判定が済んでいません" in capsys.readouterr().err
    assert not (work / "final.html").exists()


def test_AI判定を全部記録すれば_finalize_は通る(work, tmp_path):
    from pptx_maker import consulting

    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02")
    home = tmp_path / "none"
    rulebook.import_reviews(work, _ai_reviews(consulting.pending_ai(work, home)), home)
    assert consulting.pending_ai(work, home) == []
    assert finalize.finalize(work, ch, home=home) == work / "final.html"


def test_script_md_がなければ_AI判定は求めない(work):
    from pptx_maker import consulting

    assert consulting.pending_ai(work, None) == []


def test_原稿にあるスライドの断片がなければ_承認済みでも止まる(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", "R1")
    _choice(work, ch, "02", "R1")
    script = "## S01 表紙\n- layout: cover\n\n## S02 本文\n\n## S03 まとめ\n"
    (work / "script.md").write_text(script, encoding="utf-8")
    with pytest.raises(ValueError, match="S03.*断片"):
        finalize.finalize(work, ch)
    assert not (work / "final.html").exists()


def test_承認のあとで断片を直すと_finalize_が止まる(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02", "R1")
    finalize.finalize(work, ch)  # 変えなければ通る
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 直した</section>", encoding="utf-8")
    with pytest.raises(ValueError, match="S02: 承認のあとで断片が変わっています") as e:
        finalize.finalize(work, ch)
    assert "S01" not in str(e.value)


def test_旧形式の承認は断片の指紋がなく止まる(work, tmp_path):
    ch = tmp_path / "ch"
    _choice(work, ch, "01", frag=False)
    _choice(work, ch, "02", "R1", frag=False)
    with pytest.raises(ValueError, match="S01: 古い形式の承認のため、断片の指紋がありません") as e:
        finalize.finalize(work, ch)
    assert "S01: 古い形式の承認のため、断片の指紋がありません" in str(e.value)
    assert "S02: 古い形式の承認のため、断片の指紋がありません" in str(e.value)


def _import(work, capsys, pages):
    f = _paste(work, "p.txt", pages)
    capsys.readouterr()
    assert cli.main(["choices-import", str(work), "--file", f]) == 0


def _read(work, nn):
    return json.loads((work / "choices" / f"{nn}.json").read_text(encoding="utf-8"))


def test_choices_import_は承認ページだけに_frag_を書く(work, capsys):
    _import(
        work,
        capsys,
        {
            "01": {"pick": "R1", "status": "approved", "comment": ""},
            "02": {"pick": "R2", "status": "saved", "comment": ""},
        },
    )
    assert _read(work, "01")["frag"] == choices.fragment_hash("<section>ONE</section>")
    assert "frag" not in _read(work, "02")


def test_frag_があっても選択ページの_base_と_check_は変わらない(work, capsys):
    pages = {"01": {"pick": "R1", "status": "approved", "comment": ""}}
    _import(work, capsys, pages)
    state = choices.read_state(work)
    assert "frag" not in state["01"]
    with_frag = choices.stamp(work)
    data = _read(work, "01")
    del data["frag"]
    (work / "choices" / "01.json").write_text(json.dumps(data), encoding="utf-8")
    assert choices.stamp(work) == with_frag
    assert choices.read_state(work) == state


def _fr_error(work, capsys, pages, **over):
    f = _paste(work, "p.txt", pages, **over)
    capsys.readouterr()
    assert cli.main(["choices-import", str(work), "--file", f]) == 2
    assert not (work / "choices").exists() or not list((work / "choices").glob("*.json"))
    return capsys.readouterr().err


def test_断片を直したあとの古いタブの承認は_fr_が古く断られて何も書かれない(work, capsys):
    stale = choices.fragment_hash("<section>ONE</section>")
    f = work / "slides" / "01-R1.html"
    f.write_text("<section>直した</section>", encoding="utf-8")
    err = _fr_error(work, capsys, {"01": {"pick": "R1", "status": "approved", "comment": "", "fr": stale}})
    assert "01: 古い断片を承認しています" in err


def test_承認のページに_fr_がない_json_は断られる(work, capsys):
    pages = {"01": {"pick": "R1", "status": "approved", "comment": ""}}
    f = work.parent / "p.txt"
    f.write_text(  # copied は fr を足すので、fr のない旧形式は手で作る
        json.dumps(
            {"pptx-maker-review": 1, "base": choices.stamp(work), "check": choices.checksum(pages), "pages": pages}
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert cli.main(["choices-import", str(work), "--file", str(f)]) == 2
    assert "01: fr がありません" in capsys.readouterr().err
    assert not (work / "choices").exists() or not list((work / "choices").glob("*.json"))


def test_fr_が今の指紋と一致する承認は通り_frag_が書かれる(work, capsys):
    fr = choices.fragment_hash("<section>ONE2</section>")
    _import(work, capsys, {"01": {"pick": "R2", "status": "approved", "comment": "", "fr": fr}})
    assert _read(work, "01")["frag"] == fr


def test_saved_のページは_fr_なしで通る(work, capsys):
    _import(work, capsys, {"01": {"pick": "R1", "status": "saved", "comment": ""}})
    assert "frag" not in _read(work, "01")


def _reviews(work):
    return {
        (r["rule"], r["page"]) for r in json.loads((work / "rule-review.json").read_text(encoding="utf-8"))["reviews"]
    }


def test_指紋が変わった再承認だけが_AI_判定を消す(work, capsys):
    pages = {"01": {"pick": "R1", "status": "approved", "comment": ""}}
    _import(work, capsys, pages)
    ok = {"status": "ok", "message": ""}
    paths.write_json(
        work / "rule-review.json",
        {"reviews": [{"rule": "R05", "page": "01", **ok}, {"rule": "R05", "page": "02", **ok}]},
    )
    _import(work, capsys, pages)  # 断片が同じ
    assert _reviews(work) == {("R05", "01"), ("R05", "02")}
    (work / "slides" / "01-R1.html").write_text("<section>ONE 直した</section>", encoding="utf-8")
    _import(work, capsys, pages)  # 断片が変わった
    assert _reviews(work) == {("R05", "02")}


def test_新規の承認は_AI_判定を消さない(work, capsys):
    paths.write_json(
        work / "rule-review.json", {"reviews": [{"rule": "R05", "page": "01", "status": "ok", "message": ""}]}
    )
    _import(work, capsys, {"01": {"pick": "R1", "status": "approved", "comment": ""}})
    assert _reviews(work) == {("R05", "01")}


def test_choices_resolve_のあとは_frag_がない(work, capsys):
    _import(work, capsys, {"01": {"pick": "R1", "status": "approved", "comment": ""}})
    d = _read(work, "01") | {"comment": "直す"}
    (work / "choices" / "01.json").write_text(json.dumps(d), encoding="utf-8")
    assert cli.main(["choices-resolve", str(work), "01"]) == 0
    after = _read(work, "01")
    assert after["status"] == "saved"
    assert "frag" not in after


def test_固定の入力で_fragment_hash_が決まった値になる():
    assert choices.fragment_hash("<section>ONE</section>") == "a37d24f5c367"


def test_review_page_は指紋の合わない承認を_saved_で埋め込む(work, capsys):
    from pptx_maker import review_page

    _import(
        work,
        capsys,
        {
            "01": {"pick": "R1", "status": "approved", "comment": ""},
            "02": {"pick": "R1", "status": "approved", "comment": ""},
        },
    )
    stamp, disk = choices.stamp(work), choices.read_state(work)
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 直した</section>", encoding="utf-8")
    state = review_page._embedded_state(work, candidates.collect(work))
    assert state["01"]["status"] == "approved"
    assert state["02"]["status"] == "saved"
    assert choices.read_state(work) == disk
    assert choices.stamp(work) == stamp
    review_page.build(work, measure=False)
    assert '"status": "saved"' in (work / "review.html").read_text(encoding="utf-8")


def _paste_one(work, capsys, status="approved", pick="R1"):
    f = _paste(work, "p.txt", {"01": {"pick": pick, "status": status, "comment": ""}})
    capsys.readouterr()
    return f


def _seed_review(work):
    paths.write_json(
        work / "rule-review.json", {"reviews": [{"rule": "R05", "page": "01", "status": "ok", "message": ""}]}
    )


def test_判定の削除が失敗したら承認は書かれず_貼り直せる(work, capsys, monkeypatch):
    _import(work, capsys, {"01": {"pick": "R1", "status": "approved", "comment": ""}})
    _seed_review(work)
    before = _read(work, "01")
    f = _paste_one(work, capsys, pick="R2")  # 指紋が変わる
    monkeypatch.setattr(rulebook, "_write_reviews", lambda *a: (_ for _ in ()).throw(OSError("ロック")))
    assert cli.main(["choices-import", str(work), "--file", f]) == 2
    assert _read(work, "01") == before
    monkeypatch.undo()
    assert cli.main(["choices-import", str(work), "--file", f]) == 0
    assert _read(work, "01")["pick"] == "R2"
    assert _reviews(work) == set()


@pytest.mark.parametrize("body", ['{"reviews":[1]}', '{"reviews":[{"rule":"R05"}]}'])
def test_壊れた_rule_review_は_ValueError_で終了コード_2(work, capsys, body):
    (work / "rule-review.json").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="壊れています"):
        rulebook.read_reviews(work)
    f = _paste_one(work, capsys)
    assert cli.main(["choices-import", str(work), "--file", f]) == 2
    assert not (work / "choices" / "01.json").exists()


def test_承認から_saved_に戻しても判定は消えない(work, capsys):
    _import(work, capsys, {"01": {"pick": "R1", "status": "approved", "comment": ""}})
    _seed_review(work)
    _import(work, capsys, {"01": {"pick": "R1", "status": "saved", "comment": ""}})
    assert _reviews(work) == {("R05", "01")}


def test_pick_だけ変えた承認は判定を消す(work, capsys):
    _import(work, capsys, {"01": {"pick": "R1", "status": "approved", "comment": ""}})
    _seed_review(work)
    _import(work, capsys, {"01": {"pick": "R2", "status": "approved", "comment": ""}})
    assert _reviews(work) == set()


# --- AI 判定の鮮度（記録時の断片の指紋 frag） ---


def _record(work, home, *labels):
    """pending_ai のうち labels（例 "R19 S02"）だけを ok で記録する。labels がなければ全部。"""
    from pptx_maker import consulting

    todo = [x for x in consulting.pending_ai(work, home) if not labels or x.split("（")[0] in labels]
    rulebook.import_reviews(work, _ai_reviews(todo), home)


def _rec(work, rule, page):
    return next(r for r in rulebook.read_reviews(work) if (r["rule"], r["page"]) == (rule, page))


def _pend_raw(work, home):
    from pptx_maker import consulting

    return consulting.pending_ai(work, home)


def _pend(work, home):
    """印（「（断片が変わった）」）を落とした、再判定が要る場所の一覧。"""
    return [x.split("（")[0] for x in _pend_raw(work, home)]


@pytest.fixture
def scripted(work, tmp_path):
    (work / "script.md").write_text(_SCRIPT, encoding="utf-8")
    return work, tmp_path / "none"


def test_rule_review_import_はページの判定だけに_frag_を付ける(scripted):
    work, home = scripted
    _record(work, home)
    assert _rec(work, "R35", "02")["frag"] == choices.page_frag(candidates.collect(work)["02"])
    assert "frag" not in _rec(work, "R01", "deck")
    assert _pend(work, home) == []


def test_判定のあとで断片を直すと_pending_に戻り_finalize_が止まる(scripted, tmp_path):
    work, home = scripted
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02", "R1")
    _record(work, home)
    (work / "slides" / "02-R2.html").write_text("<section>TWO2 直した</section>", encoding="utf-8")  # 選ばれない案
    pend = _pend(work, home)
    assert "R35 S02" in pend
    assert "R35 S01" not in pend
    assert not any(p.endswith("全体") for p in pend)
    from pptx_maker import consulting

    msg = next(x for x in consulting.evaluate(work, home)["pages"]["02"]["deck_rules"] if x["rule"] == "R35")
    assert (msg["status"], msg["by"]) == ("pending", "AI")
    assert "断片が変わった" in msg["message"]
    with pytest.raises(ValueError, match="AI 判定が済んでいません"):
        finalize.finalize(work, ch, home=home)


def test_断片が同じなら判定は有効のまま(scripted, tmp_path):
    work, home = scripted
    ch = tmp_path / "ch"
    _choice(work, ch, "01")
    _choice(work, ch, "02")
    _record(work, home)
    (work / "slides" / "02-R1.html").write_text("<section>TWO1</section>", encoding="utf-8")  # 同じ中身で書き直す
    assert _pend(work, home) == []
    assert finalize.finalize(work, ch, home=home) == work / "final.html"


def test_別ページの断片の変更では他のページの判定は有効(scripted):
    work, home = scripted
    _record(work, home)
    (work / "slides" / "01-R1.html").write_text("<section>ONE 直した</section>", encoding="utf-8")
    assert _pend(work, home) == []  # 表紙（S01）はページ単位の AI 判定がなく、S02 の判定は有効のまま


def test_frag_のない古い記録は有効のまま(scripted):
    work, home = scripted
    _record(work, home)
    data = json.loads((work / "rule-review.json").read_text(encoding="utf-8"))
    for r in data["reviews"]:
        r.pop("frag", None)
    paths.write_json(work / "rule-review.json", data)
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 直した</section>", encoding="utf-8")
    assert _pend(work, home) == []


def test_saved_のまま断片を直したあとで初めて承認しても判定は_pending(scripted, capsys):
    """以前の既知の穴: 承認 → 保存済み → 直して再承認。判定が消えない経路でも、断片が違えば pending。"""
    work, home = scripted
    _import(work, capsys, {"02": {"pick": "R1", "status": "saved", "comment": ""}})  # まだ承認していない
    _record(work, home)
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 直した</section>", encoding="utf-8")
    _import(work, capsys, {"02": {"pick": "R1", "status": "approved", "comment": ""}})  # 初めての承認
    assert _rec(work, "R35", "02")  # clear_stale は消さない（以前の穴）
    assert "R35 S02" in _pend(work, home)
    _record(work, home, "R35 S02")
    _import(work, capsys, {"02": {"pick": "R1", "status": "saved", "comment": ""}})  # 承認 → 保存済み
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 さらに直した</section>", encoding="utf-8")
    assert "R35 S02" in _pend(work, home)


def test_案の追加と削除でも判定は_pending(scripted):
    work, home = scripted
    _record(work, home)
    extra = work / "slides" / "02-R3.html"
    extra.write_text("<section>TWO3</section>", encoding="utf-8")
    assert "R35 S02" in _pend(work, home)
    _record(work, home, "R35 S02")
    assert "R35 S02" not in _pend(work, home)
    extra.unlink()
    assert "R35 S02" in _pend(work, home)


def test_pick_だけ変えても断片が同じなら判定は有効(scripted, capsys):
    work, home = scripted
    _import(work, capsys, {"02": {"pick": "R1", "status": "saved", "comment": ""}})
    _record(work, home)
    # saved の pick 変更は判定を消さない
    _import(work, capsys, {"02": {"pick": "R2", "status": "saved", "comment": ""}})
    assert _pend(work, home) == []


def test_断片の検査に落ちている間は_ページの判定を記録できず_既存の記録は残る(scripted):
    work, home = scripted
    _record(work, home, "R35 S02")
    before = (work / "rule-review.json").read_text(encoding="utf-8")
    (work / "slides" / "99-X.html").write_text("<section>x</section>", encoding="utf-8")  # 名前が読めない
    page = {"reviews": [{"rule": "R19", "page": "02", "status": "ok", "message": ""}]}
    with pytest.raises(ValueError, match="断片の検査に落ちています"):
        rulebook.import_reviews(work, page, home)
    assert (work / "rule-review.json").read_text(encoding="utf-8") == before


def test_deck_だけの記録は_断片の検査に落ちていても通る(scripted):
    work, home = scripted
    (work / "slides" / "99-X.html").write_text("<section>x</section>", encoding="utf-8")
    deck = {"reviews": [{"rule": "R01", "page": "deck", "status": "ok", "message": ""}]}
    assert rulebook.import_reviews(work, deck, home) == 1
    assert "frag" not in _rec(work, "R01", "deck")


def test_断片のないページには_ページの判定を記録できない(scripted):
    work, home = scripted
    (work / "script.md").write_text(_SCRIPT + "\n## S03 まとめ\n- layout: closing\n", encoding="utf-8")
    with pytest.raises(ValueError, match="スライド 03 に断片がありません"):
        rulebook.import_reviews(work, {"reviews": [{"rule": "R19", "page": "03", "status": "ok", "message": ""}]}, home)
    assert not (work / "rule-review.json").exists()


def test_pending_ai_は断片が変わったものにだけ印を付ける(scripted):
    work, home = scripted
    _record(work, home, *[x for x in _pend(work, home) if x != "R35 S02"])  # R35 S02 は記録しない
    assert _pend_raw(work, home) == ["R35 S02"]
    _record(work, home, "R35 S02")
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 直した</section>", encoding="utf-8")
    raw = _pend_raw(work, home)
    assert "R35 S02（断片が変わった）" in raw
    assert all(x.endswith("（断片が変わった）") for x in raw)


@pytest.mark.parametrize("frag", ["", "abc", "ABCDEF012345", "0123456789abcd", 123])
def test_不正な形式の_frag_は_ValueError(scripted, frag):
    work, home = scripted
    paths.write_json(
        work / "rule-review.json",
        {"reviews": [{"rule": "R35", "page": "02", "status": "ok", "message": "", "frag": frag}]},
    )
    with pytest.raises(ValueError, match="frag"):
        rulebook.read_reviews(work)


def test_review_html_は断片が変わった判定を_pending_で埋め込む(scripted):
    import re

    from pptx_maker import review_page

    work, home = scripted
    _record(work, home)

    def r35():
        review_page.build(work, measure=False)
        html = (work / "review.html").read_text(encoding="utf-8")
        data = json.loads(re.search(r'id="rv-data">(.*?)</script>', html, re.S)[1])
        return next(x for x in data["pages"]["02"]["deck_rules"] if x["rule"] == "R35")["status"]

    assert r35() == "ok"
    (work / "slides" / "02-R1.html").write_text("<section>TWO1 直した</section>", encoding="utf-8")
    assert r35() == "pending"  # 表示側は pending を「AI判定待ち」と描く（test_review_page_checks）
