"""ルールの管理（rule list／rule apply）・effective_rules・AI 判定の記録・R25・3 分類の登録簿。"""

# ruff: noqa: S101  # pytest の assert
import json

import pytest
from pptx_maker import candidates, cli, consulting

from tests.test_consulting import NOTE, _deck, _slides, _work


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("PPTX_MAKER_HOME", str(h))
    return h


def _run(capsys, *argv):
    code = cli.main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def _apply(capsys, tmp_path, ops, *flags):
    f = tmp_path / "ops.json"
    f.write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
    return _run(capsys, "rule", "apply", "--file", str(f), *flags)


def _custom_file(home):
    return home / "rules" / "custom.json"


# --- 登録簿（3 分類） ---

MACHINE = [
    "R06",
    "R10",
    "R12",
    "R13",
    "R14",
    "R15",
    "R16",
    "R17",
    "R18",
    "R20",
    "R22",
    "R23",
    "R25",
    "R26",
    "R28",
    "R30",
    "R31",
]
AI = ["R01", "R02", "R03", "R04", "R05", "R07", "R08", "R09", "R11", "R19", "R21", "R24", "R27", "R29", "R35"]
HUMAN = ["R32", "R33", "R34"]


def test_登録簿は_R01_から_R35_で_機械17_AI15_人3():
    assert [r["id"] for r in consulting.RULES] == [f"R{i:02d}" for i in range(1, 36)]
    by_kind = {k: [r["id"] for r in consulting.RULES if r["kind"] == k] for k in ("機械", "AI", "人")}
    assert by_kind == {"機械": MACHINE, "AI": AI, "人": HUMAN}


def test_AI_には採点表_人には質問_機械には場所がある():
    for r in consulting.RULES:
        if r["kind"] == "AI":
            assert r["where"] == "AI"
            assert 3 <= len(r["rubric"].splitlines()) <= 5, r["id"]
            assert "question" not in r
        elif r["kind"] == "人":
            assert r["where"] == "人"
            assert r["question"]
            assert "rubric" not in r
        else:
            assert r["where"] in {"script_lint", "candidates", "check"}
    assert {r["id"]: r["level"] for r in consulting.RULES if r["kind"] == "人"} == {
        "R32": "必須",
        "R33": "必須",
        "R34": "推奨",
    }


# --- R25 ---


def test_R25_文字量が上限を超えた案を指摘する():
    big = f'<div class="pp-text">{"あ" * (candidates.TEXT_MAX + 1)}</div>'
    ok = f'<div class="pp-text">{"あ" * candidates.TEXT_MAX}</div>'
    hits = [f for f in candidates.fragment_findings(big, body=True) if f["rule"] == "R25"]
    assert len(hits) == 1
    assert "R25" not in {f["rule"] for f in candidates.fragment_findings(ok, body=True)}


def test_R25_は_evaluate_で_warn(tmp_path):
    big = f'<div class="pp-text">{"あ" * (candidates.TEXT_MAX + 1)}</div>' + NOTE
    work = _work(tmp_path, _deck("- 論点: ①\n"), None, _slides() | {"02-R2.html": big})
    v = consulting.evaluate(work, home=tmp_path / "none")["pages"]["02"]["variants"]
    assert {x["rule"]: x["status"] for x in v["R2"]}["R25"] == "warn"
    assert {x["rule"]: x["status"] for x in v["R1"]}["R25"] == "ok"


# --- effective_rules ---


def _write_custom(home, data):
    _custom_file(home).parent.mkdir(parents=True, exist_ok=True)
    _custom_file(home).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_effective_rules_は_home_がなければ組み込みだけ(monkeypatch):
    monkeypatch.delenv("PPTX_MAKER_HOME", raising=False)
    assert consulting.effective_rules() == consulting.RULES


def test_effective_rules_は上書き_無効_カスタムを反映する(tmp_path):
    _write_custom(
        tmp_path,
        {
            "custom": [
                {
                    "id": "C01",
                    "name": "要検討",
                    "level": "必須",
                    "kind": "機械",
                    "where": "custom",
                    "description": "d",
                    "pattern": "要検討",
                    "scope": "slide",
                    "message": "m",
                }
            ],
            "overrides": {"R13": {"name": "改名", "level": "推奨"}, "R14": {"enabled": False}},
        },
    )
    eff = {r["id"]: r for r in consulting.effective_rules(tmp_path)}
    assert eff["R13"]["name"] == "改名"
    assert eff["R13"]["level"] == "推奨"
    assert "R14" not in eff
    assert eff["C01"]["pattern"] == "要検討"
    assert len(eff) == 35  # 35 - 1 + 1
    assert consulting.RULES[12]["name"] != "改名"  # 組み込みの定数は変わらない


