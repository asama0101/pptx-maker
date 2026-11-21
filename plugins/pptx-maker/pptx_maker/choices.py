"""スライド案の選択結果（選択ページがコピーした JSON）の取り込みと読み込み。

選択結果は、スライド 1 枚につき 1 ファイル `<dir>/choices/<NN>.json`（NN はスライド番号 2 桁）。
中身は `{"at": …, "comment": "…", "pick": "R3", "status": "saved" | "approved"}`。人の確認があるページだけ、
`"checks": {"R32": true, …}`（ルール ID → 確認したか）が付く（任意。なくてもよい）。
選択ページの「Claude に渡す」がコピーする JSON は
`{"pptx-maker-review": 1, "base": <choices の指紋>, "check": <pages の検査値>,
"pages": {"<NN>": {pick, status, comment[, checks]}}}`。"""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from . import paths


def load(base: Path) -> dict[str, dict]:
    """`base` は `choices/` フォルダを含むフォルダ（作業フォルダ）。
    スライド番号 → {"pick": str | None, "comment": str, "status": str}。読めないファイルは全件まとめて ValueError。"""
    d = Path(base) / "choices"
    if not d.is_dir():
        raise ValueError(f"{d} がありません（--choices には choices/ を含むフォルダを渡してください）")
    out: dict[str, dict] = {}
    errors: list[str] = []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(paths.read_text(f))
            if not isinstance(data, dict):
                raise ValueError("JSON のオブジェクトではありません")
        except ValueError as e:
            errors.append(f"{f.name}: 読めません（{e}）")
            continue
        out[f.stem] = {
            "pick": data.get("pick") or None,
            "comment": str(data.get("comment") or "").strip(),
            "status": data.get("status", ""),
        }
        if isinstance(data.get("checks"), dict) and data["checks"]:  # 人の確認（任意。古い JSON にはない）
            out[f.stem]["checks"] = data["checks"]
    if errors:
        raise ValueError("\n".join(errors))
    return out


_STATUS = ("saved", "approved")
_NN = re.compile(r"[0-9]{2}")
_MARK = '{"pptx-maker-review"'


