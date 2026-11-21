"""鉄板ルールの管理（組み込みの上書き・無効化・カスタム）と、AI 判定の記録。

保存先は `<home_dir>/rules/custom.json`（全資料共通）:
  {"custom": [{id, name, level, kind, where, description, rubric?, question?, pattern?, scope?, message?, enabled?}],
   "overrides": {"R13": {"name"?, "description"?, "level"?, "kind"?, "rubric"?, "question"?, "enabled"?: false}}}
組み込み（R01〜R35）は削除できない（enabled: false で無効にする）。AI 判定の記録は作業フォルダの rule-review.json。"""

import json
import re
from pathlib import Path

from . import consulting, paths, script_lint

KINDS = ("機械", "AI", "人")
LEVELS = ("必須", "推奨")
SCOPES = ("head", "slide", "script")
STATUSES = ("ok", "warn", "ng")
_EDIT_KEYS = ("name", "description", "level", "kind", "rubric", "question", "pattern", "scope", "message")
_BUILTIN_EDIT_KEYS = ("name", "description", "level", "kind", "rubric", "question")
_CUSTOM_KEYS = (
    "id",
    "name",
    "level",
    "kind",
    "where",
    "description",
    "rubric",
    "question",
    "pattern",
    "scope",
    "message",
)
_BUILTIN = {r["id"]: r for r in consulting.RULES}
REVIEW_FILE = "rule-review.json"


def _file(home) -> Path:
    return Path(home) / "rules" / "custom.json"


def load(home) -> dict:
    f = _file(home)
    if not f.is_file():
        return {"custom": [], "overrides": {}}
    try:
        data = json.loads(paths.read_text(f))
    except json.JSONDecodeError as e:
        raise ValueError(f"{f} が壊れています（JSON として読めません）: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("custom", []), list):
        raise ValueError(f"{f} の形が違います（custom は配列、overrides はオブジェクト）")
    ov = data.get("overrides", {})
    if not isinstance(ov, dict):
        raise ValueError(f"{f} の形が違います（custom は配列、overrides はオブジェクト）")
    return {"custom": data.get("custom", []), "overrides": ov}


def save(home, data: dict) -> None:
    f = _file(home)
    f.parent.mkdir(parents=True, exist_ok=True)
    paths.write_json(f, data)


def _where(kind: str) -> str:
    return {"AI": "AI", "人": "人"}.get(kind, "custom")


def _builtin_view(rid: str, ov: dict) -> dict:
    r = dict(_BUILTIN[rid])
    o = ov.get(rid, {})
    r.update({k: v for k, v in o.items() if k != "enabled"})
    if "kind" in o:
        r["where"] = _where(o["kind"])
    if r["kind"] != "AI":
        r.pop("rubric", None)
    if r["kind"] != "人":
        r.pop("question", None)
    return r


def _all(data: dict) -> list[dict]:
    """組み込み＋カスタムの全ルール（無効も）。各ルールに enabled・source を付ける。"""
    ov = data["overrides"]
    out = []
    for rid in _BUILTIN:
        r = _builtin_view(rid, ov)
        r["enabled"] = ov.get(rid, {}).get("enabled", True) is not False
        r["source"] = "上書きあり" if rid in ov else "組み込み"
        out.append(r)
    for c in data["custom"]:
        r = {k: c[k] for k in _CUSTOM_KEYS if k in c}
        r["enabled"] = c.get("enabled", True) is not False
        r["source"] = "カスタム"
        out.append(r)
    return out


def _home(home) -> Path | None:
    if home is not None:
        return Path(home)
    try:
        return paths.home_dir()
    except RuntimeError:
        return None


def effective(home=None) -> list[dict]:
    """有効なルール（組み込み＋上書き＋カスタム。無効は除く）。home がなく使えなければ組み込みだけ。"""
    h = _home(home)
    if h is None:
        return [dict(r) for r in consulting.RULES]
    return [{k: v for k, v in r.items() if k not in ("enabled", "source")} for r in _all(load(h)) if r["enabled"]]


def listing(home, kind: str | None = None, include_all: bool = False) -> list[dict]:
    rules = _all(load(home))
    return [r for r in rules if (include_all or r["enabled"]) and (kind is None or r["kind"] == kind)]


# --- 操作（rule apply） ---


def _need(r: dict, key: str, label: str | None = None) -> str:
    v = r.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{label or key} が必要です")
    return v


def _check_fields(r: dict, *, builtin: bool = False) -> None:
    """name・level・kind と、種類ごとの必須項目を確かめる。
    組み込みの機械ルールは検査の実装があるので、正規表現の項目は見ない。"""
    _need(r, "name")
    if r.get("level") not in LEVELS:
        raise ValueError(f"level は {'・'.join(LEVELS)} のどれかです（{r.get('level')!r}）")
    if r.get("kind") not in KINDS:
        raise ValueError(f"kind は {'・'.join(KINDS)} のどれかです（{r.get('kind')!r}）")
    if r["kind"] == "AI":
        _need(r, "rubric", "rubric（採点表）")
    elif r["kind"] == "人":
        _need(r, "question", "question（確認の質問）")
    elif not builtin:
        if r.get("scope") not in SCOPES:
            raise ValueError(f"scope は {'・'.join(SCOPES)} のどれかです（{r.get('scope')!r}）")
        pattern = _need(r, "pattern", "pattern（正規表現）")
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"pattern が正規表現として不正です: {e}") from e
        _need(r, "message", "message（指摘の文）")