# --- rule list ---


def test_rule_list_は有効なルールだけ_kind_で絞れる(home, capsys):
    code, out, _ = _run(capsys, "rule", "list")
    assert code == 0
    assert len(json.loads(out)) == 35
    code, out, _ = _run(capsys, "rule", "list", "--kind", "人")
    assert [r["id"] for r in json.loads(out)] == HUMAN


def test_rule_list_all_は無効も出し_enabled_と_source_を付ける(home, tmp_path, capsys):
    _apply(capsys, tmp_path, [{"op": "disable", "id": "R13"}, {"op": "edit", "id": "R14", "set": {"name": "x"}}])
    _, out, _ = _run(capsys, "rule", "list")
    assert "R13" not in {r["id"] for r in json.loads(out)}
    _, out, _ = _run(capsys, "rule", "list", "--all")
    by = {r["id"]: r for r in json.loads(out)}
    assert (by["R13"]["enabled"], by["R13"]["source"]) == (False, "上書きあり")
    assert (by["R14"]["enabled"], by["R14"]["source"]) == (True, "上書きあり")
    assert (by["R01"]["enabled"], by["R01"]["source"]) == (True, "組み込み")


def test_rule_list_は_data_がなければ終了コード2(monkeypatch, capsys):
    monkeypatch.delenv("PPTX_MAKER_HOME", raising=False)
    assert _run(capsys, "rule", "list")[0] == 2


# --- rule apply 正常系 ---

ADD_MACHINE = {
    "op": "add",
    "name": "要検討を残さない",
    "kind": "機械",
    "level": "必須",
    "description": "要検討の語を残さない",
    "scope": "slide",
    "pattern": "要検討",
    "message": "「要検討」が残っています",
}


def test_apply_add_は採番して_before_after_を返し保存する(home, tmp_path, capsys):
    code, out, _ = _apply(capsys, tmp_path, [ADD_MACHINE, {**ADD_MACHINE, "name": "二つ目"}])
    assert code == 0
    res = json.loads(out)
    assert res["written"] is True
    assert [(r["op"], r["id"], r["before"]) for r in res["results"]] == [("add", "C01", None), ("add", "C02", None)]
    assert res["results"][0]["after"]["pattern"] == "要検討"
    saved = json.loads(_custom_file(home).read_text(encoding="utf-8"))
    assert [c["id"] for c in saved["custom"]] == ["C01", "C02"]
    assert saved["custom"][0]["where"] == "custom"


def test_apply_edit_組み込みは上書きに残し_before_after_に差分が出る(home, tmp_path, capsys):
    _, out, _ = _apply(capsys, tmp_path, [{"op": "edit", "id": "R13", "set": {"name": "新名", "level": "推奨"}}])
    r = json.loads(out)["results"][0]
    assert (r["before"]["name"], r["after"]["name"]) == ("アクションタイトル", "新名")
    assert (r["before"]["level"], r["after"]["level"]) == ("必須", "推奨")
    saved = json.loads(_custom_file(home).read_text(encoding="utf-8"))
    assert saved["overrides"]["R13"] == {"name": "新名", "level": "推奨"}
    assert saved["custom"] == []


def test_apply_edit_カスタムの種類を変えると項目が入れ替わる(home, tmp_path, capsys):
    _apply(capsys, tmp_path, [ADD_MACHINE])
    code, out, _ = _apply(capsys, tmp_path, [{"op": "edit", "id": "C01", "set": {"kind": "人", "question": "確認?"}}])
    assert code == 0
    after = json.loads(out)["results"][0]["after"]
    assert (after["kind"], after["where"], after["question"]) == ("人", "人", "確認?")
    assert "pattern" not in after


def test_apply_AI_と人は種類を入れ替えられる(home, tmp_path, capsys):
    ops = [{"op": "edit", "id": "R32", "set": {"kind": "AI", "rubric": "ok: a\nwarn: b\nng: c"}}]
    code, out, _ = _apply(capsys, tmp_path, ops)
    assert code == 0
    assert json.loads(out)["results"][0]["after"]["where"] == "AI"
    assert "R32" in {r["id"] for r in consulting.effective_rules(home) if r["kind"] == "AI"}


