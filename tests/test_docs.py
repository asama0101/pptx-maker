"""文書（SKILL.md・references・README・plugin.json・requirements.txt）の整合を検査する。"""

# ruff: noqa: S101  # pytest の assert
import json
import re

import pytest

from tests._paths import PKG, REPO

SKILL_NAMES = ("create", "doctor", "template", "rules")
SKILL_FILES = sorted((PKG / "skills").rglob("SKILL.md"))
REFERENCE_FILES = sorted((PKG / "references").glob("*.md"))
DOC_FILES = SKILL_FILES + REFERENCE_FILES  # run.py の呼び出し・コマンド名を検査する文書
ALL_MD = sorted(PKG.rglob("*.md"))
REQ_LINES = [x.strip() for x in (PKG / "requirements.txt").read_text(encoding="utf-8").splitlines() if x.strip()]


def read(p):
    return p.read_text(encoding="utf-8")


def rel(p):
    return p.relative_to(PKG).as_posix()


def skill_text(name):
    return read(PKG / "skills" / name / "SKILL.md")


def test_スキルが揃っている():
    assert sorted(f.parent.name for f in SKILL_FILES) == sorted(SKILL_NAMES)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_スキルの_frontmatter_はスキル名と一致する(name):
    text = skill_text(name)
    m = re.match(
        r"^---\nname: (.+)\ndescription: (.+)\n(?:compatibility: .+\n)?(?:disable-model-invocation: true\n)?"
        r"(?:allowed-tools: .+\n)?---\n",
        text,
    )
    assert m, f"{name}: frontmatter が読めない"
    assert m.group(1).strip() == name


_RUN_PY = 'Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" '
# スキルごとに許す run.py のサブコマンド。広い許可（run.py *）は書かない。`setup --yes` は承認が要るので許可に入れない。
_SUBCOMMANDS = {
    "create": [
        "doctor",
        "template-list",
        "init *",
        "pptx-extract *",
        "lint-script *",
        "review-page *",
        "rule list *",
        "rule-review-import *",
        "rule-review-list *",
        "rule-review-clear *",
        "choices-import *",
        "choices-resolve *",
        "finalize *",
        "build *",
        "clean *",
    ],
    "doctor": ["doctor"],
    "template": [
        "template-list",
        "template-import *",
    ],  # template-remove は元に戻せない削除なので、事前承認に入れない（B3）
    # 書き込む `rule apply` は事前承認に入れない。事前承認は `--dry-run`（何も書かない）だけ（B3）
    "rules": ["rule list *", "rule apply --file * --dry-run"],
}


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_allowed_tools_は_サブコマンドごとの_run_py_だけに絞る(name):
    """`run.py *` のような広い許可は書かない。案の選択はローカルのページなので、Artifact 系のツールは許さない。"""
    head = skill_text(name).split("\n---\n", 1)[0]
    m = re.search(r"^allowed-tools: '(.+)'$", head, re.M)
    assert m, f"{name}: allowed-tools がない"
    want = [f"{_RUN_PY}{sub})" for sub in _SUBCOMMANDS[name]]
    assert re.findall(r"Bash\([^)]*\)|[A-Za-z]+\([^)]*\)|[A-Za-z]+", m.group(1)) == want


@pytest.mark.parametrize("key", ["name", "version", "description", "license", "repository", "keywords"])
def test_plugin_json_に推奨項目がある(key):
    m = json.loads(read(PKG / ".claude-plugin" / "plugin.json"))
    assert m.get(key), key


def test_plugin_json_の_author_に名前がある():
    m = json.loads(read(PKG / ".claude-plugin" / "plugin.json"))
    assert m["author"]["name"]


@pytest.mark.parametrize("f", SKILL_FILES, ids=lambda f: f.parent.name)
def test_スキルにパスの直書きがなく_プラグインルート変数を使う(f):
    t = read(f)
    assert "C:/Users" not in t
    assert "${CLAUDE_SKILL_DIR}" not in t
    assert "${CLAUDE_PLUGIN_ROOT}" in t


@pytest.mark.parametrize("f", [REPO / "README.md", *ALL_MD], ids=lambda f: f.name if f.name == "README.md" else rel(f))
def test_libreoffice_は依存として書かず_使わないと書く(f):
    for line in read(f).splitlines():
        if re.search(r"LibreOffice|soffice", line):
            assert re.search(r"使わ|使用しな|不要|廃止", line), f"{f}: {line}"


