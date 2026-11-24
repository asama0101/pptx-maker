"""動作解説ページ（page.html）を、リポジトリの実ファイルと、デモの実行結果で埋めて出力する。標準ライブラリのみ。

  python docs/plugin-walkthrough/build.py [--out <出力フォルダ>] [--shoot]

--shoot: 案の選択ページを Chromium で開き、docs/images/review-walkthrough.png を撮り直す。撮ったら SHOT_VERSION を直す。
デモは、導入済みの専用の仮想環境を借りる（見つからなければ PPTX_MAKER_DEMO_VENV で指定する）。

出力（既定は一時フォルダ）: index.html（Artifact に公開するページ）と images/（docs/images/ の画像のコピー）。
page.html の `{{…}}` を、生成のたびにリポジトリから読んだ値で埋める。値の写しを page.html に書かない。
"""

import argparse
import ast
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PLUGIN = REPO / "plugins" / "pptx-maker"

PLUGIN_NAME = "pptx-maker"


def find_venv(repo: Path) -> Path:
    """デモ用の置き場から指す専用の仮想環境（導入済みのものを借りる。新しく作らない）。"""
    cands = [
        Path(os.environ.get("PPTX_MAKER_DEMO_VENV", "")),
        Path.home() / ".claude" / "plugins" / "data" / "pptx-maker-pptx-maker" / "venv",
        repo / ".venv",
    ]
    for c in cands:
        if (c / "Scripts" / "python.exe").is_file():
            return c
    raise SystemExit("専用の仮想環境が見つかりません。PPTX_MAKER_DEMO_VENV で指定してください")


def cleanup(root: Path) -> None:
    """一時フォルダを消す。仮想環境へのジャンクションは、先にリンクだけを外す（中身は消さない）。"""
    link = root / "D" / "venv"
    if link.exists():
        subprocess.run(["cmd", "/c", "rmdir", str(link)], check=False, capture_output=True)  # noqa: S603, S607
    shutil.rmtree(root, ignore_errors=True)


