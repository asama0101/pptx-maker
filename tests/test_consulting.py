"""コンサル資料の鉄板ルール: 登録簿・原稿の検査（R06・R12・R30・R16）・案の検査（R22・R18・R31・R28）・ルール報告。"""

# ruff: noqa: S101  # pytest の assert
import json
import re
from pathlib import Path

import pytest
from pptx_maker import candidates, cli, consulting, script_lint

HEAD = "導入により月次の集計作業が半分に縮むため、来期の人員計画を見直す必要がある"
HEAD2 = "導入により集計作業が半分に縮み、残業も減るため、来期の人員計画を見直す必要がある"
VISUAL = "- 主役の図表: 表 — 集計時間の前後を並べる\n- 読み手にさせたいこと: 人員計画の見直しを承認する"
ISSUES = "- 論点:\n  - ① 現状\n  - ② 案の比較\n  - ③ 効果\n"


def _deck(slide_extra="", body="- 本文:\n  - 要点", closing_body="①現状 ②案の比較 ③効果", issues=ISSUES, head=HEAD):
    return (
        f"# 題\n{issues}\n"
        "## S01 表紙\n- layout: cover\n- ヘッドメッセージ: 表紙のメッセージです\n\n"
        f"## S02 本文\n- layout: content\n- 章名: 何が変わるか\n- ヘッドメッセージ: {head}\n{slide_extra}"
        f"{body}\n{VISUAL}\n\n"
        f"## S03 裏表紙\n- layout: closing\n- ヘッドメッセージ: ご承認ください\n- 本文: {closing_body}\n"
    )


# --- 原稿の検査（script_lint） ---


def test_論点の欄が全部そろった原稿は指摘ゼロ():
    assert script_lint.lint(_deck("- 論点: ①\n")) == []


def test_R12_本文スライドに論点の欄がないと指摘する():
    out = script_lint.lint(_deck())
    assert any(o.startswith("S02: ") and "論点" in o for o in out)


def test_R06_一覧にない番号を指摘する():
    out = script_lint.lint(_deck("- 論点: ⑤\n"))
    assert any(o.startswith("S02: ") and "⑤" in o for o in out)


def test_R06_複数の番号は連ねて書ける():
    assert script_lint.lint(_deck("- 論点: ①②\n")) == []


def test_R06_裏表紙に出ていない番号を回収漏れとして指摘する():
    out = script_lint.lint(_deck("- 論点: ①\n", closing_body="①現状 ②案の比較"))
    assert any(o.startswith("S03: ") and "③" in o for o in out)


def test_論点の一覧がない古い原稿には論点の検査を出さない():
    assert script_lint.lint(_deck(issues="")) == []


def test_R30_比較の語があって基準の語がないヘッドを指摘する():
    out = script_lint.lint(_deck("- 論点: ①\n", head="今回の案は、他よりも最も使いやすい方式だと判断できる"))
    assert any(o.startswith("S02: ") and "基準が見当たらない" in o for o in out)


@pytest.mark.parametrize(
    ("head", "extra", "body"),
    [
        ("導入後の件数は最も小さい水準に収まり、来期の計画に使える状態だ", "", "- 本文:\n  - 要点"),
        (
            "今回の案は最も使いやすい方式であり、導入の決定に値する判断だ",
            "- 判断の枠: 決めること=導入／基準=現行比\n",
            "- 本文:\n  - 要点",
        ),
        ("今回の案は最も使いやすい方式であり、導入の決定に値する判断だ", "", "- 本文:\n  - 目標を上回る"),
    ],
    ids=["ヘッドに基準語", "判断の枠に基準語", "本文に基準語"],
)
def test_R30_基準の語がどこかにあれば指摘しない(head, extra, body):
    md = _deck("- 論点: ①\n" + extra, body=body, head=head)
    assert not any("基準が見当たらない" in o for o in script_lint.lint(md))


DESIGN = "## ページごと\n### S02 本文\n- 証拠対応表:\n  | ヘッドの節 | 証明する本体の要素 |\n  |---|---|\n{rows}\n"


def _rows(n):
    return "\n".join(f"  | 節{i} | 要素{i} |" for i in range(n))


def test_R16_証拠対応表の行がヘッドの節より少ないと指摘する():
    out = script_lint.lint(_deck("- 論点: ①\n", head=HEAD2), DESIGN.format(rows=_rows(1)))
    assert any(o.startswith("S02: ") and "証拠対応表" in o for o in out)


