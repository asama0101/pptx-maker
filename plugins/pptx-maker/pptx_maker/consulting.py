"""コンサル資料の鉄板ルール（R01〜R35）の登録簿と、作業フォルダのルール報告。

検査の種類は 3 つ。機械（コードで判定。script_lint・candidates・check）、AI（Claude が採点表（rubric）に照らして判定し、
rule-review.json に記録する）、人（利用者が質問（question）に答えて確認する）。
区分（必須・推奨）は、読み手に誤りが伝わる・資料の骨格が崩れるものを必須にした。
利用者の追加・編集・無効化（`<home>/rules/custom.json`）は rulebook.py。evaluate は有効なルールだけを検査する。"""

import re
from html import unescape
from pathlib import Path

from . import candidates, choices, fragcheck, paths, script_lint


def _m(id_, name, level, where, description):  # 機械が判定するルール
    return {"id": id_, "name": name, "level": level, "kind": "機械", "where": where, "description": description}


def _ai(id_, name, level, description, rubric):  # AI が採点表で判定するルール
    return {
        "id": id_,
        "name": name,
        "level": level,
        "kind": "AI",
        "where": "AI",
        "description": description,
        "rubric": rubric,
    }


def _h(id_, name, level, description, question):  # 人が確認するルール
    return {
        "id": id_,
        "name": name,
        "level": level,
        "kind": "人",
        "where": "人",
        "description": description,
        "question": question,
    }