@pytest.mark.parametrize("f", ALL_MD, ids=rel)
def test_参照文書に旧い変数や_pngs_がない(f):
    t = read(f)
    assert "${CLAUDE_SKILL_DIR}" not in t
    assert "pngs" not in t


@pytest.mark.parametrize("f", SKILL_FILES, ids=lambda f: f.parent.name)
def test_スキルのパスはプラグインルート基準で実在する(f):
    """相対リンク（references/…）は使わない。${CLAUDE_PLUGIN_ROOT}/ の後ろは実在する。"""
    t = read(f)
    assert not re.search(r"\]\((references|assets)/", t), "相対リンク"
    assert not re.search(r"`(references|assets)/[A-Za-z0-9_]", t), "地の文の相対パス"
    missing = []
    for m in re.finditer(r"\$\{CLAUDE_PLUGIN_ROOT\}/((?:run\.py|references/|assets/)[A-Za-z0-9_./-]*)", t):
        r = m.group(1)
        if "<" not in r and not (PKG / r.rstrip("/")).exists():
            missing.append(r)
    assert missing == []


def _known_commands():
    cli_src = read(PKG / "pptx_maker" / "cli.py")
    return set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', cli_src)) | {"setup"}  # setup は run.py が直接処理する


@pytest.mark.parametrize("f", DOC_FILES, ids=rel)
def test_文書に書かれたコマンドは_cli_に実在する(f):
    """`run.py" <コマンド>` と書かれたコマンド名は、cli.py の add_parser にある。"""
    known = _known_commands()
    used = re.findall(r'run\.py"(?: --data "\$\{CLAUDE_PLUGIN_DATA\}")? ([a-z][a-z-]*)', read(f))
    assert [c for c in used if c not in known] == []


# v2 で削除したコマンド（`history`・`draft` は普通の語と紛れるので、上の run.py の形の検査に任せる）
_REMOVED_V2 = (
    "variants",
    "apply-edits",
    "review-final",
    "start-page",
    "intake",
    "set-color",
    "set-font-size",
    "output-format",
    "reopen",
    "review-plan",
    "export-html",
    "review-picture",
    "picture-status",
    "template-map",
)


