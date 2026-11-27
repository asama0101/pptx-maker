# ruff: noqa: S101  # pytest の assert
"""review-page は review.html を書いたあと、既定のブラウザで開く（--no-open で開かない。開けなくても失敗にしない）。"""

import json
import webbrowser
from pathlib import Path

from pptx_maker import cli, initdir, paths

from tests.test_review_page_render import _slides


def _work(tmp_path: Path) -> Path:
    base = tmp_path / "out" / ".pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    s = work / "slides"
    s.mkdir(exist_ok=True)
    for name, text in _slides().items():
        (s / name).write_text(text, encoding="utf-8")
    return work


def _run(work, capsys, *extra):
    code = cli.entry(["review-page", str(work), "--no-measure", *extra])
    return code, capsys.readouterr().out


def test_review_page_は書いたあとブラウザで開く(tmp_path, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    work = _work(tmp_path)
    code, out = _run(work, capsys)
    assert code == 0
    assert opened == [(work / "review.html").as_uri()]
    assert json.loads(out)["path"] == str(work / "review.html")


def test_review_page_は_no_open_で開かない(tmp_path, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    code, _ = _run(_work(tmp_path), capsys, "--no-open")
    assert code == 0
    assert opened == []


def test_review_page_は開けなくても終了コード_0(tmp_path, monkeypatch, capsys):
    def boom(url, *a, **k):
        raise webbrowser.Error("no browser")

    monkeypatch.setattr(webbrowser, "open", boom)
    code, out = _run(_work(tmp_path), capsys)
    assert code == 0
    assert set(json.loads(out)) == {"path", "warnings"}