RULES = [
    _ai(
        "R01",
        "答え先行（ガバニングメッセージ）",
        "必須",
        "資料全体の結論を 1 文で先に立て、各ページはその根拠として下に付ける。",
        "ok: 冒頭のサマリか表紙のヘッドに、資料全体の結論が 1 文で立ち、各ページがその根拠になっている。\n"
        "warn: 結論はあるが 2 文以上に分かれる、または根拠にならないページがある。\n"
        "ng: 結論が冒頭になく、背景や経緯から始まっている。\n"
        "証拠: 結論の文（どのページか）と、根拠にならないページの番号。",
    ),
    _ai(
        "R02",
        "導入の型（SCQA・SCR）",
        "推奨",
        "冒頭を状況→複雑化→問い→答えで組み、読み手が答えを必要とする理由を先に作る。",
        "ok: 冒頭 1〜2 ページで、状況・複雑化（困りごと）・問い・答えが順に読める。\n"
        "warn: 要素が 1 つ欠ける、または順序が違う。\n"
        "ng: 状況・複雑化がなく、いきなり答えか詳細に入る。\n"
        "証拠: 欠けている要素の名前と、冒頭のページ番号。",
    ),
    _ai(
        "R03",
        "縦のロジック",
        "必須",
        "上位のメッセージが疑問を生み、下位が答える。ヘッドを縦に通すと「なぜ」「だから」でつながる。",
        "ok: 上位のヘッドに「なぜ」と問うと、下位のヘッドが答えている。\n"
        "warn: 一部のページで接続が弱く、間の説明が要る。\n"
        "ng: 上位の主張を下位が支えていない、またはページ同士が無関係に並ぶ。\n"
        "証拠: つながらない 2 ページの番号と、その間に足りない説明。",
    ),
    _ai(
        "R04",
        "横のロジック",
        "必須",
        "同じ階層の並びは、演繹か帰納で、粒度と切り口をそろえる。",
        "ok: 同じ階層のページが、同じ切り口・同じ粒度で、演繹か帰納として並ぶ。\n"
        "warn: 1 つだけ粒度や切り口が違う。\n"
        "ng: 切り口が混在し、並びの意味が読み取れない。\n"
        "証拠: 並びの範囲（ページ番号）と、粒度や切り口が違うページ。",
    ),
    _ai(
        "R05",
        "MECE",
        "推奨",
        "分類は漏れなく重なりなく。切り口は 1 つ。",
        "ok: 分類が漏れなく重なりなく、切り口が 1 つである。\n"
        "warn: 重なりか漏れが 1 か所ある。\n"
        "ng: 切り口が混在し、漏れも重なりもある。\n"
        "証拠: 分類のあるページ番号と、重なる・漏れる項目。",
    ),
    _m(
        "R06",
        "論点の予告と回収",
        "必須",
        "script_lint",
        "冒頭のサマリで論点を番号つきで予告し、各ページが番号で位置を示し、裏表紙で同じ番号を回収する。",
    ),
    _ai(
        "R07",
        "縦読みで筋が通る",
        "必須",
        "タイトル（ヘッド）だけを順に読んで、結論と根拠が分かる。",
        "ok: ヘッドだけを順に読んで、結論と根拠が過不足なく分かる。\n"
        "warn: 読めるが、飛ぶ箇所や言い換えの重複がある。\n"
        "ng: ヘッドだけでは結論か根拠が分からない。\n"
        "証拠: 飛ぶ箇所の前後のページ番号と、足りない一文。",
    ),
    _ai(
        "R08",
        "先にタイトル（ゴーストデッキ）",
        "必須",
        "図表より先に、ヘッドだけで骨子を作ってから中身を作る。",
        "ok: 設計図の台帳のヘッドだけで骨子ができ、原稿・案の中身がそれに沿っている。\n"
        "warn: 台帳のヘッドと原稿のヘッドが一部ずれている。\n"
        "ng: 台帳がない、または中身が台帳と無関係に作られている。\n"
        "証拠: ずれているページ番号と、台帳と原稿のヘッドの違い。",
    ),
    _ai(
        "R09",
        "エグゼクティブサマリ",
        "必須",
        "冒頭 1〜2 ページで、結論・根拠・求める決定を示す。",
        "ok: 冒頭 1〜2 ページに、結論・根拠・求める決定がそろっている。\n"
        "warn: 3 つのうち 1 つが欠ける。\n"
        "ng: サマリがない、または 2 つ以上が欠ける。\n"
        "証拠: サマリのページ番号と、欠けている要素。",
    ),
    _m("R10", "デッキの定型", "推奨", "script_lint", "表紙→サマリ→本文→提言と次のステップ→付録の順にする。"),
    _ai(
        "R11",
        "付録（バックアップ）",
        "推奨",
        "本編に載せない根拠・方法・詳細表は付録に回し、本編を絞る。",
        "ok: 本編は主張に必要な根拠だけで、方法・前提・詳細表は付録にある。\n"
        "warn: 本編に詳細表や方法の説明が混じっている。\n"
        "ng: 付録がなく、本編が詳細で膨らんでいる。\n"
        "証拠: 付録に回すとよい内容のあるページ番号と、その内容。",
    ),
    _m(
        "R12",
        "現在位置の表示",
        "必須",
        "script_lint",
        "章・論点の番号で、今どこを読んでいるかを各ページに示す（原稿の「- 論点:」の欄）。",
    ),
    _m(
        "R13",
        "アクションタイトル",
        "必須",
        "script_lint",
        "見出しは主題の名詞でなく、結論（事実＋判断）を言い切る文にする。",
    ),
    _m("R14", "見出しの長さ", "必須", "script_lint", "2 行以内（日本語では 1 行 36 字前後）。"),
    _m(
        "R15", "1 スライド 1 メッセージ", "必須", "script_lint", "1 枚に主張は 1 つ。関係の薄い情報は削るか別ページへ。"
    ),
    _m(
        "R16",
        "ヘッドと本体の対応",
        "必須",
        "script_lint",
        "ヘッドの各節を本体のどの要素が証明するかが 1 対 1 で言える。証拠対応表の行がヘッドの節に足りないと知らせる。",
    ),
    _m(
        "R17",
        "本体は視覚的な証拠",
        "推奨",
        "candidates",
        "箇条書きより、図・表・グラフを証拠にする（図・絵・表・グラフが主役でない案は review-page が警告する）。",
    ),
    _m(
        "R18",
        "次の行動・決定の明示（決定の重複）",
        "推奨",
        "candidates",
        "決定を求める文は 1 か所にそろえる。「可否」を含む要素が 1 枚に 2 つ以上あると知らせる。",
    ),
    _ai(
        "R19",
        "視線誘導（Z・F）",
        "推奨",
        "始点を左上、終点を右下に置き、主役の 1 点で視線を受ける。",
        "ok: 題（左上）から主役を経て結論（右下）へ、視線が自然に流れる。\n"
        "warn: 主役が複数あるか、結論が視線の終点にない。\n"
        "ng: 始点も終点も読み取れず、視線が散る。\n"
        "証拠: そのページ番号と、視線が止まる要素・外れる要素。",
    ),
    _m(
        "R20",
        "視覚階層",
        "推奨",
        "check",
        "大きさ・太さ・色・間隔で重要度の順位をつける。同じ階層は同じ書式（build 時の check が測る）。",
    ),
    _ai(
        "R21",
        "近接・共通領域・整列・反復",
        "推奨",
        "関係の近いものは近づけ、枠で囲み、左端・上端をそろえ、同じ役割は同じ形にする。",
        "ok: 関係の近いものが近く、端がそろい、同じ役割は同じ形である。\n"
        "warn: 一部がそろっていない、または同じ役割の形が揺れる。\n"
        "ng: 関係のないものが近接する、または配置に規則が読み取れない。\n"
        "証拠: そのページ番号と、そろっていない要素の名前。",
    ),
    _m("R22", "強調は 1 点", "推奨", "candidates", "強調色の使い所を絞る。強調色の要素が多すぎる案を知らせる。"),
    _m(
        "R23",
        "色数の制限と表記の統一",
        "必須",
        "check",
        "色は少数に絞り、同じものは同じ見た目、違うものは違う見た目にする（build 時の check が測る）。",
    ),
    _ai(
        "R24",
        "装飾を削る",
        "推奨",
        "データを運ばない線・影・立体・飾りを置かない。",
        "ok: すべての線・図形・色が、データか構造を運んでいる。\n"
        "warn: 飾りに近い要素が 1〜2 個ある。\n"
        "ng: 影・立体・飾りが多く、データより目立つ。\n"
        "証拠: そのページ番号と、削れる装飾の名前。",
    ),
    _m(
        "R25",
        "1 枚の情報量の上限",
        "推奨",
        "candidates",
        "1 枚（案）の文字量に上限を置く（上限は candidates.TEXT_MAX。超えた案を知らせる）。",
    ),
    _m("R26", "文字サイズの下限", "必須", "check", "本文・注記に下限を置く（build 時の check が測る）。"),
    _ai(
        "R27",
        "図表の選び方",
        "推奨",
        "言いたい比較の種類（構成・項目・時系列・度数分布・相関）から図を選ぶ。",
        "ok: 言いたい比較（構成・項目・時系列・分布・相関）に合う図表を選んでいる。\n"
        "warn: 読めるが、より合う図表がある。\n"
        "ng: 比較の種類と図表が合わず、主張が読み取れない。\n"
        "証拠: そのページ番号と、比較の種類・使っている図表・合う図表。",
    ),
    _m(
        "R28",
        "棒は 0 始まり",
        "推奨",
        "candidates",
        "棒グラフの軸は 0 から（線・％は例外）。data-chart の axis.min が 0 より大きい棒を知らせる。",
    ),
    _ai(
        "R29",
        "軸・単位・凡例・ラベル・同一スケール",
        "推奨",
        "単位を 1 回示す。要素に実数ラベル。並べるグラフは同じ軸。",
        "ok: 単位が 1 回示され、要素に実数ラベルがあり、並べるグラフの軸が同じである。\n"
        "warn: 単位かラベルが一部欠ける、または軸が違う。\n"
        "ng: 単位がなく、数字の意味が読み取れない。\n"
        "証拠: そのページ番号と、欠けている単位・ラベル・軸。",
    ),
    _m(
        "R30",
        "比較の基準",
        "必須",
        "script_lint",
        "数字は何と比べて大きい・小さいのかを添える。比較・水準の語があるのに基準の語がないヘッドを知らせる。",
    ),
    _m(
        "R31",
        "出所と注記",
        "推奨",
        "candidates",
        "データの出所・前提・単位を、ページの下に書く。本文スライドに注釈がない案を知らせる。",
    ),
    _h(
        "R32",
        "数値・前提の正しさ",
        "必須",
        "資料の数字と試算の前提が、事実・社内の基準と合っている。",
        "資料の数字（金額・件数・日付）と試算の前提は、事実と社内の基準に合っていますか。素材にない数字は「xx」のままではありませんか。",
    ),
    _h(
        "R33",
        "機密情報の確認",
        "必須",
        "社外秘・個人情報・取引先名などが含まれていない（含めるなら配布先に合っている）。",
        "社外秘・個人情報・取引先名などが含まれていませんか。含めるなら、配布先に見せてよい内容ですか。",
    ),
    _h(
        "R34",
        "決定事項と承認を求める相手",
        "推奨",
        "求める決定が 1 つに特定され、承認権限のある相手に向いている。",
        "求める決定は 1 つに特定されていますか。承認する権限のある相手に向けた内容ですか。",
    ),
    _ai(
        "R35",
        "読み手への適合",
        "必須",
        "主役の図表と「読み手にさせたいこと」が、設計図の読み手・前提知識・目的に合っている。",
        "ok: 主役の図表が、読み手の知らない用語や前提を飛ばさずに読め、"
        "「読み手にさせたいこと」が設計図の目的と求める決定につながっている。\n"
        "warn: 読み手が知らない用語の説明が足りない、または既知の話に紙面を使いすぎている。\n"
        "ng: 読み手の前提知識では読み取れない、または「読み手にさせたいこと」が目的・求める決定とつながらない。\n"
        "証拠: そのページ番号と、読み手の前提知識（設計図の文）に合わない用語・図表・行動の名前。",
    ),
]