def test_apply_remove_enable_disable_reset(home, tmp_path, capsys):
    _apply(
        capsys,
        tmp_path,
        [ADD_MACHINE, {"op": "disable", "id": "R13"}, {"op": "edit", "id": "R14", "set": {"name": "x"}}],
    )
    code, out, _ = _apply(
        capsys,
        tmp_path,
        [{"op": "remove", "id": "C01"}, {"op": "enable", "id": "R13"}, {"op": "reset", "id": "R14"}],
    )
    assert code == 0
    res = json.loads(out)["results"]
    assert res[0]["after"] is None
    assert res[0]["before"]["id"] == "C01"
    assert res[1]["before"]["enabled"] is False
    assert res[1]["after"]["enabled"] is True
    assert res[2]["after"]["name"] == "見出しの長さ"
    saved = json.loads(_custom_file(home).read_text(encoding="utf-8"))
    assert saved == {"custom": [], "overrides": {}}


def test_apply_dry_run_は書かない(home, tmp_path, capsys):
    code, out, _ = _apply(capsys, tmp_path, [ADD_MACHINE], "--dry-run")
    assert code == 0
    res = json.loads(out)
    assert res["written"] is False
    assert res["results"][0]["id"] == "C01"
    assert not _custom_file(home).exists()


def test_apply_同じ_apply_内の後の操作は前の操作を見る(home, tmp_path, capsys):
    ops = [ADD_MACHINE, {"op": "edit", "id": "C01", "set": {"message": "別の文"}}, {"op": "disable", "id": "C01"}]
    code, out, _ = _apply(capsys, tmp_path, ops)
    assert code == 0
    assert json.loads(out)["results"][1]["after"]["message"] == "別の文"
    assert "C01" not in {r["id"] for r in consulting.effective_rules(home)}


# --- rule apply 異常系 ---


def _fails(capsys, tmp_path, home, ops, needle):
    before = _custom_file(home).read_text(encoding="utf-8") if _custom_file(home).exists() else None
    code, out, err = _apply(capsys, tmp_path, ops)
    assert code == 2, err
    assert out == ""
    assert err.startswith("エラー: ")
    assert needle in err
    after = _custom_file(home).read_text(encoding="utf-8") if _custom_file(home).exists() else None
    assert after == before  # 何も書かない
    return err


def test_apply_組み込みの削除は無効にする案内つきで拒む(home, tmp_path, capsys):
    err = _fails(capsys, tmp_path, home, [ADD_MACHINE, {"op": "remove", "id": "R13"}], "2: ")
    assert "disable" in err


def test_apply_機械ルールの_kind_変更は不可(home, tmp_path, capsys):
    _fails(capsys, tmp_path, home, [{"op": "edit", "id": "R13", "set": {"kind": "AI", "rubric": "x"}}], "1: ")


def test_apply_AI_を機械にはできない(home, tmp_path, capsys):
    _fails(capsys, tmp_path, home, [{"op": "edit", "id": "R01", "set": {"kind": "機械"}}], "1: ")


def test_apply_不正な正規表現(home, tmp_path, capsys):
    _fails(capsys, tmp_path, home, [{**ADD_MACHINE, "pattern": "(未閉じ"}], "正規表現")


@pytest.mark.parametrize(
    ("op", "needle"),
    [
        ({"op": "add", "kind": "機械", "scope": "slide", "pattern": "x", "message": "m"}, "name"),
        ({"op": "add", "name": "n", "kind": "機械", "scope": "slide", "message": "m"}, "pattern"),
        ({"op": "add", "name": "n", "kind": "機械", "pattern": "x", "message": "m"}, "scope"),
        ({"op": "add", "name": "n", "kind": "機械", "scope": "body", "pattern": "x", "message": "m"}, "scope"),
        ({"op": "add", "name": "n", "kind": "機械", "scope": "slide", "pattern": "x"}, "message"),
        ({"op": "add", "name": "n", "kind": "AI"}, "rubric"),
        ({"op": "add", "name": "n", "kind": "人"}, "question"),
        ({"op": "add", "name": "n", "kind": "謎"}, "kind"),
        ({"op": "add", "name": "n", "kind": "人", "question": "q", "level": "任意"}, "level"),
    ],
)
def test_apply_必須項目の不足と不正な値(home, tmp_path, capsys, op, needle):
    _fails(capsys, tmp_path, home, [op], needle)


@pytest.mark.parametrize(
    "op",
    [
        {"op": "edit", "id": "R99", "set": {"name": "x"}},
        {"op": "remove", "id": "C09"},
        {"op": "enable", "id": "C09"},
        {"op": "reset", "id": "R99"},
    ],
)
def test_apply_存在しない_ID(home, tmp_path, capsys, op):
    _fails(capsys, tmp_path, home, [op], "存在しません")


