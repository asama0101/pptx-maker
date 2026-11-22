"""設計図（design.md）の `デザイン方向の候補:`・`デザイン方向:` を読み書きする。"""

import re
from pathlib import Path

from . import paths

_CANDIDATES = re.compile(r"^\s*(?:-\s+)?デザイン方向の候補\s*[:：][ \t]*(.*?)\s*$", re.MULTILINE)
_CURRENT = re.compile(r"^\s*(?:-\s+)?デザイン方向\s*[:：][ \t]*(.+?)\s*$", re.MULTILINE)
_SPLIT = re.compile(r"[,、]")


def _read(work: Path) -> str | None:
    path = Path(work) / "design.md"
    return paths.read_text(path) if path.is_file() else None


def candidate_list(work: Path) -> dict[str, str] | None:
    """`デザイン方向の候補:` の行を {"R1": 名前, ...}（挿入順）にして返す。

    設計図か行がなければ None。壊れていれば ValueError。
    """
    text = _read(work)
    m = _CANDIDATES.search(text) if text is not None else None
    if m is None:
        return None
    line = m.group(0).strip()
    result: dict[str, str] = {}
    for part in _SPLIT.split(m.group(1)):
        key, sep, name = part.partition("=")
        key, name = key.strip(), name.strip()
        if not sep or not name:
            raise ValueError(f"デザイン方向の候補の書式が違います（R1=名前 の形）: {line}")
        result[key] = name
    n = len(result)
    if n < 3 or n > 4 or list(result) != [f"R{i}" for i in range(1, n + 1)] or n != len(_SPLIT.split(m.group(1))):
        raise ValueError(f"デザイン方向の候補は R1 から連続した 3〜4 個にしてください: {line}")
    return result


def current(work: Path) -> str | None:
    """`デザイン方向:` の値。なければ None。"""
    text = _read(work)
    m = _CURRENT.search(text) if text is not None else None
    return m.group(1) if m else None


def set_current(work: Path, name: str) -> None:
    """設計図の `デザイン方向:` の行を書き換える（なければ足す。ほかの行は触らない。設計図がなければ作る）。"""
    text = _read(work)
    if text is None:
        text = "# 設計図\n"
    pat = re.compile(r"^(\s*(?:-\s+)?)デザイン方向\s*[:：].*$", re.MULTILINE)
    if pat.search(text):
        text = pat.sub(lambda m: f"{m.group(1)}デザイン方向: {name}", text, count=1)
    else:
        text = text.rstrip("\n") + f"\n- デザイン方向: {name}\n"
    paths.write_text(Path(work) / "design.md", text)