_BUILTIN_IDS = {r["id"] for r in RULES}
_SCRIPT_PAGE_RULES = ("R12", "R06", "R30", "R16")  # 原稿・設計図のページ単位の検査
_FRAGMENT_RULES = ("R22", "R18", "R31", "R28", "R25")  # 断片単位の検査
_NO_BODY = {"cover", "closing", "divider"}
_BUILD_RULES = ("R20", "R23", "R26")  # build 時の check（HTML を測る）で検査する。evaluate では実行しない
_BUILD_MESSAGE = "build 時の check（chromeSpec・fontMin など）で検査します"
_WARN_ONLY = {"R15", "R17", "R20", "R22", "R30"}  # 近似で警告するルール。必須でも ng にしない
_AI_PAGE_RULES = {
    "R05",
    "R19",
    "R21",
    "R24",
    "R27",
    "R29",
    "R35",
}  # AI の判定をページごとに求めるルール。ほかは資料全体（deck）
_PENDING = "AI の判定がありません（採点表で判定して rule-review-import で記録する）"
_STALE = "断片が変わったため、判定し直してください（採点表で判定して rule-review-import で記録する）"
# script_lint.lint のメッセージを、文言の特徴（キーワード）でルールに対応づける。
#   R10: 最初のスライドが表紙でない（ファイル全体）
#   R13: ヘッドメッセージに判断語か接続語がない
#   R14: ヘッドメッセージの字数（30〜60）、題の字数（20 以内）・句読点・文の形
#   R15: ヘッドメッセージの二段構え・ダッシュ・自己言及（ヒューリスティック）
# どれにも当たらないメッセージ（連番・書式・必須欄の欠落・文型の連続など）は、ここでは扱わない。
_LINT_RULES = (
    ("最初のスライドは表紙", "R10"),
    ("判断語か接続語", "R13"),
    ("ヘッドメッセージの字数", "R14"),
    ("題の字数", "R14"),
    ("題に句読点", "R14"),
    ("題が文の形", "R14"),
    ("二段構え", "R15"),
    ("ダッシュ", "R15"),
    ("自己言及", "R15"),
)
_LINT_PAGE_RULES = ("R13", "R14", "R15")  # 本文スライドのページ単位
_SLIDE_PREFIX = re.compile(r"^(S\d{2}): ")