@pytest.mark.parametrize(
    ("ops", "needle"),
    [
        ([{"op": "edit", "id": "R13", "set": {"pattern": "x"}}], "1: "),
        ([{"op": "edit", "id": "R13", "set": {"謎": "x"}}], "1: "),
        ([{"op": "edit", "id": "R13", "set": {}}], "1: "),
        ([{"op": "謎", "id": "R13"}], "1: "),
        ({"op": "add"}, "配列"),
    ],
)
def test_apply_そのほかの不可の操作(home, tmp_path, capsys, ops, needle):
    _fails(capsys, tmp_path, home, ops, needle)


def test_apply_カスタムの_reset_は不可(home, tmp_path, capsys):
    _apply(capsys, tmp_path, [ADD_MACHINE])
    _fails(capsys, tmp_path, home, [{"op": "reset", "id": "C01"}], "1: ")


def test_apply_ファイルがなければ終了コード2(home, capsys):
    assert _run(capsys, "rule", "apply", "--file", str(home / "nai.json"))[0] == 2


def test_apply_壊れた_JSON_は終了コード2(home, tmp_path, capsys):
    f = tmp_path / "bad.json"
    f.write_text("{", encoding="utf-8")
    assert _run(capsys, "rule", "apply", "--file", str(f))[0] == 2


# --- evaluate と管理されたルール ---


def test_evaluate_無効なルールは出さない(home, tmp_path):
    off = {"R13": {"enabled": False}, "R31": {"enabled": False}, "R12": {"enabled": False}}
    _write_custom(home, {"custom": [], "overrides": off})
    work = _work(tmp_path / "w", _deck("- 論点: ①\n"), None, _slides())
    r = consulting.evaluate(work)
    page = {x["rule"] for x in r["pages"]["02"]["deck_rules"]}
    assert "R13" not in page
    assert "R12" not in page
    assert "R31" not in {x["rule"] for x in r["pages"]["02"]["variants"]["R1"]}
    assert "R13" not in {x["id"] for x in r["rules"]}


def _c(id_, scope, pattern, message, level="推奨"):
    return {
        "id": id_,
        "name": id_,
        "level": level,
        "kind": "機械",
        "where": "custom",
        "description": "d",
        "scope": scope,
        "pattern": pattern,
        "message": message,
    }


def test_evaluate_カスタム機械ルールが該当する場所で評価される(home, tmp_path):
    custom = [
        _c("C01", "slide", "要検討", "断片に要検討"),
        _c("C02", "head", "見直す", "ヘッドに見直す", "必須"),
        _c("C03", "script", "要点", "本文に要点"),
    ]
    _write_custom(home, {"custom": custom, "overrides": {}})
    slides = _slides() | {"02-R2.html": '<div class="pp-text">これは<b>要</b>要検討です</div>' + NOTE}
    r = consulting.evaluate(_work(tmp_path / "w", _deck("- 論点: ①\n"), None, slides))
    page = {x["rule"]: x for x in r["pages"]["02"]["deck_rules"]}
    assert page["C02"]["status"] == "ng"
    assert page["C02"]["message"].startswith("ヘッドに見直す")
    assert page["C03"]["status"] == "warn"
    assert (page["C02"]["by"], page["C03"]["by"]) == ("機械", "機械")
    v = r["pages"]["02"]["variants"]
    assert {x["rule"]: x["status"] for x in v["R2"]}["C01"] == "warn"
    assert {x["rule"]: x["status"] for x in v["R1"]}["C01"] == "ok"
    assert "C02" not in {x["rule"] for x in r["pages"]["01"]["deck_rules"]}  # 表紙にヘッドの検査はしない


def test_evaluate_人のルールは_manual_と_human_の一覧(home, tmp_path):
    work = _work(tmp_path / "w", _deck("- 論点: ①\n"), None, _slides())
    r = consulting.evaluate(work)
    assert [h["rule"] for h in r["human"]] == HUMAN
    assert set(r["human"][0]) == {"rule", "name", "question", "level"}
    assert [(d["status"], d["by"]) for d in r["deck"] if d["rule"] in HUMAN] == [("manual", "人")] * 3


def test_evaluate_既存の_status_は変わらない(home, tmp_path):
    head = "三つの拠点の回線構成と運用体制を一覧にして示した資料のまとめページ"
    work = _work(tmp_path / "w", _deck("- 論点: ①\n", head=head), None, _slides())
    st = {x["rule"]: x["status"] for x in consulting.evaluate(work)["pages"]["02"]["deck_rules"]}
    assert (st["R13"], st["R14"], st["R15"]) == ("ng", "ok", "ok")


# --- AI 判定の記録 ---


def _import(capsys, tmp_path, work, reviews):
    f = tmp_path / "res.json"
    f.write_text(json.dumps({"reviews": reviews}, ensure_ascii=False), encoding="utf-8")
    return _run(capsys, "rule-review-import", str(work), "--file", str(f))