def checksum(pages: dict) -> str:
    """`pages` の JSON（空白なし）の FNV-1a（32 bit）。選択ページの JS と同じ計算で、貼り付けの途中で内容が
    変わっていないかを確かめる。"""
    h = 0x811C9DC5
    for b in json.dumps(pages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def stamp(base: Path) -> str:
    """今の `choices/` の指紋。選択ページに埋め込み、「Claude に渡す」の JSON に `base` として入る。
    取り込みで今の指紋と合わなければ、作り直す前の古いページから渡されたものとして断る。"""
    state = json.dumps(
        [str(Path(base).resolve()), read_state(base)], sort_keys=True, ensure_ascii=False
    )  # 成果物ごとに違う
    return hashlib.sha1(state.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _parse(text: str, base: Path, valid: dict[str, list[str]] | None) -> dict[str, dict]:
    """コピーされた JSON（前後の説明や ``` は無視する）を検査して、スライド番号 → 選択の辞書にする。
    `valid`（スライド番号 → 案の名前の一覧）があれば、実在しない番号・案も断る。"""
    a = text.find(_MARK)
    try:
        data, _ = json.JSONDecoder().raw_decode(text[a:]) if a >= 0 else (None, 0)
    except ValueError:
        data = None
    pages = data.get("pages") if isinstance(data, dict) and data.get("pptx-maker-review") == 1 else None
    if not isinstance(pages, dict):
        raise ValueError("選択ページの「Claude に渡す」でコピーした JSON ではありません")
    if data.get("check") != checksum(pages):
        raise ValueError("貼り付けた内容が途中で変わっています。「Claude に渡す」を押し直して、そのまま貼ってください")
    if data.get("base") != stamp(base):
        raise ValueError(
            "古いページから渡されています。作り直したページ（review.html）を開き直し、"
            "もう一度「Claude に渡す」を押してください"
        )
    out: dict[str, dict] = {}
    errors: list[str] = []
    for nn, d in pages.items():
        if not _NN.fullmatch(nn) or not isinstance(d, dict):
            errors.append(f"{nn}: スライド番号（2 桁）と選択のオブジェクトが要ります")
            continue
        pick, comment, status = d.get("pick"), d.get("comment", ""), d.get("status")
        if status not in _STATUS or not isinstance(comment, str):
            errors.append(f"{nn}: status は saved か approved、comment は文字列にしてください")
        elif pick is not None and not isinstance(pick, str):
            errors.append(f"{nn}: pick は文字列か null にしてください")
        elif valid is not None and nn not in valid:
            errors.append(f"{nn}: このスライドはありません")
        elif valid is not None and pick is not None and pick not in valid[nn]:
            errors.append(f"{nn}: 案 {pick} はありません（候補: {', '.join(valid[nn])}）")
        elif status == "approved" and (comment.strip() or pick is None):
            errors.append(f"{nn}: 承認済みにはコメントなし・案の選択済みが要ります")
        elif "checks" in d and not (
            isinstance(d["checks"], dict) and all(isinstance(v, bool) for v in d["checks"].values())
        ):
            errors.append(f"{nn}: checks は、ルール ID から真偽（true・false）へのオブジェクトにしてください")
        else:
            out[nn] = {"pick": pick, "comment": comment.strip(), "status": status}
            if d.get("checks"):
                out[nn]["checks"] = d["checks"]
    if errors:
        raise ValueError("\n".join(errors))
    return out


_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def color_of(text: str) -> dict | None:
    """コピーされた JSON の `color`（案の選択ページで配色セットを変えたとき）。なければ None。
    `{"name", "accent", "emphasis"}`（色は #RRGGBB）。不正なら ValueError（選択を書く前に確かめる）。"""
    a = text.find(_MARK)
    try:
        data, _ = json.JSONDecoder().raw_decode(text[a:]) if a >= 0 else (None, 0)
    except ValueError:
        return None
    color = data.get("color") if isinstance(data, dict) else None
    if color is None:
        return None
    ok = isinstance(color, dict) and all(
        isinstance(color.get(k), str) and _HEX.fullmatch(color[k]) for k in ("accent", "emphasis")
    )
    if not ok:
        raise ValueError("color は、accent と emphasis を #RRGGBB で書いたオブジェクトにしてください")
    return {
        "name": str(color.get("name") or ""),
        "accent": color["accent"].upper(),
        "emphasis": color["emphasis"].upper(),
    }


def direction_of(text: str) -> str | None:
    """コピーされた JSON の `direction`（案の選択ページでデザイン方向を変えたとき。"R2" など）。なければ None。
    文字列でなければ ValueError（選択を書く前に確かめる）。"""
    a = text.find(_MARK)
    try:
        data, _ = json.JSONDecoder().raw_decode(text[a:]) if a >= 0 else (None, 0)
    except ValueError:
        return None
    direction = data.get("direction") if isinstance(data, dict) else None
    if direction is not None and not isinstance(direction, str):
        raise ValueError("direction は、R1 のような文字列にしてください")
    return direction


def _write(base: Path, nn: str, d: dict) -> None:
    f = Path(base) / "choices" / f"{nn}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    paths.write_json(f, {"at": datetime.now(UTC).isoformat(timespec="seconds"), **d})


def _commit(base: Path, parsed: dict[str, dict]) -> None:
    """全ページを `<NN>.json.new` に書き終えてから、`<NN>.json` に置き換える。
    書き込みの途中（ディスクが満杯など）で失敗したら、どのページも反映せず、一時ファイルも残さない。
    置き換えの途中（別のプロセスがファイルを掴んでいるなど）で失敗したときは、置き換え済みのページだけが反映される。"""
    d = Path(base) / "choices"
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    staged: list[Path] = []
    try:
        for nn, page in parsed.items():
            new = d / f"{nn}.json.new"
            staged.append(new)
            paths.write_json(new, {"at": now, **page})
        for new in staged:
            new.replace(new.with_suffix(""))
    except BaseException:
        for new in staged:
            new.unlink(missing_ok=True)
        raise


def import_text(
    base: Path,
    text: str,
    valid: dict[str, list[str]] | None = None,
    before_write: Callable[[], None] | None = None,
) -> list[dict]:
    """選択ページがコピーした JSON を `<base>/choices/<NN>.json` に書く（含まれないページは触らない）。
    検査が全部通ったあと、書く直前に `before_write` を呼ぶ（配色など、選択と一緒に反映したいものを先に書く。
    ここで失敗すれば、選択は書かれず、同じ JSON をそのまま貼り直せる）。
    コメントのあるページを `[{"slide": "03", "comment": "…"}]` で返す。"""
    parsed = _parse(text, base, valid)
    if before_write:
        before_write()
    _commit(base, parsed)
    return [{"slide": nn, "comment": d["comment"]} for nn, d in sorted(parsed.items()) if d["comment"]]


def resolve(base: Path, slides: list[str]) -> list[str]:
    """コメントに応えたページの印を戻す: コメントを空にし、承認済みなら未承認（saved）に戻す（pick は残す）。
    コメントのないページは、そのまま（承認を戻さない）。印を戻したページの番号を返す。"""
    current = load(base)
    missing = [nn for nn in slides if nn not in current]
    if missing:
        raise ValueError("選択結果がないスライド: " + ", ".join(missing))
    resolved = [nn for nn in slides if current[nn]["comment"]]
    for nn in resolved:
        d = current[nn]
        _write(base, nn, {"pick": d["pick"], "comment": "", "status": "saved", **_keep_checks(d)})
    return resolved


def _keep_checks(d: dict) -> dict:
    return {"checks": d["checks"]} if "checks" in d else {}


def read_state(base: Path) -> dict[str, dict]:
    """選択ページに埋め込む、今の選択結果。まだなければ空。"""
    return load(base) if (Path(base) / "choices").is_dir() else {}