class Demo:
    def __init__(self, repo: Path, root: Path, demo_src: Path):
        self.repo = repo
        self.plugin = repo / "plugins" / PLUGIN_NAME
        self.run_py = self.plugin / "run.py"
        self.root = root
        self.home = root / "D"
        self.cwd = root / "起動"
        self.work = self.cwd / "pptx-maker-source" / "demo"
        self.scratch = root / "scratch"
        self.demo_src = demo_src
        self.steps: dict[str, dict] = {}
        self.files: dict[str, str] = {}
        for d in (self.home, self.cwd, self.scratch):
            d.mkdir(parents=True, exist_ok=True)
        venv = find_venv(repo)
        link = ["cmd", "/c", "mklink", "/J", str(self.home / "venv"), str(venv)]  # noqa: S607  # ジャンクションは cmd の mklink でだけ作れる
        subprocess.run(link, check=True, capture_output=True)  # noqa: S603  # 固定の引数
        self.py = self.home / "venv" / "Scripts" / "python.exe"

    # --- 表示用の置き換え -------------------------------------------------
    def mask(self, text: str) -> str:
        tmp = Path(tempfile.gettempdir())
        pairs = [
            (str(self.work), "<元データ>"),
            (str(self.home), "<D>"),
            (str(self.cwd), "<起動フォルダ>"),
            (str(self.scratch), "<作業用>"),
            (str(self.root), "<一時フォルダ>"),
            (str(self.repo), "<リポジトリ>"),
        ]
        for a, b in pairs:
            text = text.replace(a, b).replace(a.replace("\\", "\\\\"), b)
            text = text.replace(a.replace("\\", "/"), b)
        text = text.replace(str(tmp).replace("\\", "\\\\"), "<TEMP>").replace(str(tmp), "<TEMP>")
        text = re.sub(r"(pptx-maker[\\/]+demo)-[0-9a-f]{8}", r"\1-<ハッシュ>", text)
        text = text.replace(str(Path.home()).replace("\\", "\\\\"), "<ホーム>").replace(str(Path.home()), "<ホーム>")
        return text

    # --- 実行 ---------------------------------------------------------------
    def run(self, key: str, args: list[str], *, data: bool = True, label: str | None = None, env_extra=None) -> dict:
        cmd = [sys.executable, str(self.run_py)]
        if data is True:
            cmd += ["--data", str(self.home)]
        elif isinstance(data, str):
            cmd += ["--data", data]
        cmd += args
        env = {k: v for k, v in os.environ.items() if k not in ("PPTX_MAKER_HOME", "PYTHONPATH")}
        env["PYTHONUTF8"] = "1"
        env.update(env_extra or {})
        p = subprocess.run(cmd, cwd=self.cwd, env=env, capture_output=True, text=True, encoding="utf-8")  # noqa: S603
        shown = ["python", '"${CLAUDE_PLUGIN_ROOT}/run.py"']
        if data is True:
            shown += ["--data", '"${CLAUDE_PLUGIN_DATA}"']
        elif isinstance(data, str):
            shown += ["--data", data]
        shown += [self.fmt_arg(a) for a in args]
        rec = {
            "cmd": self.mask(" ".join(shown)),
            "code": p.returncode,
            "out": self.mask(p.stdout.rstrip("\n")),
            "err": self.mask(p.stderr.rstrip("\n")),
        }
        self.steps[key] = rec
        return rec

    def fmt_arg(self, a: str) -> str:
        m = self.mask(a)
        return f'"{m}"' if (" " in m or "<" in m or "\\" in m) else m

    def venv_py(self, code: str, *args: str) -> str:
        env = {**os.environ, "PYTHONPATH": str(self.plugin), "PYTHONUTF8": "1", "PPTX_MAKER_HOME": str(self.home)}
        p = subprocess.run(  # noqa: S603
            [str(self.py), "-P", "-c", code, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=True,
        )
        return p.stdout

    def paste(self, pages: dict, *, break_check: bool = False, base: str | None = None) -> str:
        """「Claude に渡す」がコピーする JSON と同じ形の貼り付け文。承認のページには、今の断片の指紋 fr を付ける。"""
        code = (
            "import json,sys\nfrom pathlib import Path\nfrom pptx_maker import candidates, choices\n"
            "work=Path(sys.argv[1]); pages=json.loads(sys.argv[2]); c=candidates.collect(work)\n"
            "for nn,d in pages.items():\n"
            "    if d.get('status')=='approved' and 'fr' not in d: d['fr']=choices.fragment_hash(c[nn][d['pick']])\n"
            "print(json.dumps({'pptx-maker-review':1,'base':choices.stamp(work),'check':choices.checksum(pages),'pages':pages},ensure_ascii=False))\n"
        )
        text = self.venv_py(code, str(self.work), json.dumps(pages, ensure_ascii=False)).strip()
        if break_check:
            text = text.replace('"check": "', '"check": "0')
        return text

    def write_scratch(self, name: str, text: str) -> Path:
        p = self.scratch / name
        p.write_text(text, encoding="utf-8", newline="\n")
        self.files[name] = text
        return p

    # --- 全体 ---------------------------------------------------------------
    def collect(self) -> None:
        w = str(self.work)
        # 0 環境
        self.run("doctor", ["doctor"])
        self.run("no_data", ["doctor"], data=False)
        self.run("bad_data", ["doctor"], data="${CLAUDE_PLUGIN_DATA}")
        self.run("setup_noyes", ["setup"])
        # テンプレート
        self.run("tpl_list_empty", ["template-list"])
        self.write_scratch("memo.txt", "テンプレートではないファイル\n")
        self.run("tpl_import_bad", ["template-import", str(self.scratch / "memo.txt")])
        std = self.plugin / "assets" / "template" / "standard.potx"
        self.run("tpl_import", ["template-import", str(std), "--name", "社内標準"])
        self.run("tpl_import_dup", ["template-import", str(std), "--name", "社内標準"])
        self.run("tpl_list", ["template-list"])
        self.run("tpl_remove", ["template-remove", "社内標準"])
        self.run("tpl_remove_none", ["template-remove", "社内標準"])
        # 1 受け取る
        self.run("init", ["init", w, "--footer", "© 2026 Demo"])
        self.run("init_dup", ["init", w])
        self.run("init_bad_path", ["init", str(self.cwd / "demo")])
        # 2 設計図と原稿
        bad = self.scratch / "bad"
        bad.mkdir()
        (bad / "script.md").write_text((self.demo_src / "script-bad.md").read_text(encoding="utf-8"), encoding="utf-8")
        self.run("lint_bad", ["lint-script", str(bad / "script.md")])
        shutil.copyfile(self.demo_src / "script.md", self.work / "script.md")
        self.run("lint_ok", ["lint-script", str(self.work / "script.md")])
        # 3 案
        make_fragments(self.plugin, self.work / "slides")
        self.files["script.md"] = (self.work / "script.md").read_text(encoding="utf-8")
        self.files["02-R1.html"] = (self.work / "slides" / "02-R1.html").read_text(encoding="utf-8")
        # 4.1 AI 判定
        self.run("rule_list_ai", ["rule", "list", "--kind", "AI"])
        ids = [r["id"] for r in json.loads(self.steps["rule_list_ai"]["out"])]
        page_rules = {"R05", "R19", "R21", "R24", "R27", "R29", "R35"}
        reviews = []
        for i in ids:
            if i in page_rules:
                reviews.append({"rule": i, "page": "02", "status": "ok", "message": "3 組の見出しと本文が同じ形で並ぶ"})
            else:
                reviews.append({"rule": i, "page": "deck", "status": "ok", "message": "この 3 枚の範囲では問題なし"})
        bad_rv = {"reviews": [{"rule": "R99", "page": "deck", "status": "ok", "message": "存在しないルール"}]}
        f = self.write_scratch("reviews-bad.json", json.dumps(bad_rv, ensure_ascii=False, indent=2))
        self.run("rv_import_bad", ["rule-review-import", w, "--file", str(f)])
        f = self.write_scratch("reviews.json", json.dumps({"reviews": reviews}, ensure_ascii=False, indent=2))
        self.run("rv_import", ["rule-review-import", w, "--file", str(f)])
        # 5 案の選択
        self.run("review_page", ["review-page", w, "--no-open"])
        approved = {
            "01": {"pick": "R1", "status": "approved", "comment": ""},
            "03": {"pick": "R1", "status": "approved", "comment": ""},
        }
        p1 = {**approved, "02": {"pick": "R2", "status": "saved", "comment": "見出しの色を落としてください"}}
        bad_paste = self.paste({"02": {"pick": "R2", "status": "approved", "comment": "色を落としてください"}})
        f = self.write_scratch("paste-bad.txt", bad_paste)
        self.run("import_bad_state", ["choices-import", w, "--file", str(f)])
        f = self.write_scratch("paste-broken.txt", self.paste(p1, break_check=True))
        self.run("import_broken", ["choices-import", w, "--file", str(f)])
        f = self.write_scratch("paste-1.txt", self.paste(p1))
        self.run("import_1", ["choices-import", w, "--file", str(f)])
        self.run("import_1_again", ["choices-import", w, "--file", str(f)])
        self.run("finalize_stop", ["finalize", w, "--choices", w])
        self.run("resolve", ["choices-resolve", w, "02"])
        self.run("review_page_2", ["review-page", w, "--no-open"])
        keep = self.root / "keep"
        keep.mkdir()
        shutil.copyfile(self.work / "review.html", keep / "review.html")
        p2 = {"02": {"pick": "R2", "status": "approved", "comment": ""}}
        f = self.write_scratch("paste-2.txt", self.paste(p2))
        self.run("import_2", ["choices-import", w, "--file", str(f)])
        # 6 PPTX（承認し直しで、02 の AI 判定は消えている。判定し直してから統合する）
        self.run("finalize_ai", ["finalize", w, "--choices", w])
        rv2 = [r for r in reviews if r["page"] == "02"]
        f = self.write_scratch("reviews-02.json", json.dumps({"reviews": rv2}, ensure_ascii=False, indent=2))
        self.run("rv_import_2", ["rule-review-import", w, "--file", str(f)])
        self.run("finalize", ["finalize", w, "--choices", w])
        self.run("build", ["build", w])
        self.run("finalize_2", ["finalize", w, "--choices", w])
        self.run("build_dup", ["build", w])
        self.run("extract", ["pptx-extract", str(self.cwd / "demo.pptx")])
        self.run("extract_bad", ["pptx-extract", str(self.scratch / "memo.txt")])
        self.run("clean", ["clean", w])
        # rules スキル
        self.run("rule_list_all", ["rule", "list", "--all"])
        ops = [
            {
                "op": "add",
                "name": "要検討を残さない",
                "kind": "機械",
                "level": "必須",
                "scope": "slide",
                "pattern": "要検討",
                "message": "「要検討」が残っています",
            },
            {"op": "disable", "id": "R14"},
        ]
        f = self.write_scratch("ops.json", json.dumps(ops, ensure_ascii=False, indent=2))
        self.run("rule_dry", ["rule", "apply", "--file", str(f), "--dry-run"])
        bad_ops = [{"op": "remove", "id": "R13"}]
        f = self.write_scratch("ops-bad.json", json.dumps(bad_ops, ensure_ascii=False, indent=2))
        self.run("rule_dry_bad", ["rule", "apply", "--file", str(f), "--dry-run"])


# 見本の裏表紙の文言を、デモの内容に替える（置き換え前, 置き換え後）
CLOSING_SWAPS = [
    ("拠点ネットワーク標準化（投資4.2億円）", "作業時間帯（平日22時から翌5時）"),
    ("通信コスト構造改革（通信費▲1.2億円）", "承認の条件（3営業日前までに申請）"),
    ("監視・運用の自動化（復旧1.0時間）", "切戻しの基準（切替後15分以内）"),
    ("組織・プロセス改革（7→5階層）", "緊急時は事後承認（24時間以内に報告）"),
    ("9月30日　投資委員会で柱Aの案件を審議", "11月5日　運用会議で承認"),
    ("10月31日　経営会議で実行計画を確定", "11月15日　運用手順書に反映"),
    ("3月31日　四半期報告の初回（進捗と予算）", "12月1日　最初の夜間切替から適用"),
]


def make_fragments(plugin: Path, dst: Path) -> None:
    """デモの案（slides/NN-R1.html・NN-R2.html）。見本の型を写し、題と文言をデモの内容に替え、data-variant を足す。"""
    c = plugin / "assets" / "components" / "layouts"

    def variant(text: str, name: str) -> str:
        return re.sub(r'(<section class="slide")', rf' data-variant="{name}"', text, count=1)

    def write(nn: str, k: int, text: str, name: str) -> None:
        (dst / f"{nn}-R{k}.html").write_text(variant(text, name), encoding="utf-8", newline="\n")

    cover = (c / "cover.html").read_text(encoding="utf-8")
    text = (c / "text.html").read_text(encoding="utf-8")
    closing = (c / "closing.html").read_text(encoding="utf-8")
    for a, b in CLOSING_SWAPS:
        closing = closing.replace(a, b)
    cover1 = cover.replace("全社ネットワークのSD-WAN更改を承認いただきたい", "夜間の回線切替ルールの承認依頼")
    cover1 = cover1.replace("3案の比較と推奨案（B案）", "3項目のルールの承認のお願い")
    write("01", 1, cover1, "題を中央に置く標準の表紙")
    write("01", 2, cover1.replace('style="height:120px"', 'style="height:160px"'), "題を大きく取る表紙")
    write("02", 1, text, "見出しと本文を縦に3組並べる")
    numbered = (
        text.replace("作業時間帯", "① 作業時間帯")
        .replace("承認の条件", "② 承認の条件")
        .replace("切戻しの基準", "③ 切戻しの基準")
    )
    write("02", 2, numbered, "番号つきの見出しで3組並べる")
    write("03", 1, closing, "左に要点、右に次のステップ")
    write(
        "03",
        2,
        closing.replace("以上です。ご意見・ご質問をお願いします", "3項目のルールの承認をお願いします"),
        "結びの一文を承認の依頼にする",
    )


# 画像を撮ったときのプラグインの版。ページの出力時の版と違えば、ページに「撮影時の版」を出して知らせる
SHOT_VERSION = "0.2.0"
IMAGES = {"review-walkthrough.png": "案の選択ページ（review.html）の 1 スライド分"}


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def read(rel: str) -> str:
    p = REPO / rel
    if not p.is_file():
        raise SystemExit(f"page.html が参照するファイルがありません: {rel}")
    return p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def size_label(rel: str) -> str:
    p = REPO / rel
    if not p.is_file():
        raise SystemExit(f"page.html が参照するファイルがありません: {rel}")
    n = p.stat().st_size
    return f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"


def def_line(rel: str, name: str) -> int:
    """構文解析で、関数・クラスの定義の行を求める。"""
    tree = ast.parse(read(rel))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name == name:
            return node.lineno
    raise SystemExit(f"定義が見つかりません: {rel} の {name}")


def chapter(rel: str, heading: str) -> str:
    """Markdown の、見出し（先頭一致）から、同じ以上の階層の次の見出しの手前まで。"""
    lines = read(rel).split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        raise SystemExit(f"見出しが見つかりません: {rel} の {heading}")
    level = len(re.match(r"#+", lines[start]).group(0))
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"(#+) ", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start:end]).rstrip("\n")


