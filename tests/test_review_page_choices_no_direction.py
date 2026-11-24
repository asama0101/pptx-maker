# ruff: noqa: S101  # pytest の assert
"""古い選択ページの JSON（direction つき）も取り込める。設計図の方向は書き換えない。"""

from pptx_maker import cli, initdir, paths

from tests._flow import copied
from tests.test_review_page_render import _slides


def test_choices_import_は_direction_を無視する(tmp_path):
    base = tmp_path / "out" / "pptx-maker-source" / "deck"
    initdir.init(base)
    work = paths.resolve_work(base)
    s = work / "slides"
    s.mkdir(exist_ok=True)
    for name, text in _slides().items():
        (s / name).write_text(text, encoding="utf-8")
    design = "# 設計図\n- デザイン方向の候補: R1=a, R2=b\n- デザイン方向: a\n"
    (work / "design.md").write_text(design, encoding="utf-8")
    f = tmp_path / "paste.txt"
    f.write_text(
        copied(work, {"02": {"pick": "R1", "status": "saved", "comment": ""}}, direction="R2"), encoding="utf-8"
    )
    assert cli.entry(["choices-import", str(work), "--file", str(f)]) == 0
    assert (work / "design.md").read_text(encoding="utf-8") == design