def test_R16_行が足りていれば指摘しない():
    assert script_lint.lint(_deck("- 論点: ①\n", head=HEAD2), DESIGN.format(rows=_rows(2))) == []


def test_R16_設計図がない_対応表がないページは指摘しない():
    md = _deck("- 論点: ①\n", head=HEAD2)
    assert script_lint.lint(md, None) == []
    assert script_lint.lint(md, "### S02 本文\n- 題: x\n") == []


def test_lint_script_は同じフォルダの設計図を読む(tmp_path, capsys):
    (tmp_path / "script.md").write_text(_deck("- 論点: ①\n", head=HEAD2), encoding="utf-8")
    (tmp_path / "design.md").write_text(DESIGN.format(rows=_rows(1)), encoding="utf-8")
    assert cli.main(["lint-script", str(tmp_path / "script.md")]) == 1
    assert "S02: " in capsys.readouterr().out


# --- 案の検査（candidates） ---

NOTE = '<div class="pp-text" data-part="注釈" data-role="caption">出所: 管理表</div>'
EMPH = '<div class="pp-shape f-emph"></div>'


def _rules(html, body=True):
    return {f["rule"] for f in candidates.fragment_findings(html, body=body)}


def test_R22_強調色の要素が多すぎると指摘する():
    assert "R22" in _rules(EMPH * (candidates.EMPHASIS_MAX + 1) + NOTE)
    assert "R22" not in _rules(EMPH * candidates.EMPHASIS_MAX + NOTE)


def test_R22_style_の強調色も数える():
    many = '<div class="pp-text" style="color:var(--emphasis)">a</div>' * (candidates.EMPHASIS_MAX + 1)
    assert "R22" in _rules(many + NOTE)


def test_R18_可否が2か所にあると指摘する():
    two = '<div class="pp-text">来期の導入の可否</div><div class="pp-text">承認の可否を問う</div>'
    assert "R18" in _rules(two + NOTE)
    assert "R18" not in _rules('<div class="pp-text">導入の可否</div>' + NOTE)


def test_R31_本文スライドに注釈がないと指摘する():
    assert "R31" in _rules('<div class="pp-text">x</div>')
    assert "R31" not in _rules('<div class="pp-text">x</div>' + NOTE)
    assert "R31" not in _rules('<div class="pp-text" data-role="caption">x</div>')
    assert "R31" not in _rules('<div class="pp-text">x</div>', body=False)


def _chart(t, axis):
    spec = json.dumps({"type": t, "categories": ["a"], "series": [{"name": "s", "values": [1]}], "axis": axis})
    return f"<div class=\"pp-chart\" data-chart='{spec}'></div>" + NOTE


@pytest.mark.parametrize("t", ["bar", "barh", "stacked"])
def test_R28_棒の軸が0でない始まりだと指摘する(t):
    assert "R28" in _rules(_chart(t, {"min": 50, "max": 100}))


def test_R28_0始まり_軸指定なし_線グラフは指摘しない():
    assert "R28" not in _rules(_chart("bar", {"min": 0, "max": 100}))
    assert "R28" not in _rules(_chart("bar", {}))
    assert "R28" not in _rules(_chart("line", {"min": 50, "max": 100}))


# --- 登録簿 ---

FIXED = {
    "R06": ("必須", "script_lint"),
    "R12": ("必須", "script_lint"),
    "R30": ("必須", "script_lint"),
    "R16": ("必須", "script_lint"),
    "R22": ("推奨", "candidates"),
    "R18": ("推奨", "candidates"),
    "R31": ("推奨", "candidates"),
    "R28": ("推奨", "candidates"),
}


def test_登録簿は_R01_から_R35_まで重複なくそろう():
    assert [r["id"] for r in consulting.RULES] == [f"R{i:02d}" for i in range(1, 36)]


def test_登録簿の項目と値が正しい():
    for r in consulting.RULES:
        assert {"id", "name", "level", "kind", "where", "description"} <= set(r)
        assert r["level"] in {"必須", "推奨"}
        assert r["kind"] in {"機械", "AI", "人"}
        assert r["name"]
        assert r["description"]