def version() -> str:
    m = re.search(r'__version__ = "([^"]+)"', read("plugins/pptx-maker/pptx_maker/__init__.py"))
    return m.group(1)


def block(label: str, text: str, cls: str = "") -> str:
    return f'<div class="blk {cls}"><div class="blk-h">{label}</div><pre>{esc(text)}</pre></div>'


def step_block(rec: dict, long: int = 60) -> str:
    """コマンド・標準出力・標準エラー・終了コードを 1 つのブロックにする。長い出力は折りたたむ。"""
    parts = [f'<div class="cmd"><span class="lab lab-cmd">実行</span><code>{esc(rec["cmd"])}</code></div>']
    for key, label, cls in (("out", "標準出力", "lab-out"), ("err", "標準エラー", "lab-err")):
        text = rec[key]
        if not text:
            continue
        n = text.count("\n") + 1
        pre = f'<pre class="outpre">{esc(text)}</pre>'
        body = f"<details><summary>{n} 行（開く）</summary>{pre}</details>" if n > long else pre
        parts.append(f'<div class="o"><span class="lab {cls}">{label}</span>{body}</div>')
    if not rec["out"] and not rec["err"]:
        parts.append(
            '<div class="o"><span class="lab lab-out">標準出力</span><span class="none">（出力なし）</span></div>'
        )
    ok = "ok" if rec["code"] == 0 else "stop"
    parts.append(f'<div class="code {ok}">終了コード {rec["code"]}</div>')
    return f'<div class="run">{"".join(parts)}</div>'


