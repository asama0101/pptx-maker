"""コードレビューの指摘 1〜3・5 の再現テスト。ブラウザなしで動く。"""

# ruff: noqa: S101  # pytest の assert
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pptx_maker import candidates, paths

RUN_PY = Path(__file__).resolve().parent.parent / "plugins" / "pptx-maker" / "run.py"


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "w"
    (work / "slides").mkdir(parents=True)
    return work


@pytest.mark.parametrize("name", ["CON ", "con .draft", "NUL  .v2"])
def test_拡張子の前の空白があっても予約名は弾く(name):
    assert paths.filename_problem(name) is not None


def test_子プロセスは利用者の_PYTHONPATH_を残してプラグインを先頭に足す():
    spec = importlib.util.spec_from_file_location("pptx_run_for_env", RUN_PY)
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    env = run.child_env({"PYTHONPATH": r"C:\extra", "A": "1"})
    assert env["PYTHONPATH"].split(os.pathsep) == [str(run.SKILL), r"C:\extra"]
    assert env["A"] == "1"
    assert run.child_env({})["PYTHONPATH"] == str(run.SKILL)


def test_入口も子プロセスもバイトコードを書かない(monkeypatch):
    """A1: 更新で入れ替わる ${CLAUDE_PLUGIN_ROOT} に __pycache__ を書かない。"""
    monkeypatch.setattr(sys, "dont_write_bytecode", False)  # 終了時に元へ戻る
    spec = importlib.util.spec_from_file_location("pptx_run_for_bytecode", RUN_PY)
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    assert sys.dont_write_bytecode is True
    assert run.child_env({})["PYTHONDONTWRITEBYTECODE"] == "1"


def test_BOM_付きの断片でも先頭に_BOM_が残らない(tmp_path):
    work = _work(tmp_path)
    (work / "slides" / "01-R1.html").write_bytes(b"\xef\xbb\xbf<section>x</section>")
    (work / "slides" / "01-R2.html").write_text("y", encoding="utf-8")
    text = candidates.collect(work)["01"]["R1"]
    assert not text.startswith("\ufeff")
    assert "<section>x</section>" in text
