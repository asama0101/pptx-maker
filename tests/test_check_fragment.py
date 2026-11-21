"""check: 断片（slides/NN-Rk.html。<section> だけ）をそのまま検査できる。設計図の色は検査の前に theme.css へ反映する。

ブラウザを実際に起動する（slow）。
"""

# ruff: noqa: S101  # pytest の assert
import json

import pytest
from pptx_maker import cli, design_colors, initdir, paths

FRAGMENT = (
    '<section class="slide" data-layout="content">\n'
    '  <div class="pp-text" data-role="title" style="top:36px;height:50px">題</div>\n'
    '  <div class="pp-text" data-role="body" style="left:64px;top:200px;width:600px;height:60px">本文</div>\n'
    "</section>\n"
)

slow = pytest.mark.slow


@pytest.fixture
def work(tmp_path):
    base = tmp_path / "out" / "pptx-maker-source" / "deck"
    initdir.init(base)
    return paths.resolve_work(base)


def _check(capsys, *argv):
    capsys.readouterr()
    rc = cli.entry(["check", *argv])
    return rc, capsys.readouterr().out


@slow
def test_断片を渡すとテーマの文字サイズで検査され違反は0件(work, capsys):
    frag = work / "slides" / "02-R1.html"
    frag.parent.mkdir(exist_ok=True)
    frag.write_text(FRAGMENT, encoding="utf-8")
    rc, out = _check(capsys, str(frag), "--workdir", str(work))
    assert (rc, json.loads(out)) == (0, [])
    assert not any(p.name.startswith("check-") for p in work.iterdir())  # 一時ファイルを作業フォルダに残さない


@slow
def test_検査の前に設計図の色が_theme_css_に反映される(work, capsys):
    (work / "design.md").write_text("- 基調色: #1F3A5F\n- 強調色: #D9730D\n", encoding="utf-8")
    frag = work / "slides" / "02-R1.html"
    frag.parent.mkdir(exist_ok=True)
    frag.write_text(FRAGMENT, encoding="utf-8")
    rc, _ = _check(capsys, str(frag), "--workdir", str(work))
    assert rc == 0
    emphasis = design_colors.load_for(work, paths.read_cfg(work)).emphasis  # 白地の対比 4.5 に調整した色
    assert f"--emphasis: {emphasis};" in (work / "theme.css").read_text(encoding="utf-8")


@slow
def test_先頭に_html_コメントがある断片も包んで検査する(work, capsys):
    """見本の断片は先頭に用途のコメントがある。写して書いた断片が、完全な html と取り違えられない。"""
    frag = work / "slides" / "02-R1.html"
    frag.parent.mkdir(exist_ok=True)
    comment = "<!-- 用途: 見本\n     差し替える所: 本文 -->\n"
    frag.write_text(comment + FRAGMENT, encoding="utf-8")
    rc, out = _check(capsys, str(frag), "--workdir", str(work))
    assert (rc, json.loads(out)) == (0, [])
