# ruff: noqa: S101  # pytest の assert
"""check: ヘッドメッセージ・題の最終行が 1〜2 字だけになる（文字が 1 つだけ次の行に落ちる）ときは、警告する。

漢字は 1 字が 1em 幅で、書体が変わっても同じ字数で折り返すので、字数でそろえて確かめる。ブラウザを起動する（slow）。
"""

import json

import pytest
from pptx_maker import cli, fragcheck, initdir, paths

slow = pytest.mark.slow
LEAD = (
    '<section class="slide" data-layout="content">\n'
    '  <div class="pp-text" data-role="title" style="top:36px;height:50px">題</div>\n'
    '  <div class="pp-text b" data-role="lead"'
    ' style="left:84px;top:98px;width:1000px;height:80px;line-height:1.35">{}</div>\n'
    "</section>\n"
)


@pytest.fixture
def work(tmp_path):
    base = tmp_path / "out" / ".pptx-maker-source" / "deck"
    initdir.init(base)
    return paths.resolve_work(base)


def _violations(work, capsys, text):
    frag = work / "slides" / "02-R1.html"
    frag.parent.mkdir(exist_ok=True)
    frag.write_text(LEAD.format(text), encoding="utf-8")
    capsys.readouterr()
    cli.entry(["check", str(frag), "--workdir", str(work)])
    return [v for v in json.loads(capsys.readouterr().out) if v["rule"] == "orphanLine"]


@slow
def test_最終行が1字だけのヘッドメッセージは警告する(work, capsys):
    found = _violations(work, capsys, "漢" * 38)  # 1 行 37 字（1000 ÷ 27）。最終行は 1 字
    assert len(found) == 1
    assert found[0]["severity"] == "warn"
    assert "1 字分" in found[0]["message"]


@slow
def test_最終行が十分長いヘッドメッセージは警告しない(work, capsys):
    assert _violations(work, capsys, "漢" * 50) == []  # 最終行は 13 字


@slow
def test_1行に収まるヘッドメッセージは警告しない(work, capsys):
    assert _violations(work, capsys, "漢" * 20) == []


def test_最終行の警告は_R20_に対応づける():
    v = {"rule": "orphanLine", "slide": 1, "message": "最終行が 1 字分しかありません", "severity": "warn"}
    assert "R20" in fragcheck.summarize([v])