def _normalize_custom(r: dict) -> dict:
    """カスタムルールの項目を、種類に必要なものだけにそろえる。"""
    r = dict(r)
    r["where"] = _where(r.get("kind", ""))
    r["description"] = r.get("description") or r.get("name", "")
    keep = {"id", "name", "level", "kind", "where", "description"}
    keep |= {"AI": {"rubric"}, "人": {"question"}}.get(r.get("kind", ""), {"pattern", "scope", "message"})
    out = {k: r[k] for k in _CUSTOM_KEYS if k in r and k in keep}
    if r.get("enabled") is False:
        out["enabled"] = False
    return out


def _find_custom(data: dict, rid: str) -> dict | None:
    return next((c for c in data["custom"] if c.get("id") == rid), None)


def _view(data: dict, rid: str) -> dict | None:
    return next((r for r in _all(data) if r["id"] == rid), None)


def _next_id(data: dict) -> str:
    nums = [int(m.group(1)) for c in data["custom"] if (m := re.fullmatch(r"C(\d+)", str(c.get("id", ""))))]
    return f"C{max(nums, default=0) + 1:02d}"


def _op_add(data: dict, op: dict) -> str:
    unknown = set(op) - {"op", *_EDIT_KEYS}
    if unknown:
        raise ValueError(f"add に使えない項目です: {'・'.join(sorted(unknown))}")
    r = {"level": "推奨", **{k: v for k, v in op.items() if k != "op"}}
    _check_fields(r)
    r["id"] = _next_id(data)
    data["custom"].append(_normalize_custom(r))
    return r["id"]


def _edit_builtin(data: dict, rid: str, changes: dict) -> None:
    base = _BUILTIN[rid]
    bad = set(changes) - set(_BUILTIN_EDIT_KEYS)
    if bad:
        raise ValueError(f"{rid} は組み込みのルールなので、{'・'.join(sorted(bad))} は変えられません")
    if "kind" in changes and changes["kind"] != base["kind"]:
        if base["kind"] == "機械":
            raise ValueError(
                f"{rid} は検査の実装がある機械ルールなので、kind は変えられません（変えても実装は変わりません）"
            )
        if changes["kind"] == "機械":
            raise ValueError(f"{rid} を機械にはできません（検査の実装がありません。カスタムルールを add してください）")
    ov = data["overrides"]
    new = {**ov.get(rid, {}), **changes}
    ov[rid] = {k: v for k, v in new.items() if k == "enabled" or v != base.get(k)}
    _check_fields(_builtin_view(rid, ov), builtin=True)
    if not ov[rid]:
        del ov[rid]


def _op_edit(data: dict, rid: str, op: dict) -> None:
    changes = op.get("set")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("set（変える項目のオブジェクト）が必要です")
    bad = set(changes) - set(_EDIT_KEYS)
    if bad:
        raise ValueError(f"変えられない項目です: {'・'.join(sorted(bad))}")
    custom = _find_custom(data, rid)
    if custom is None:
        _edit_builtin(data, rid, changes)
        return
    merged = {**custom, **changes}
    _check_fields(merged)
    data["custom"][data["custom"].index(custom)] = _normalize_custom(merged)


def _op_toggle(data: dict, rid: str, enabled: bool) -> None:
    custom = _find_custom(data, rid)
    if custom is not None:
        custom.pop("enabled", None)
        if not enabled:
            custom["enabled"] = False
        return
    ov = data["overrides"].setdefault(rid, {})
    ov.pop("enabled", None)
    if not enabled:
        ov["enabled"] = False
    if not ov:
        del data["overrides"][rid]


def _op_remove(data: dict, rid: str) -> None:
    custom = _find_custom(data, rid)
    if custom is None:
        raise ValueError(f"{rid} は組み込みのルールなので削除できません（無効にするには disable を使います）")
    data["custom"].remove(custom)