class Ctx:
    def __init__(self, demo: Demo):
        self.demo = demo

    def sub(self, m: re.Match) -> str:
        kind, _, arg = m.group(1).partition(":")
        d = self.demo
        if kind == "ver":
            return version()
        if kind == "shotver":
            return SHOT_VERSION
        if kind == "size":
            return size_label(arg)
        if kind == "count":
            return str(len(list(REPO.glob(arg))))
        if kind == "ln":
            rel, _, name = arg.rpartition(":")
            return f"{Path(rel).name} L{def_line(rel, name)}"
        if kind == "file":
            return f'<pre class="file">{esc(read(arg))}</pre>'
        if kind == "chap":
            rel, _, heading = arg.partition("|")
            return f'<pre class="file">{esc(chapter(rel, heading))}</pre>'
        if kind == "out":
            return step_block(d.steps[arg])
        if kind == "outs":  # 長い標準出力を折りたたまない（短い出力）
            return step_block(d.steps[arg], long=10**6)
        if kind == "code":
            return str(d.steps[arg]["code"])
        if kind == "demo":  # デモ中に作った・Claude が書いた文章
            return f'<pre class="file">{esc(d.files[arg])}</pre>'
        if kind == "demofile":  # 作業フォルダの中のファイル
            return f'<pre class="file">{esc((d.work / arg).read_text(encoding="utf-8"))}</pre>'
        raise SystemExit(f"未知の置き換え: {{{{{m.group(1)}}}}}")


