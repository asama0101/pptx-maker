"""final.html を Chromium で開き、スライドごとの確認用の画像にする。
PPTX の実描画ではない（PowerPoint で最終確認する）。"""

from pathlib import Path


def screenshots(html: Path, out_dir: Path, browser=None) -> list[Path]:
    from .measure import check_not_unc, guarded_page, open_browser

    html = check_not_unc(html)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    with open_browser(browser) as b, guarded_page(b, viewport={"width": 1280, "height": 720}) as page:
        page.goto(html.as_uri())
        page.evaluate("document.fonts.ready.then(() => true)")
        page.wait_for_timeout(300)  # chart-preview.js の描画を待つ
        for i, el in enumerate(page.query_selector_all("section.slide"), start=1):
            path = out_dir / f"slide-{i:02d}.png"
            el.screenshot(path=str(path))
            out.append(path)
    return out
