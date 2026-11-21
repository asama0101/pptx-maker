"""新しい流れ（choices/*.json → finalize --choices）をテストで通す補助。"""

import json
from pathlib import Path

from pptx_maker import candidates, choices, cli


def write_choices(base: Path, picks: dict[str, str], work: Path | None = None) -> Path:
    """`base/choices/<NN>.json` に承認済みの選択を書き、`base` を返す。`work` があれば、選んだ断片の指紋（frag）も書く
    （finalize が承認のあとの変更を見つけるのに要る）。"""
    cands = candidates.collect(work) if work else {}
    d = Path(base) / "choices"
    d.mkdir(parents=True, exist_ok=True)
    for nn, pick in picks.items():
        data = {"at": "2026-11-08T00:00:00.000Z", "comment": "", "pick": pick, "status": "approved"}
        if nn in cands:
            data["frag"] = choices.fragment_hash(cands[nn][pick])
        (d / f"{nn}.json").write_text(json.dumps(data), encoding="utf-8")
    return Path(base)


def finalize_all(work: Path, picks: dict[str, str] | None = None, choices_dir: Path | None = None) -> int:
    """全スライドを承認して finalize する。picks にないスライドは最初の案（R1）を選ぶ。終了コードを返す。"""
    work = Path(work)
    chosen = {nn: (picks or {}).get(nn) or sorted(c)[0] for nn, c in candidates.collect(work).items()}
    base = write_choices(choices_dir or work.parent / f"{work.name}-choices", chosen, work)
    return cli.main(["finalize", str(work), "--choices", str(base)])


def write_slide(slides: Path, nn: str, html: str, html2: str | None = None) -> None:
    """`slides/NN-R1.html` と `NN-R2.html` を書く（どのページも 2 案が要る）。html2 がなければ同じ内容。"""
    Path(slides).mkdir(parents=True, exist_ok=True)
    for key, body in (("R1", html), ("R2", html if html2 is None else html2)):
        (Path(slides) / f"{nn}-{key}.html").write_text(body, encoding="utf-8")


def copied(work: Path, pages: dict, **over) -> str:
    """選択ページの「Claude に渡す」がコピーする JSON（今の choices/ の指紋と検査値つき）。over で項目を差し替える。"""
    cands = candidates.collect(work) if (Path(work) / "slides").is_dir() else {}
    pages = {  # 承認のページには、選んだ断片の指紋 fr を足す（利用者が見た断片。`fr` を書いてあるものは、そのまま）
        nn: {**d, "fr": choices.fragment_hash(cands[nn][d["pick"]])}
        if d.get("status") == "approved" and "fr" not in d and d.get("pick") in cands.get(nn, {})
        else d
        for nn, d in pages.items()
    }
    data = {"pptx-maker-review": 1, "base": choices.stamp(work), "check": choices.checksum(pages), "pages": pages}
    return json.dumps({**data, **over}, ensure_ascii=False)