def render(template: str, demo: Demo) -> str:
    ctx = Ctx(demo)
    out = re.sub(r"\{\{([^{}]+)\}\}", ctx.sub, template)
    left = re.findall(r"\{\{[^{}]*\}\}", out)
    if left:
        raise SystemExit(f"置き換わっていない印があります: {left[:3]}")
    return out


_SHOOT = """
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1500})
    pg.goto(Path(sys.argv[1]).as_uri())
    pg.wait_for_timeout(800)
    pg.screenshot(path=sys.argv[2])
    b.close()
"""


def shoot(demo: Demo, dst: Path) -> None:
    """デモの review.html（5.1 のやり直し後の状態）を Chromium で開いて撮る。"""
    page = demo.root / "keep" / "review.html"
    subprocess.run(  # noqa: S603  # 固定の引数。Python は借りた専用の仮想環境のもの
        [str(demo.py), "-P", "-c", _SHOOT, str(page), str(dst)], check=True, env={**os.environ, "PYTHONUTF8": "1"}
    )
    print(f"撮影した: {dst}（SHOT_VERSION を {version()} に直す。画面の内容を読んで、説明と合っているか確かめる）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--shoot", action="store_true", help="案の選択ページを撮って docs/images/ の画像を撮り直す")
    args = ap.parse_args()
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="walkthrough-"))
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="pptxwalk-"))
    try:
        demo = Demo(REPO, root, HERE / "demo")
        demo.collect()
        page = render((HERE / "page.html").read_text(encoding="utf-8"), demo)
        (out / "index.html").write_text(page, encoding="utf-8", newline="\n")
        img_src = REPO / "docs" / "images"
        (out / "images").mkdir(exist_ok=True)
        for name in IMAGES:
            if (img_src / name).is_file():
                shutil.copyfile(img_src / name, out / "images" / name)
        if args.shoot:
            shoot(demo, REPO / "docs" / "images" / "review-walkthrough.png")
    finally:
        cleanup(root)
    print(out / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
