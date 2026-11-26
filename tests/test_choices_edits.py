# ruff: noqa: S101  # pytest の assert
"""choices-import の edits（編集モードの文言・位置の直し）: 断片への書き戻し、承認を外す、全件エラー、途中の失敗。"""

import json
from pathlib import Path

import pytest
from pptx_maker import candidates, choices, cli, paths

from tests._flow import copied, write_slide
from tests.test_fragedit import FRAG, POS
from tests.test_review_page_checks import _work

R2_FRAG = FRAG.replace("本文 A", "本文 A2")


def _setup(tmp_path: Path) -> Path:
    work = _work(tmp_path)
    write_slide(work / "slides", "01", FRAG, R2_FRAG)
    return work


def _raw(work: Path, name: str) -> str:
    return (work / "slides" / name).read_bytes().decode("utf-8")


def _ef(work: Path, nn: str = "01", key: str = "R2") -> str:
    return choices.fragment_hash(candidates.collect(work)[nn][key])


def _run(work: Path, tmp_path: Path, pages: dict) -> int:
    f = tmp_path / "paste.json"
    f.write_text(copied(work, pages), encoding="utf-8")
    return cli.main(["choices-import", str(work), "--file", str(f)])


def _page(work: Path, status: str = "approved", **over) -> dict:
    return {"pick": "R1", "status": status, "comment": "", **over}


def _snapshot(work: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(work)): p.read_bytes()
        for d in ("slides", "choices")
        if (work / d).is_dir()
        for p in sorted((work / d).iterdir())
    }


def test_edits_断片に書き戻し承認を外す(tmp_path, capsys):
    work = _setup(tmp_path)
    before = {n: _raw(work, n) for n in ("01-R1.html", "01-R2.html")}
    edits = {"R2": {"ef": _ef(work), "items": {"1": {"left": 100, "text": ["新A", "本文 B"]}}}}

    code = _run(work, tmp_path, {"01": _page(work, edits=edits)})

    out = capsys.readouterr().out
    assert code == 0
    expected = before["01-R2.html"].replace(POS, "left:100px;top:140px;width:500px;height:100px")
    expected = expected.replace("本文 A2<br>", "新A<br>")
    assert _raw(work, "01-R2.html") == expected
    assert _raw(work, "01-R1.html") == before["01-R1.html"]
    saved = json.loads((work / "choices" / "01.json").read_text(encoding="utf-8"))
    assert saved["status"] == "saved"
    assert saved["pick"] == "R1"
    assert "frag" not in saved
    assert "edits" not in saved
    assert '"edited": [{"slide": "01", "variant": "R2", "items": 1}]' in out
    assert not list(work.rglob("*.new"))


@pytest.mark.parametrize(
    "make",
    [
        lambda ef: {"R2": {"ef": "000000000000", "items": {"1": {"left": 100}}}},
        lambda ef: {"R2": "文字列"},
        lambda ef: {"R2": {"ef": 1, "items": {"1": {"left": 100}}}},
        lambda ef: {"R2": {"ef": ef, "items": [1]}},
        lambda ef: {"R2": {"ef": ef, "items": {"一": {"left": 100}}}},
        lambda ef: {"R9": {"ef": ef, "items": {"1": {"left": 100}}}},
        lambda ef: {"R2": {"ef": ef, "items": {"0": {"left": 100}}}},  # 題（固定部分）の移動は validate が断る
    ],
)
def test_edits_誤りがあれば全件断り何も書かない(tmp_path, capsys, make):
    work = _setup(tmp_path)
    write_slide(work / "slides", "02", FRAG, R2_FRAG)
    good = {"R2": {"ef": _ef(work), "items": {"1": {"left": 100}}}}
    bad = make(_ef(work, "02"))
    snap = _snapshot(work)

    code = _run(work, tmp_path, {"01": _page(work, edits=good), "02": _page(work, edits=bad)})

    err = capsys.readouterr().err
    assert code == 2
    assert err.startswith("エラー")
    assert "02" in err
    assert _snapshot(work) == snap
    assert not list(work.rglob("*.new"))


def test_edits_同じ貼り付けは_2_回目に断られる(tmp_path):
    work = _setup(tmp_path)
    orig = _raw(work, "01-R2.html")
    edits = {"R2": {"ef": _ef(work), "items": {"1": {"left": 100}}}}
    f = tmp_path / "paste.json"
    f.write_text(copied(work, {"01": _page(work, edits=edits)}), encoding="utf-8")
    args = ["choices-import", str(work), "--file", str(f)]

    assert cli.main(args) == 0
    once = _raw(work, "01-R2.html")
    assert once == orig.replace(POS, "left:100px;top:140px;width:500px;height:100px")
    assert cli.main(args) == 2
    assert _raw(work, "01-R2.html") == once


def test_edits_なしの貼り付けは従来どおり(tmp_path, capsys):
    work = _setup(tmp_path)

    assert _run(work, tmp_path, {"01": _page(work, "saved")}) == 0

    assert set(json.loads(capsys.readouterr().out)) == {"comments"}


def test_edits_空の_items_は何もしない(tmp_path, capsys):
    work = _setup(tmp_path)
    before = _raw(work, "01-R2.html")
    edits = {"R2": {"ef": _ef(work), "items": {}}}

    assert _run(work, tmp_path, {"01": _page(work, edits=edits)}) == 0

    assert "edited" not in json.loads(capsys.readouterr().out)
    assert _raw(work, "01-R2.html") == before
    saved = json.loads((work / "choices" / "01.json").read_text(encoding="utf-8"))
    assert saved["status"] == "approved"
    assert saved["frag"]


def test_edits_書き込みの途中で失敗したら断片も選択も元のまま(tmp_path, monkeypatch, capsys):
    work = _setup(tmp_path)
    edits = {"R2": {"ef": _ef(work), "items": {"1": {"left": 100}}}}
    snap = _snapshot(work)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(paths, "write_json", boom)

    code = _run(work, tmp_path, {"01": _page(work, edits=edits)})

    assert code == 2
    assert "disk full" in capsys.readouterr().err
    assert _snapshot(work) == snap
    assert not list(work.rglob("*.new"))