def effective_rules(home=None) -> list[dict]:
    """有効なルール（組み込み＋利用者の上書き＋カスタム。無効は除く）。
    home を省くと paths.home_dir()、使えなければ組み込みだけ。"""
    from . import rulebook  # rulebook が RULES を使うので、循環を避けて呼ぶときに読む

    return rulebook.effective(home)


def _lint_findings(md: str, design: str | None) -> list[dict]:
    """script_lint.lint の既存メッセージのうち、R10・R13・R14・R15 に当たるもの。{"rule", "slide", "message"}。"""
    out = []
    for msg in script_lint.lint(md, design):
        rid = next((r for kw, r in _LINT_RULES if kw in msg), None)
        if rid:
            m = _SLIDE_PREFIX.match(msg)
            out.append({"rule": rid, "slide": m.group(1) if m else None, "message": msg})
    return out


def _status(rule: dict) -> str:
    """指摘があるときの状態。必須の機械検査は ng、それ以外（推奨・近似で警告するもの）は warn。"""
    return "ng" if rule["level"] == "必須" and rule["kind"] == "機械" and rule["id"] not in _WARN_ONLY else "warn"


def _read(p: Path) -> str | None:
    return paths.read_text(p) if p.is_file() else None


def _res(rid: str, status: str, message: str = "", by: str = "機械") -> dict:
    return {"rule": rid, "status": status, "message": message, "by": by}