def test_検査を実装する8件の区分と場所が固定どおり():
    by_id = {r["id"]: r for r in consulting.RULES}
    for rid, (level, where) in FIXED.items():
        assert (by_id[rid]["level"], by_id[rid]["where"]) == (level, where)
        assert by_id[rid]["kind"] == "機械"
    others = [r for r in consulting.RULES if r["id"] not in FIXED]
    assert len(others) == 27  # 残りは、既存の検査がある項目（文書の棚卸し）と、AI 判定・人の確認
    assert {r["where"] for r in others} <= {"script_lint", "candidates", "check", "AI", "人"}


# --- ルール報告 ---

OKH = '<div class="pp-text">x</div>' + NOTE
NGH = '<div class="pp-text">x</div>'


def _work(tmp_path, script, design=None, slides=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "script.md").write_text(script, encoding="utf-8")
    if design is not None:
        (tmp_path / "design.md").write_text(design, encoding="utf-8")
    d = tmp_path / "slides"
    d.mkdir()
    for name, html in (slides or {}).items():
        (d / name).write_text(html, encoding="utf-8")
    return tmp_path


def _slides():
    return {
        "01-R1.html": OKH,
        "01-R2.html": OKH,
        "02-R1.html": OKH,
        "02-R2.html": NGH,
        "03-R1.html": OKH,
        "03-R2.html": OKH,
    }


def test_rule_report_の形(tmp_path):
    work = _work(tmp_path, _deck("- 論点: ①\n", head=HEAD2), DESIGN.format(rows=_rows(1)), _slides())
    r = consulting.evaluate(work)
    assert set(r) == {"rules", "deck", "pages", "human"}
    assert r["rules"] == consulting.RULES
    assert {d["status"] for d in r["deck"]} >= {"ok", "manual", "pending"}
    assert all(set(d) == {"rule", "status", "message", "by"} for d in r["deck"])
    p = r["pages"]["02"]
    assert set(p) == {"deck_rules", "variants"}
    st = {x["rule"]: x["status"] for x in p["deck_rules"]}
    assert st["R16"] == "ng"
    assert st["R12"] == "ok"
    assert {x["rule"]: x["status"] for x in p["variants"]["R2"]}["R31"] == "warn"
    assert {x["rule"]: x["status"] for x in p["variants"]["R1"]}["R31"] == "ok"
    assert "01" in r["pages"]
    json.dumps(r, ensure_ascii=False)


def test_rule_report_論点の回収漏れは_deck_に出る(tmp_path):
    work = _work(tmp_path, _deck("- 論点: ①\n", closing_body="①だけ"), None, _slides())
    r = consulting.evaluate(work)
    assert [d for d in r["deck"] if d["rule"] == "R06" and d["status"] == "ng"]


def test_rule_report_古い原稿では論点の項目を出さない(tmp_path):
    work = _work(tmp_path, _deck(issues=""), None, _slides())
    r = consulting.evaluate(work)
    assert not [d for d in r["deck"] if d["rule"] == "R06"]
    assert not [x for x in r["pages"]["02"]["deck_rules"] if x["rule"] in {"R06", "R12", "R16"}]


def test_rule_report_コマンドが_JSON_を出す(tmp_path, capsys):
    work = _work(tmp_path / "out" / ".pptx-maker-source" / "deck", _deck("- 論点: ①\n"), None, _slides())
    assert cli.main(["rule-report", str(work)]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"rules", "deck", "pages", "human"}


def test_rule_report_script_md_がなければ終了コード2(tmp_path):
    assert cli.main(["rule-report", str(tmp_path)]) == 2


# --- 文書（references/consulting-rules.md）と登録簿の一致 ---

_DOC = Path(__file__).resolve().parents[1] / "plugins" / "pptx-maker" / "references" / "consulting-rules.md"


def _first(text, words):
    found = [(text.find(w), w) for w in words if w in text]
    return min(found)[1] if found else None


def _doc_rows():
    rows = {}
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(R\d\d)\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return rows


def test_文書の表と登録簿は_ID_名前_区分_種類_場所が一致する():
    """文書（人が読む）と登録簿（コードと画面が使う）が、ずれないようにする。"""
    rows = _doc_rows()
    assert sorted(rows) == [r["id"] for r in consulting.RULES]  # R01〜R35
    diffs = []
    for r in consulting.RULES:
        name, _desc, level, kind, where, _src = rows[r["id"]]
        got = (
            name,
            level,
            _first(kind, ["機械", "AI", "人"]),
            _first(where, ["script_lint", "candidates", "check", "AI", "人"]),
        )
        if got != (r["name"], r["level"], r["kind"], r["where"]):
            diffs.append((r["id"], got, (r["name"], r["level"], r["kind"], r["where"])))
    assert diffs == []


