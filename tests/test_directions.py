from pathlib import Path

import pytest
from pptx_maker import directions


def _design(work: Path, text: str) -> None:
    (work / "design.md").write_text(text, encoding="utf-8", newline="\n")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "- デザイン方向の候補: R1=決定先行型, R2=比較表中心型, R3=数字と推移型",
            {"R1": "決定先行型", "R2": "比較表中心型", "R3": "数字と推移型"},
        ),
        (
            "- デザイン方向の候補: R1=a, R2=b, R3=c, R4=d",
            {"R1": "a", "R2": "b", "R3": "c", "R4": "d"},
        ),
        (
            "デザイン方向の候補：R1=甲、R2=乙、R3=丙",
            {"R1": "甲", "R2": "乙", "R3": "丙"},
        ),
    ],
)
def test_candidate_list_parses_three_and_four(tmp_path, line, expected):
    _design(tmp_path, f"# 設計図\n{line}\n")
    result = directions.candidate_list(tmp_path)
    assert result == expected
    assert list(result) == list(expected)


def test_candidate_list_none_when_absent(tmp_path):
    assert directions.candidate_list(tmp_path) is None
    _design(tmp_path, "# 設計図\n- 基調色: #112233\n")
    assert directions.candidate_list(tmp_path) is None


@pytest.mark.parametrize(
    "body",
    [
        "R1=a, R3=b, R4=c",
        "R1=a, R1=b, R2=c",
        "R1=a, R2=b",
        "R1=a, R2=b, R3=c, R4=d, R5=e",
        "R1=, R2=b, R3=c",
        "R1=a, b, R3=c",
    ],
)
def test_candidate_list_rejects_malformed(tmp_path, body):
    _design(tmp_path, f"# 設計図\n- デザイン方向の候補: {body}\n")
    with pytest.raises(ValueError, match="デザイン方向の候補") as e:
        directions.candidate_list(tmp_path)
    assert body in str(e.value)  # 問題の行の中身をメッセージに引く


def test_candidate_list_empty_value_does_not_swallow_next_line(tmp_path):
    _design(tmp_path, "# 設計図\n- デザイン方向の候補:\n- 基調色: #112233\n")
    with pytest.raises(ValueError, match="デザイン方向の候補") as e:
        directions.candidate_list(tmp_path)
    assert "基調色" not in str(e.value)


def test_current_empty_value_is_none(tmp_path):
    _design(tmp_path, "# 設計図\n- デザイン方向:\n- 基調色: #112233\n")
    assert directions.current(tmp_path) is None


def test_current_ignores_candidate_line(tmp_path):
    _design(tmp_path, "# 設計図\n- デザイン方向の候補: R1=a, R2=b, R3=c\n")
    assert directions.current(tmp_path) is None


def test_current_reads_value(tmp_path):
    assert directions.current(tmp_path) is None
    _design(tmp_path, "# 設計図\n- デザイン方向の候補: R1=a, R2=b, R3=c\n- デザイン方向: 決定先行型\n")
    assert directions.current(tmp_path) == "決定先行型"


def test_set_current_replaces_adds_and_keeps_other_lines(tmp_path):
    # design.md がなければ作る
    directions.set_current(tmp_path, "甲")
    assert (tmp_path / "design.md").read_text(encoding="utf-8") == "# 設計図\n- デザイン方向: 甲\n"

    # 置き換え。ほかの行（候補の行を含む）は変わらない
    others = "# 設計図\n- 基調色: #112233\n- デザイン方向の候補: R1=a, R2=b, R3=c\n"
    _design(tmp_path, others + "- デザイン方向: 甲\n- 強調色: #445566\n")
    directions.set_current(tmp_path, "乙")
    assert (tmp_path / "design.md").read_text(encoding="utf-8") == others + "- デザイン方向: 乙\n- 強調色: #445566\n"
    assert directions.current(tmp_path) == "乙"

    # なければ末尾に足す
    _design(tmp_path, others)
    directions.set_current(tmp_path, "丙")
    assert (tmp_path / "design.md").read_text(encoding="utf-8") == others + "- デザイン方向: 丙\n"


def test_set_current_は書き込みが途中で止まっても元の設計図を壊さない(tmp_path, monkeypatch):
    _design(tmp_path, "# 設計図\n- デザイン方向: 甲\n")

    def boom(self, target):
        raise OSError("置き換えに失敗")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="置き換えに失敗"):
        directions.set_current(tmp_path, "乙")
    assert (tmp_path / "design.md").read_text(encoding="utf-8") == "# 設計図\n- デザイン方向: 甲\n"
    assert [p.name for p in tmp_path.iterdir()] == ["design.md"]  # 一時ファイルが残らない


def test_UTF8_でない設計図は_ValueError(tmp_path):
    (tmp_path / "design.md").write_bytes("# 設計図\n- デザイン方向: 甲\n".encode("cp932"))
    with pytest.raises(ValueError, match="UTF-8"):
        directions.current(tmp_path)
