"""案（slides/NN-Rk.html）を 1 つずつ測り、check の違反を R20・R23・R26 に対応づける（案の選択ページ用）。

Chromium は 1 回だけ起動して、すべての案を測る。R20・R23・R26 以外の違反
（overlap・overflow・keepout・outOfSlide など）は、ルールに対応しないので、ここでは返さない（build が止める）。"""

from pathlib import Path

# check の違反の種類 → ルール
RULE_OF = {
    "chromeSpec": "R20",
    "orphanLine": "R20",
    "fontMin": "R26",
    "pptxFontMin": "R26",
    "colorRange": "R23",
    "colorNeon": "R23",
    "colorContrast": "R23",
}
SHOWN = 3  # 1 つの結果に書く違反の数（残りは「ほか n 件」）


def summarize(violations: list[dict]) -> dict[str, str]:
    """違反の一覧 → {ルール: メッセージ}（対応づけのない違反は捨てる）。違反のないルールは入らない。"""
    by: dict[str, list[str]] = {}
    for v in violations:
        rid = RULE_OF.get(v["rule"])
        if rid:
            by.setdefault(rid, []).append(f"{v['message']}（{v['rule']}）")
    return {
        rid: " / ".join(msgs[:SHOWN]) + (f" / ほか {len(msgs) - SHOWN} 件" if len(msgs) > SHOWN else "")
        for rid, msgs in by.items()
    }


def check_variants(
    work: Path, nns: dict[str, list[str]], failed: dict[str, str] | None = None
) -> dict[tuple[str, str], dict[str, str] | None]:
    """{(スライド番号, 案): summarize の結果}。測れなかった案は None（`failed` を渡すと {"03-R2": 理由} を入れる）。
    ブラウザが起動できなければ例外のまま上げる。"""
    from . import check, cli, measure

    work = Path(work)
    cfg, info, palette = cli._load_cfg(work)  # noqa: SLF001
    rules = cli._load_rules(work)  # noqa: SLF001
    backgrounds = cli._backgrounds(work, cfg, info)  # noqa: SLF001
    out: dict[tuple[str, str], dict[str, str] | None] = {}
    with measure.open_browser() as browser:
        for nn, keys in nns.items():
            for key in keys:
                frag = work / "slides" / f"{nn}-{key}.html"
                try:
                    with cli._as_page(frag, work) as page:  # noqa: SLF001
                        model = measure.measure(page, browser=browser)
                    out[(nn, key)] = summarize(check.check_model(model, info, palette, rules, backgrounds))
                except Exception as e:  # noqa: BLE001  # 1 つの案が測れなくても、ほかの案は測る（その案は build のまま）
                    out[(nn, key)] = None
                    if failed is not None:
                        failed[f"{nn}-{key}"] = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
    return out