# --- 既存の検査の結果を evaluate に載せる（R10・R13・R14・R15・R17・R20・R23・R26） ---

HEAD_NO_JUDGE = "三つの拠点の回線構成と運用体制を一覧にして示した資料のまとめページ"
HEAD_LONG = HEAD2 + "、その後の運用体制も含めて全拠点で段階的に見直すことが望ましい状況にある"
HEAD_TWO = "導入により月次の集計作業が半分に縮む。来期の人員計画を見直す必要がある"


def _page_status(r, nn="02"):
    return {x["rule"]: x["status"] for x in r["pages"][nn]["deck_rules"]}


def test_evaluate_問題のないヘッドは_R13_R14_R15_が_ok(tmp_path):
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n"), None, _slides()))
    st = _page_status(r)
    assert (st["R13"], st["R14"], st["R15"]) == ("ok", "ok", "ok")
    assert {x["rule"] for x in r["pages"]["01"]["deck_rules"]} >= {"R20", "R23", "R26"}
    assert "R13" not in {x["rule"] for x in r["pages"]["01"]["deck_rules"]}  # 表紙には当たらない


def test_evaluate_判断語のないヘッドは_R13_が_ng(tmp_path):
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n", head=HEAD_NO_JUDGE), None, _slides()))
    st = _page_status(r)
    assert (st["R13"], st["R14"]) == ("ng", "ok")


def test_evaluate_長すぎるヘッドは_R14_が_ng(tmp_path):
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n", head=HEAD_LONG), None, _slides()))
    assert _page_status(r)["R14"] == "ng"


def test_evaluate_二段構えのヘッドは_R15_が_warn(tmp_path):
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n", head=HEAD_TWO), None, _slides()))
    st = _page_status(r)
    assert (st["R15"], st["R13"], st["R14"]) == ("warn", "ok", "ok")


def test_evaluate_先頭が表紙でない原稿は_R10_が_deck_で_warn(tmp_path):
    md = _deck("- 論点: ①\n").replace("## S01 表紙\n- layout: cover", "## S01 表紙\n- layout: content", 1)
    r = consulting.evaluate(_work(tmp_path, md, None, _slides()))
    assert [d["status"] for d in r["deck"] if d["rule"] == "R10"] == ["warn"]  # R10 は推奨なので ng でなく warn


def test_evaluate_表紙で始まる原稿は_R10_が_ok(tmp_path):
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n"), None, _slides()))
    assert [d["status"] for d in r["deck"] if d["rule"] == "R10"] == ["ok"]


PICT = '<div class="pp-picture" data-alt="図">x</div>' + NOTE


def test_evaluate_図表が主役でない案は_R17_が_warn(tmp_path):
    slides = _slides() | {"02-R1.html": PICT, "02-R2.html": OKH}
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n"), None, slides))
    v = r["pages"]["02"]["variants"]
    assert {x["rule"]: x["status"] for x in v["R1"]}["R17"] == "ok"
    assert {x["rule"]: x["status"] for x in v["R2"]}["R17"] == "warn"
    assert "R17" not in {x["rule"] for x in r["pages"]["01"]["variants"]["R1"]}  # 表紙
    assert "R17" not in {x["rule"] for x in r["pages"]["03"]["variants"]["R1"]}  # 裏表紙


def test_evaluate_R20_R23_R26_は_build_時の検査(tmp_path):
    r = consulting.evaluate(_work(tmp_path, _deck("- 論点: ①\n"), None, _slides()))
    assert {d["rule"]: d["status"] for d in r["deck"] if d["rule"] in {"R20", "R23", "R26"}} == {
        "R20": "build",
        "R23": "build",
        "R26": "build",
    }
    st = _page_status(r)
    assert (st["R20"], st["R23"], st["R26"]) == ("build", "build", "build")


def test_文書の採点表と質問は登録簿の_rubric_question_と一致する():
    text = _DOC.read_text(encoding="utf-8")
    missing = []
    for r in consulting.RULES:
        for line in (r.get("rubric") or r.get("question") or "").splitlines():
            if line not in text:
                missing.append((r["id"], line))
        if r["kind"] in ("AI", "人"):
            assert f"### {r['id']} {r['name']}（{r['level']}）" in text
    assert missing == []