def _custom_hit(rule: dict, text: str) -> dict:
    """カスタム（機械）ルールを 1 つの文字列に当てた結果。一致したら warn（必須なら ng）。"""
    m = re.search(rule["pattern"], text or "")
    if not m:
        return _res(rule["id"], "ok")
    status = "ng" if rule["level"] == "必須" else "warn"
    return _res(rule["id"], status, f"{rule['message']}（「{m.group(0)[:30]}」）")


def _plain(html: str) -> str:
    return unescape(re.sub(r"<[^>]*>", "", html))


def evaluate(work, home=None, measure: bool = False) -> dict:
    """作業フォルダの script.md・design.md・slides/ を検査し、ルール報告（rules・deck・pages・human）を返す。
    有効なルールだけを出す（home の指定は effective_rules と同じ）。AI のルールは rule-review.json の判定を載せる。
    measure=True なら、案を 1 つずつ測って R20・R23・R26 を案ごとの結果にする（fragcheck。ブラウザを使う）。
    戻り値に measured（測れたか）と、測れなかったときの measure_error を足す。measure=False は従来どおり build。"""
    from . import rulebook

    work = Path(work)
    md = _read(work / "script.md")
    if md is None:
        raise ValueError(f"{work / 'script.md'} がありません")
    design = _read(work / "design.md")
    rules = effective_rules(home)
    eff = {r["id"]: r for r in rules}

    def on(rid: str) -> bool:
        return rid in eff

    def st(rid: str) -> str:
        return _status(eff[rid])

    slides = script_lint.parse(md)
    findings = script_lint.consulting_findings(md, design)
    nums = script_lint.issue_numbers(md)
    has_table = script_lint._evidence_rows(design) if design else {}  # noqa: SLF001

    lint_hits = _lint_findings(md, design)
    deck: list[dict] = []
    if nums:
        bad = [f for f in findings if f["slide"] is None and on(f["rule"])]
        deck += [_res(f["rule"], st(f["rule"]), f["message"]) for f in bad]
        if not bad and on("R06"):
            deck.append(_res("R06", "ok", f"論点 {''.join(nums)} は裏表紙で回収されています"))
    if on("R10"):
        first = [f for f in lint_hits if f["rule"] == "R10"]
        deck += [_res("R10", st("R10"), f["message"]) for f in first] or [_res("R10", "ok")]
    deck += [_res(rid, "build", _BUILD_MESSAGE) for rid in _BUILD_RULES if on(rid)]
    human = [r for r in rules if r["kind"] == "人"]
    deck += [_res(r["id"], "manual", "人の確認", "人") for r in human]

    cands = candidates.collect(work)
    measured, measure_error = {}, None
    if measure:
        failed: dict[str, str] = {}
        try:
            measured = fragcheck.check_variants(work, {nn: sorted(c) for nn, c in cands.items()}, failed)
        except Exception as e:  # noqa: BLE001  # chromium がないなど。止めずに build のまま出す
            measure_error = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
        if failed and not measure_error:
            measure_error = "測れなかった案: " + "、".join(f"{k}（{v}）" for k, v in failed.items())
    custom = [r for r in rules if r["kind"] == "機械" and r["id"] not in _BUILTIN_IDS]
    pages: dict[str, dict] = {}
    body_nns: list[str] = []
    for s in slides:
        nn = s["id"][1:]
        fields = s["fields"]
        layout = script_lint._layout(fields)  # noqa: SLF001
        body = layout in script_lint._BODY_LAYOUTS  # noqa: SLF001
        page_rules: list[dict] = []
        if body:
            body_nns.append(nn)
            applicable = {"R12": bool(nums), "R06": bool(nums), "R30": True, "R16": s["id"] in has_table}
            for rid in _SCRIPT_PAGE_RULES:
                if not applicable[rid] or not on(rid):
                    continue
                hits = [f for f in findings if f["slide"] == s["id"] and f["rule"] == rid]
                page_rules += [_res(rid, st(rid), f["message"]) for f in hits] or [_res(rid, "ok")]
            for rid in _LINT_PAGE_RULES:
                if not on(rid):
                    continue
                hits = [f for f in lint_hits if f["slide"] == s["id"] and f["rule"] == rid]
                page_rules += [_res(rid, st(rid), f["message"]) for f in hits] or [_res(rid, "ok")]
            for r in custom:
                if r["scope"] == "head":
                    page_rules.append(_custom_hit(r, script_lint._text(fields.get("ヘッドメッセージ"))))  # noqa: SLF001
                elif r["scope"] == "script":
                    page_rules.append(_custom_hit(r, script_lint._text(fields.get("本文"))))  # noqa: SLF001
        page_rules += [_res(rid, "build", _BUILD_MESSAGE) for rid in _BUILD_RULES if on(rid)]
        variants = {}
        any_measured = False
        for key, html in sorted(cands.get(nn, {}).items()):
            hits = candidates.fragment_findings(html, body=layout not in _NO_BODY)
            res = []
            for rid in _FRAGMENT_RULES:
                if not on(rid) or (rid == "R31" and layout in _NO_BODY):
                    continue
                mine = [h for h in hits if h["rule"] == rid]
                res += [_res(rid, st(rid), h["message"]) for h in mine] or [_res(rid, "ok")]
            if layout not in _NO_BODY and on("R17"):
                bad = not candidates._has_main_visual(html)  # noqa: SLF001
                res.append(
                    _res("R17", st("R17") if bad else "ok", "図・絵・表・グラフが主役になっていません" if bad else "")
                )
            res += [_custom_hit(r, _plain(html)) for r in custom if r["scope"] == "slide"]
            found = measured.get((nn, key))
            if found is not None:
                any_measured = True
                res += [
                    _res(rid, st(rid), found[rid]) if rid in found else _res(rid, "ok")
                    for rid in _BUILD_RULES
                    if on(rid)
                ]
            variants[key] = res
        if any_measured:  # 測れた案があるページは、ページ単位の「build 時」を外す（測れなかった案は、その案だけ build）
            page_rules[:] = [x for x in page_rules if x["rule"] not in _BUILD_RULES]
            for key, res in variants.items():
                if measured.get((nn, key)) is None:
                    res += [_res(rid, "build", _BUILD_MESSAGE) for rid in _BUILD_RULES if on(rid)]
        pages[nn] = {"deck_rules": page_rules, "variants": variants}

    _add_ai_results(rules, rulebook.read_reviews(work), deck, pages, body_nns, cands)
    out = {
        "rules": rules,
        "deck": deck,
        "pages": pages,
        "human": [{"rule": r["id"], "name": r["name"], "question": r["question"], "level": r["level"]} for r in human],
    }
    if measure:
        out["measured"] = any(v is not None for v in measured.values())
        if measure_error:
            out["measure_error"] = measure_error
    return out