def _op_reset(data: dict, rid: str) -> None:
    if _find_custom(data, rid) is not None:
        raise ValueError(f"{rid} はカスタムルールです（既定がないので reset できません。edit か remove を使います）")
    data["overrides"].pop(rid, None)


def apply(home, ops, *, dry_run: bool = False) -> dict:
    """操作の配列を、全部検証してから書く（1 件でもエラーなら何も書かない）。
    戻り値: {"results": [{op, id, before, after}], "written": bool}。エラーは「<操作の番号>: <理由>」の ValueError。"""
    if not isinstance(ops, list):
        raise ValueError('操作は配列で渡してください（[{"op": ...}, ...]）')
    data = load(home)
    results = []
    for n, op in enumerate(ops, 1):
        try:
            results.append(_apply_one(data, op))
        except ValueError as e:
            raise ValueError(f"{n}: {e}") from e
    if not dry_run:
        save(home, data)
    return {"results": results, "written": not dry_run}


def _apply_one(data: dict, op) -> dict:
    if not isinstance(op, dict):
        raise ValueError("操作はオブジェクトで書きます")
    name = op.get("op")
    if name not in ("add", "edit", "remove", "enable", "disable", "reset"):
        raise ValueError(f"op は add・edit・remove・enable・disable・reset のどれかです（{name!r}）")
    if name == "add":
        rid = _op_add(data, op)
        return {"op": name, "id": rid, "before": None, "after": _view(data, rid)}
    rid = op.get("id")
    before = _view(data, rid) if isinstance(rid, str) else None
    if before is None:
        raise ValueError(f"{rid} は存在しません")
    if name == "edit":
        _op_edit(data, rid, op)
    elif name == "remove":
        _op_remove(data, rid)
    elif name == "reset":
        _op_reset(data, rid)
    else:
        _op_toggle(data, rid, name == "enable")
    return {"op": name, "id": rid, "before": before, "after": _view(data, rid)}


# --- AI 判定の記録（rule-review.json） ---


def read_reviews(work) -> list[dict]:
    f = Path(work) / REVIEW_FILE
    if not f.is_file():
        return []
    try:
        data = json.loads(paths.read_text(f))
    except json.JSONDecodeError as e:
        raise ValueError(f"{f} が壊れています（JSON として読めません）: {e}") from e
    reviews = data.get("reviews") if isinstance(data, dict) else None
    if not isinstance(reviews, list):
        raise ValueError(f'{f} の形が違います（{{"reviews": [...]}}）')
    return reviews


def _write_reviews(work, reviews: list[dict]) -> None:
    paths.write_json(Path(work) / REVIEW_FILE, {"reviews": reviews})


def import_reviews(work, data, home=None) -> int:
    """{"reviews": [...]} を検証して書く。同じ rule+page は上書きし、ほかは残す。1 件でも不正なら何も書かない。"""
    work = Path(work)
    items = data.get("reviews") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError('{"reviews": [...]} の形で渡してください')
    ai = {r["id"] for r in effective(home) if r["kind"] == "AI"}
    md = paths.read_text(work / "script.md") if (work / "script.md").is_file() else None
    if md is None:
        raise ValueError(f"{work / 'script.md'} がありません")
    pages = {"deck", *(s["id"][1:] for s in script_lint.parse(md))}
    errors = []
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            errors.append(f"{n}: 項目はオブジェクトで書きます")
        elif it.get("rule") not in ai:
            errors.append(f"{n}: {it.get('rule')!r} は有効な AI のルールではありません")
        elif it.get("page") not in pages:
            errors.append(f"{n}: ページ {it.get('page')!r} がありません（deck か原稿のスライド番号 2 桁）")
        elif it.get("status") not in STATUSES:
            errors.append(f"{n}: status は ok・warn・ng のどれかです（{it.get('status')!r}）")
        elif not isinstance(it.get("message"), str) or (it["status"] != "ok" and not it["message"].strip()):
            errors.append(f"{n}: message（理由。どのページの何がどうか）が必要です")
    if errors:
        raise ValueError("\n".join(errors))
    merged = {(r["rule"], r["page"]): r for r in read_reviews(work)}
    for it in items:
        merged[(it["rule"], it["page"])] = {k: it[k] for k in ("rule", "page", "status", "message")}
    _write_reviews(work, list(merged.values()))
    return len(items)


def clear_reviews(work, rule: str | None = None, page: str | None = None) -> int:
    reviews = read_reviews(work)
    keep = [r for r in reviews if not ((rule is None or r["rule"] == rule) and (page is None or r["page"] == page))]
    if len(keep) != len(reviews) or (Path(work) / REVIEW_FILE).is_file():
        _write_reviews(work, keep)
    return len(reviews) - len(keep)
