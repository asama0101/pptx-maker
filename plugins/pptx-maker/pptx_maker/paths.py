"""場所の決定。標準ライブラリのみ（run.py から venv なしで使う）。"""

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"


def read_cfg(work) -> dict:
    return json.loads((Path(work) / "template.json").read_text(encoding="utf-8"))


def read_text(path) -> str:
    """利用者が書くファイル（原稿・設計図・回答・メモなど）を読む。
    BOM 付きの UTF-8 も読み、UTF-8 でなければ ValueError にする。"""
    path = Path(path)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{path.name} は UTF-8 で保存してください（今の文字コードでは読めません）: {path}") from None


def make_tmp(directory, prefix: str, suffix: str = ".tmp") -> tuple[int, str]:
    """同じフォルダに一時ファイルを排他的に 1 回だけ作り、(fd, パス) を返す。作れなければ OSError を上げる。
    tempfile.mkstemp は、Windows で os.access が書けると答えるのに実際は書けないフォルダだと、PermissionError を
    TMP_MAX 回（Python 3.14 では約 21 億回）繰り返して止まらないので使わない。"""
    path = Path(directory) / f"{prefix}{uuid.uuid4().hex[:12]}{suffix}"
    return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600), str(path)


def write_json(target, data) -> None:
    """同じフォルダの一時ファイルに書いてから置き換える（読む側が途中の JSON を見ない。同時でも名前が重ならない）。"""
    target = Path(target)
    fd, tmp = make_tmp(target.parent, f"{target.stem}-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        Path(tmp).replace(target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_text(target, text: str) -> None:
    """同じフォルダの一時ファイルに書いてから置き換える（途中で止まっても、元のファイルは壊れない。改行は LF）。"""
    target = Path(target)
    fd, tmp = make_tmp(target.parent, f"{target.stem}-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        Path(tmp).replace(target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_cfg(work, cfg: dict) -> None:
    write_json(Path(work) / "template.json", cfg)


_FORBIDDEN_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAME = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


def filename_problem(name: str) -> str | None:
    """Windows のファイル名（拡張子なし）として使えない理由。使えるなら None。
    テンプレートの登録名（templatestore）が使う。"""
    if not name.strip():
        return "空です"
    if _FORBIDDEN_NAME.search(name):
        return '使えない文字があります（半角の < > : " / \\ |? * と制御文字）'
    if name in (".", "..") or name != name.rstrip(" ."):
        return "末尾にドットか空白は使えません（`.`・`..` も不可）"
    if _RESERVED_NAME.fullmatch(name.split(".")[0].rstrip()):
        return "Windows の予約名は使えません"
    return None


def home_dir() -> Path:
    """専用の仮想環境などの置き場。run.py が `--data`（${CLAUDE_PLUGIN_DATA}）を PPTX_MAKER_HOME に入れて渡す。"""
    home = os.environ.get("PPTX_MAKER_HOME")
    if not home:
        raise RuntimeError("専用環境の置き場が未指定です（環境変数 PPTX_MAKER_HOME か、run.py の --data で指定します）")
    return Path(home)


def venv_dir() -> Path:
    return home_dir() / "venv"


def venv_python() -> Path:
    return venv_dir() / "Scripts" / "python.exe"


def templates_dir() -> Path:
    """利用者のテンプレートの置き場。プラグインを更新しても残る。"""
    return home_dir() / "templates"


def temp_key(name: str, work=None) -> str:
    """一時フォルダの名前。work（作業フォルダ）を渡すと、絶対パスのハッシュを足し、同名の別の成果物と混ざらないようにする。"""
    if not name.strip() or name.strip() in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"一時フォルダの名前が不正です: {name!r}")  # clean が %TEMP%\pptx-maker 全体を消さないように
    if work is None:
        return name
    return f"{name}-{hashlib.sha1(str(Path(work).resolve()).encode('utf-8'), usedforsecurity=False).hexdigest()[:8]}"


def temp_dir(name: str, work=None) -> Path:
    """OS の一時フォルダ配下の作業場所（確認用 PNG など一過性のもの）。work を渡すと作業フォルダごとに分ける。"""
    d = Path(tempfile.gettempdir()) / "pptx-maker" / temp_key(name, work)
    d.mkdir(parents=True, exist_ok=True)
    return d


SOURCE_PARENT = "pptx-maker-source"


class LayoutError(ValueError):
    """成果物の置き場所の規則に合わないパス。"""


def resolve_work(arg: str | Path) -> Path:
    """コマンドの引数を、作業フォルダ（<出力先>/pptx-maker-source/<成果物名>）に解決する。
    .pptx のパスを渡すと、その隣の pptx-maker-source/<成果物名> にする。"""
    arg = Path(arg)
    is_pptx = arg.suffix.lower() == ".pptx"
    if is_pptx and (arg.parent / "source" / "template.json").is_file():
        raise LayoutError(
            f"旧配置は未対応です（<名前>/<名前>.pptx と <名前>/source の形は使えません。作り直してください）: {arg}"
        )
    work = arg.parent.resolve() / SOURCE_PARENT / arg.stem if is_pptx else arg.resolve()
    if not work.name:
        raise LayoutError(f"成果物の名前が空です（ドライブ直下は指定できません）: {arg}")
    if work.parent.name != SOURCE_PARENT:
        if work.name == "source" or (work / "source" / "template.json").is_file():
            raise LayoutError(f"旧配置は未対応です（<名前>/source の形は使えません。作り直してください）: {arg}")
        raise LayoutError(
            f"成果物の元データは <出力先>/{SOURCE_PARENT}/<成果物名> に置きます。"
            f"このパスは {SOURCE_PARENT} の直下ではありません: {arg}"
        )
    return work


def deck_dir(work: Path) -> Path:
    """出力先（PPTX・HTML を置く、pptx-maker-source の親）。"""
    return Path(work).parent.parent


def deck_name(work: Path) -> str:
    return Path(work).name


# 遷移（meta refresh など）は CSP で防げない。candidates.unsafe_parts と測定側（measure.py）の通信遮断が頼り。
# 断片は素材を読んだ Claude が書くので、検査をすり抜けた script・外部 URL があっても外へ出さないための CSP。
# `file:` は作業フォルダの theme.css・base.css・画像など、同じ PC の中の読み込み用（作業フォルダだけには絞れない。
# 外へは出ないが、断片が書く参照は candidates.unsafe_parts が相対パスと data:image/ だけに絞る）。
# review.html は何も外から読まない（画像も data URI）ので、インラインの JS・CSS だけを許す。
CSP_REVIEW = (
    "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; connect-src 'none'; "
    "img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "script-src-attr 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-src 'none'\">"
)
# final.html と、測定・検査用に包む html（作業フォルダのファイルを読む。インラインの script は許さない）
CSP_FILE = (
    "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; connect-src 'none'; "
    "img-src data: file:; font-src data: file:; style-src 'unsafe-inline' file:; script-src file:; "
    "object-src 'none'; frame-src 'none'; form-action 'none'\">"
)