def _add_ai_results(
    rules: list[dict],
    reviews: list[dict],
    deck: list[dict],
    pages: dict[str, dict],
    body_nns: list[str],
    cands: dict[str, dict[str, str]],
) -> None:
    """AI のルールの結果（判定済みはその内容、まだなら pending）を、deck とページの deck_rules に足す。
    記録に断片の指紋 frag があり、いまのそのページの指紋と違えば、判定し直しの pending にする。
    frag のない記録（古いもの、deck）は、今までどおり有効。"""
    now = {nn: choices.page_frag(c) for nn, c in cands.items() if c}  # ページごとに 1 回だけ計算する
    for r in (r for r in rules if r["kind"] == "AI"):
        mine = {v["page"]: v for v in reviews if v["rule"] == r["id"]}
        places = list(body_nns) if r["id"] in _AI_PAGE_RULES else ["deck"]
        places += [pg for pg in mine if pg not in places]
        for place in places:
            v = mine.get(place)
            if v is None:
                res = _res(r["id"], "pending", _PENDING, "AI")
            elif v.get("frag") is not None and v["frag"] != now.get(place):
                res = _res(r["id"], "pending", _STALE, "AI")
            else:
                status = "warn" if v["status"] == "ng" and r["level"] != "必須" else v["status"]
                res = _res(r["id"], status, v["message"], "AI")
            if place == "deck":
                deck.append(res)
            elif place in pages:
                pages[place]["deck_rules"].append(res)