@pytest.mark.parametrize("f", DOC_FILES, ids=rel)
def test_文書に削除したコマンドの名前が残っていない(f):
    t = read(f)
    assert [c for c in _REMOVED_V2 if re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", t)] == []


@pytest.mark.parametrize(
    "name",
    ["review-page", "finalize", "build"],
)
def test_主要コマンドが_cli_に登録されている(name):
    assert name in _known_commands()


@pytest.mark.parametrize("f", DOC_FILES, ids=rel)
def test_run_py_の呼び出しはすべて_data_を付ける(f):
    """Bash の環境変数には入らないので、本文の ${...} で渡す。
    frontmatter の allowed-tools（許可の書式）は呼び出しではない。"""
    t = read(f).split("\n---\n", 1)[-1]
    n_all = len(re.findall(r'run\.py"', t))
    n_ok = len(re.findall(r'run\.py" --data "\$\{CLAUDE_PLUGIN_DATA\}"', t))
    assert n_all == n_ok, f"{f.name}: --data のない run.py の呼び出し"


def test_主要コマンドは_run_py_の形で文書に書かれている():
    used = set()
    for f in DOC_FILES:
        used |= set(re.findall(r'run\.py" --data "\$\{CLAUDE_PLUGIN_DATA\}" ([a-z][a-z-]*)', read(f)))
    want = {"doctor", "setup", "init", "template-list", "lint-script", "review-page", "finalize", "build", "clean"}
    assert want <= used, want - used


@pytest.mark.parametrize("f", DOC_FILES, ids=rel)
def test_システムの_python_に入れる経路が書かれていない(f):
    """v2 は専用の仮想環境だけ。システムの Python への導入（`setup --system`）とその判定を書かない。"""
    words = ("--system", "python.kind")
    t = read(f)
    assert [w for w in words if w in t] == []


def test_requirements_txt_に依存が書かれている():
    assert REQ_LINES


@pytest.mark.parametrize("line", REQ_LINES, ids=lambda s: s.split("==")[0])
def test_requirements_は_固定の版で書かれている(line):
    assert re.match(r"^[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9_.]*$", line)


@pytest.mark.parametrize(
    "word",
    ["pp-picture", "NN-R1.html", "review-page", "コメント", "PowerPoint で直せない", "xx"],
)
def test_create_に絵を描いて見せてコメントで直す手順の語が書いてある(word):
    assert word in skill_text("create")


@pytest.mark.parametrize("word", ["NW 構成図", "トラフィックフロー", "障害動作", "自己紹介", "marker", "viewBox"])
def test_picture_craft_に絵の作法の語が書いてある(word):
    assert word in read(PKG / "references" / "picture-craft.md")


def test_create_は_picture_craft_を指し_readme_は図の依頼に触れる():
    assert "picture-craft.md" in skill_text("create")
    assert "図にして" in read(REPO / "README.md")


def test_create_は_init_から_build_の順に案内する():
    t = skill_text("create").split("\n---\n", 1)[-1]  # frontmatter の allowed-tools は数えない
    words = ('init "', "input.md", "lint-script", "review-page", "choices-import", 'finalize "', 'build "')
    pos = [t.find(w) for w in words]
    assert all(p >= 0 for p in pos), pos
    assert pos == sorted(pos)


@pytest.mark.parametrize(
    "word", ["review-page", "choices-import", "choices-resolve", "finalize", "--choices", "Claude に渡す"]
)
def test_create_に選択ページからの受け取りが書いてある(word):
    assert word in skill_text("create")


def test_create_と_readme_と_review_flow_と_development_に_artifact_の記述がない():
    for f in (
        PKG / "skills" / "create" / "SKILL.md",
        REPO / "README.md",
        REPO / "docs" / "development.md",
        PKG / "references" / "review-flow.md",
    ):
        t = read(f)
        for w in ("Artifact", "ArtifactData", "ArtifactComments", "capabilities", "readable by only you"):
            assert w not in t, f"{f.name}: {w}"


def test_文書とコードの鉄板ルールの件数が登録簿と一致する():
    from pptx_maker import consulting

    n = len(consulting.RULES)
    last = consulting.RULES[-1]["id"]
    assert f"鉄板ルール {n} 件" in read(REPO / "README.md")
    assert f"R01〜{last}" in skill_text("rules")
    assert f"R01〜{last}" in read(PKG / "pptx_maker" / "rulebook.py")


def test_development_は_cli_のコマンドを網羅している():
    t = read(REPO / "docs" / "development.md")
    missing = [c for c in sorted(_known_commands() - {"setup"}) if c not in t]
    assert missing == []


def test_create_はコメントで直したページの印を_choices_resolve_で戻す():
    t = skill_text("create")
    assert "choices-resolve" in t
    assert "`pick` は残る" in t
    assert "`review-page` をやり直す" in t


def test_create_は貼り付けの誤りを貼り直してもらう():
    t = skill_text("create")
    assert "終了コード 2 は貼り付けの誤り" in t


@pytest.mark.parametrize("f", [REPO / "README.md", PKG / "references" / "review-flow.md"], ids=lambda f: f.name)
def test_ページを閉じる前に貼り付ける注意が書いてある(f):
    t = read(f)
    assert "Claude に渡す" in t
    assert "貼" in t
    assert "開き直" in t


def test_create_は案を書く前にデザイン方向を提示して選ばせる():
    t = skill_text("create")
    assert "デザイン方向" in t
    assert "design-directions.md" in t
    assert "AskUserQuestion" in t[t.index("デザイン方向") :]
    # frontend-design には依存しない（スキルの許可にも、手順にも書かない）
    assert "Skill(frontend-design" not in t


def test_design_directions_に使う観点と使わない観点と方向のカタログが書いてある():
    t = read(PKG / "references" / "design-directions.md")
    assert "使う観点" in t
    assert "使わない" in t
    # PPTX に出せない装飾の例を挙げている
    for word in ("グラデーション", "影", "アニメーション", "Web フォント"):
        assert word in t, word
    # 題材ごとのカタログ（稟議・承認、提案、計画、障害報告）
    for word in ("稟議", "提案", "計画", "障害報告"):
        assert word in t, word


def test_html_rules_は_design_directions_を参照し_frontend_design_を呼ばない():
    t = read(PKG / "references" / "html-rules.md")
    sec = t[t.index("## 自由設計（R）の指針") :]
    assert "design-directions.md" in sec
    assert "frontend-design" not in sec


def test_create_は_build_の終了コード4で_build_overwrite_か_out_を選ばせる():
    line = next(x for x in skill_text("create").splitlines() if "終了コード 4" in x)
    assert "build-overwrite" in line
    assert "--out" in line


def test_スキルと_README_に旧配置の_source_スラッシュ_の説明が残っていない():
    for f in [*ALL_MD, REPO / "README.md"]:
        t = read(f)
        assert "<名前>/source/" not in t, f
        assert not re.search(r"(?<![\w-])source/(slides|script|design|final)", t), f


def test_成果物の用語が統一されている():
    old = "".join(["作", "品"])
    targets = [f for ext in ("py", "md", "html", "json") for f in PKG.rglob(f"*.{ext}") if "__pycache__" not in f.parts]
    targets += [
        REPO / "CLAUDE.md",
        REPO / "README.md",
        REPO / ".claude-plugin" / "marketplace.json",
        *sorted((REPO / "docs").glob("*.md")),
        *sorted((REPO / "tests").glob("*.py")),
    ]
    offenders = [f.relative_to(REPO).as_posix() for f in targets if f.exists() and old in read(f)]
    assert not offenders, offenders


def test_部品の_html_に旧配置の_source_スラッシュ_の説明が残っていない():
    pat = r"(?<![\w-])source/(slides|script|design|final)"
    offenders = [
        f.relative_to(REPO).as_posix()
        for f in (PKG / "assets" / "components").rglob("*.html")
        if re.search(pat, read(f))
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    "f", [REPO / "README.md", *DOC_FILES], ids=lambda f: f.name if f.name == "README.md" else rel(f)
)
def test_removed_names(f):
    """デザイン自由化で廃止した `init --color`・プリセット・`NN-A.html` が文書に残っていない。"""
    t = read(f)
    assert "--color" not in t
    assert "NN-A.html" not in t
    assert not re.search(r"1 枚に 1 点|1 枚 1 点|1 スライドに 1 点", t.replace("**", ""))
    assert "自由設計｜" not in t
    assert not re.search(r"navy|`green`|`gray`", t)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_導入や書き込みを行えるスキルは自動起動させない(name):
    """B4: `setup --yes`（導入）や `rule apply`（書き込み）を手順に持つスキルは、利用者が起動したときだけ動く。"""
    text = skill_text(name)
    if "setup --yes" in text or "rule apply" in text:
        assert "disable-model-invocation: true" in text.split("\n---\n", 1)[0], name


def test_marketplace_json_の_description_は最上位にあり_plugins_に_version_がない():
    """D3: description は最上位（metadata.description は旧形式）。version は plugin.json だけに置く。"""
    m = json.loads(read(REPO / ".claude-plugin" / "marketplace.json"))
    assert m["description"]
    assert "metadata" not in m
    assert m["owner"]["name"]
    assert all(p["name"] and p["source"] and p["description"] and "version" not in p for p in m["plugins"])


def test_rules_スキルは利用者が起動したときだけ動き_description_に使う場面と代わりのスキルがある():
    text = skill_text("rules")
    head = text.split("\n---\n", 1)[0]
    assert "disable-model-invocation: true" in head
    desc = re.search(r"^description: (.+)$", head, re.M).group(1)
    for word in ("ルールを足したい", "ルールを消したい", "ルールを直したい", "無効にしたい", "一覧を見たい", "create"):
        assert word in desc, word


@pytest.mark.parametrize("word", ["AskUserQuestion", "--dry-run", "rule apply", "rule list", "reset", "disable"])
def test_rules_スキルに対話の手順の語が書いてある(word):
    assert word in skill_text("rules")


def test_rules_スキルは操作の_JSON_をプラグインの置き場に書かない():
    text = skill_text("rules")
    assert "スクラッチパッド" in text
    assert "には書かない" in text


def test_create_は_AI_判定を_review_page_の前に案内する():
    t = skill_text("create")
    ai = t.index("AI 判定（案を書いたあと")
    assert ai < t.index("## 5. 案の選択")
    for word in ("rule list --kind AI", "rule-review-import", "pending", "/pptx-maker:rules"):
        assert word in t, word