def _w(tmp_path):
    return _work(tmp_path / "out" / ".pptx-maker-source" / "deck", _deck("- 論点: ①\n"), None, _slides())


def _rv(rule, page, status, message=""):
    return {"rule": rule, "page": page, "status": status, "message": message}


def test_AI_は判定がなければ_pending_で_判定済みは反映される(home, tmp_path, capsys):
    work = _w(tmp_path)
    r = consulting.evaluate(work)
    pend = [d for d in r["deck"] if d["rule"] == "R03"]
    assert [(d["status"], d["by"]) for d in pend] == [("pending", "AI")]
    assert "rule-review-import" in pend[0]["message"]
    assert "R19" in {x["rule"] for x in r["pages"]["02"]["deck_rules"] if x["status"] == "pending"}
    reviews = [
        _rv("R03", "deck", "ng", "05 のヘッドが前と続かない"),
        _rv("R19", "02", "warn", "視線が右上に向く"),
        _rv("R02", "deck", "ng", "冒頭が SCQA でない"),
    ]
    code, out, _ = _import(capsys, tmp_path, work, reviews)
    assert code == 0, out
    r = consulting.evaluate(work)
    d = {x["rule"]: x for x in r["deck"] if x["rule"] in {"R03", "R02", "R01"}}
    assert (d["R03"]["status"], d["R03"]["by"], d["R03"]["message"]) == ("ng", "AI", "05 のヘッドが前と続かない")
    assert d["R02"]["status"] == "warn"  # 推奨のルールの ng は warn に下げる
    assert d["R01"]["status"] == "pending"
    p = {x["rule"]: x for x in r["pages"]["02"]["deck_rules"]}
    assert (p["R19"]["status"], p["R19"]["by"]) == ("warn", "AI")
    assert p["R21"]["status"] == "pending"


def test_rule_review_import_は同じ_rule_page_を上書きし_ほかを残す(home, tmp_path, capsys):
    work = _w(tmp_path)
    _import(capsys, tmp_path, work, [_rv("R03", "deck", "ok"), _rv("R19", "02", "ok")])
    _import(capsys, tmp_path, work, [_rv("R03", "deck", "warn", "新")])
    _, out, _ = _run(capsys, "rule-review-list", str(work))
    got = {(x["rule"], x["page"]): x for x in json.loads(out)["reviews"]}
    assert got[("R03", "deck")]["status"] == "warn"
    assert ("R19", "02") in got


@pytest.mark.parametrize(
    "bad",
    [
        _rv("R13", "deck", "ok"),  # 機械のルール
        _rv("R99", "deck", "ok"),
        _rv("R03", "77", "ok"),  # 存在しないページ
        _rv("R03", "deck", "良い"),
        {"rule": "R03", "page": "deck", "status": "warn"},  # 理由なし
    ],
)
def test_rule_review_import_の検証エラーは何も書かない(home, tmp_path, capsys, bad):
    work = _w(tmp_path)
    code, _, err = _import(capsys, tmp_path, work, [_rv("R03", "deck", "ok"), bad])
    assert code == 2
    assert err.startswith("エラー: ")
    assert not (work / "rule-review.json").exists()


def test_rule_review_clear_は_rule_page_で絞れる(home, tmp_path, capsys):
    work = _w(tmp_path)
    _import(capsys, tmp_path, work, [_rv("R03", "deck", "ok"), _rv("R19", "02", "ok"), _rv("R21", "02", "ok")])
    assert _run(capsys, "rule-review-clear", str(work), "--rule", "R19")[0] == 0
    assert _run(capsys, "rule-review-clear", str(work), "--page", "deck")[0] == 0
    _, out, _ = _run(capsys, "rule-review-list", str(work))
    assert [x["rule"] for x in json.loads(out)["reviews"]] == ["R21"]
    _run(capsys, "rule-review-clear", str(work))
    _, out, _ = _run(capsys, "rule-review-list", str(work))
    assert json.loads(out)["reviews"] == []


def test_rule_review_は_AI_のカスタムルールも受け付ける(home, tmp_path, capsys):
    _apply(capsys, tmp_path, [{"op": "add", "name": "独自", "kind": "AI", "rubric": "ok: a\nng: b"}])
    work = _w(tmp_path)
    assert _import(capsys, tmp_path, work, [_rv("C01", "deck", "ok")])[0] == 0
    r = consulting.evaluate(work)
    assert [(d["status"], d["by"]) for d in r["deck"] if d["rule"] == "C01"] == [("ok", "AI")]