def _connectives(design: str | None) -> dict[str, str]:
    """設計図の「台帳」の表から、スライド番号（S02）→「直前からの接続語」。表・列がなければ空。"""
    out: dict[str, str] = {}
    col = None
    for line in (design or "").splitlines():
        if not line.strip().startswith("|"):
            if not line.strip():
                col = None  # 表が終わった
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "直前からの接続語" in cells:
            col = cells.index("直前からの接続語")
        elif col is not None and col < len(cells) and re.fullmatch(r"S\d{2}", cells[0]):
            out[cells[0]] = cells[col]
    return out


def vertical_reading(work) -> dict:
    """縦読みの表示用データ: 本文スライドの {nn, title, head, issue, conn} と、裏表紙の本文の要点（closing）。"""
    work = Path(work)
    md = _read(work / "script.md")
    if md is None:
        raise ValueError(f"{work / 'script.md'} がありません")
    conn = _connectives(_read(work / "design.md"))
    rows, closing = [], ""
    for s in script_lint.parse(md):
        f = s["fields"]
        layout = script_lint._layout(f)  # noqa: SLF001
        if layout in script_lint._BODY_LAYOUTS:  # noqa: SLF001
            rows.append(
                {
                    "nn": s["id"][1:],
                    "title": script_lint._text(f.get("題")) or s["title"],  # noqa: SLF001
                    "head": script_lint._text(f.get("ヘッドメッセージ")),  # noqa: SLF001
                    "issue": script_lint._text(f.get("論点")),  # noqa: SLF001
                    "conn": conn.get(s["id"], ""),
                }
            )
        elif layout == "closing":
            closing = script_lint._text(f.get("本文"))  # noqa: SLF001
    return {"rows": rows, "closing": closing}


def pending_ai(work, home=None) -> list[str]:
    """AI の判定がまだのルールを「R01 全体」「R05 S03」の形で返す（有効なルールだけ。script.md がなければ空）。
    断片が変わって判定し直しになったものは、末尾に「（断片が変わった）」を付ける。"""
    if not (Path(work) / "script.md").is_file():
        return []
    res = evaluate(work, home)

    def label(x, place):
        return f"{x['rule']} {place}" + ("（断片が変わった）" if x["message"] == _STALE else "")

    out = [label(x, "全体") for x in res["deck"] if x["status"] == "pending"]
    for nn, pg in res["pages"].items():
        out += [label(x, f"S{nn}") for x in pg["deck_rules"] if x["status"] == "pending"]
    return out
