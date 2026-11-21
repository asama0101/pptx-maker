# ruff: noqa: S101  # pytest の assert
"""選択結果の読み込み（choices.load）のテスト。"""

import json

import pytest
from pptx_maker import choices

from tests._flow import copied


def _put(base, name, data):
    d = base / "choices"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def test_load_reads_files_by_page_number(tmp_path):
    _put(tmp_path, "01.json", {"at": "2026-11-08T06:55:51.860Z", "comment": "", "pick": "R3", "status": "approved"})
    _put(tmp_path, "02.json", {"comment": " 直す ", "status": "saved"})
    assert choices.load(tmp_path) == {
        "01": {"pick": "R3", "comment": "", "status": "approved"},
        "02": {"pick": None, "comment": "直す", "status": "saved"},
    }


def test_load_requires_choices_folder(tmp_path):
    with pytest.raises(ValueError, match="choices"):
        choices.load(tmp_path)


def test_load_reports_broken_json(tmp_path):
    _put(tmp_path, "01.json", "{broken")
    with pytest.raises(ValueError, match="01.json"):
        choices.load(tmp_path)


def _copied(base, **pages):
    """選択ページの「Claude に渡す」がコピーする JSON（前後に説明があってもよい）。"""
    return "貼ります:\n```json\n" + copied(base, pages) + "\n```"


def test_import_writes_files_and_returns_commented_pages(tmp_path):
    text = _copied(
        tmp_path,
        **{
            "01": {"pick": "R1", "status": "approved", "comment": ""},
            "03": {"pick": "R2", "status": "saved", "comment": " 色を落とす "},
        },
    )
    assert choices.import_text(tmp_path, text) == [{"slide": "03", "comment": "色を落とす"}]
    assert choices.load(tmp_path) == {
        "01": {"pick": "R1", "comment": "", "status": "approved"},
        "03": {"pick": "R2", "comment": "色を落とす", "status": "saved"},
    }
    assert "at" in json.loads((tmp_path / "choices" / "01.json").read_text(encoding="utf-8"))


def test_import_書き込みの途中で失敗したら前のページも書かず元のままにする(tmp_path, monkeypatch):
    _put(tmp_path, "01.json", {"comment": "", "pick": "R2", "status": "saved"})
    before = (tmp_path / "choices" / "01.json").read_bytes()
    text = _copied(
        tmp_path,
        **{
            "01": {"pick": "R1", "status": "approved", "comment": ""},
            "02": {"pick": "R1", "status": "saved", "comment": ""},
        },
    )
    real, calls = choices.paths.write_json, []

    def flaky(target, data):
        calls.append(target)
        if len(calls) == 2:  # 2 ページ目の書き込みでディスクが満杯になる
            raise OSError("disk full")
        real(target, data)

    monkeypatch.setattr(choices.paths, "write_json", flaky)
    with pytest.raises(OSError, match="disk full"):
        choices.import_text(tmp_path, text)
    assert (tmp_path / "choices" / "01.json").read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "choices").iterdir()) == ["01.json"]  # 2 ページ目も一時ファイルも残らない


def test_import_before_write_は選択を書く前に呼ばれ_失敗すれば何も書かない(tmp_path):
    text = _copied(tmp_path, **{"01": {"pick": "R1", "status": "saved", "comment": ""}})
    seen = []

    def boom():
        seen.append((tmp_path / "choices").exists())
        raise OSError("design.md を書けません")

    with pytest.raises(OSError, match="design.md"):
        choices.import_text(tmp_path, text, before_write=boom)
    assert seen == [False]  # 呼ばれた時点では、まだ choices/ もできていない
    assert not (tmp_path / "choices").exists()


def test_import_leaves_pages_not_in_the_json(tmp_path):
    _put(tmp_path, "02.json", {"comment": "", "pick": "R1", "status": "approved"})
    choices.import_text(tmp_path, _copied(tmp_path, **{"01": {"pick": "R1", "status": "saved", "comment": ""}}))
    assert choices.load(tmp_path)["02"]["status"] == "approved"


def test_import_accepts_braces_around_the_json(tmp_path):
    body = copied(tmp_path, {"01": {"pick": "R1", "status": "saved", "comment": "直す"}})
    assert choices.import_text(tmp_path, "メモ {x}\n" + body + "\n以上です}") == [{"slide": "01", "comment": "直す"}]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ただの文章",
        "{broken",
        '{"pages": {}}',
        '{"pptx-maker-review": 1}',
        '{"pptx-maker-review": 1, "pages": {}}',
    ],
)
def test_import_rejects_other_text(tmp_path, text):
    with pytest.raises(ValueError, match="Claude に渡す|途中で変わっています"):
        choices.import_text(tmp_path, text)
    assert not (tmp_path / "choices").exists()


def test_import_rejects_content_changed_after_copy(tmp_path):
    """チャットからファイルへ写すときに、コメントの文字や承認の状態が変わったものは取り込まない。"""
    pages = {"01": {"pick": "R1", "status": "saved", "comment": "色を落とす"}}
    text = copied(tmp_path, pages)
    for old, new in (("色を落とす", "色を落と"), ('"saved"', '"approved"')):
        assert old in text
        with pytest.raises(ValueError, match="途中で変わっています"):
            choices.import_text(tmp_path, text.replace(old, new))
    assert not (tmp_path / "choices").exists()


def test_import_rejects_page_from_before_the_page_was_rebuilt(tmp_path):
    """作り直す前の古いページから渡された内容は、解決済みのコメントや取り消した承認を戻すので取り込まない。"""
    old = copied(tmp_path, {"03": {"pick": "R1", "status": "saved", "comment": "直して"}})
    choices.import_text(tmp_path, old)
    choices.resolve(tmp_path, ["03"])  # 直した（コメントを空にして、ページを作り直した）
    with pytest.raises(ValueError, match="古いページ"):
        choices.import_text(tmp_path, old)
    assert choices.load(tmp_path)["03"]["comment"] == ""


def test_import_same_paste_twice_is_rejected_the_second_time(tmp_path):
    text = copied(tmp_path, {"01": {"pick": "R1", "status": "approved", "comment": ""}})
    choices.import_text(tmp_path, text)
    with pytest.raises(ValueError, match="古いページ"):
        choices.import_text(tmp_path, text)


def test_stamp_differs_between_deliverables_and_after_a_change(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert choices.stamp(a) != choices.stamp(b)
    before = choices.stamp(a)
    _put(a, "01.json", {"comment": "", "pick": "R1", "status": "saved"})
    assert choices.stamp(a) != before


def test_import_reports_every_bad_page_and_writes_nothing(tmp_path):
    pages = {
        "1": {"pick": "R1", "status": "saved", "comment": ""},
        "02": {"pick": "R1", "status": "done", "comment": ""},
        "03": {"pick": "R1", "status": "saved", "comment": ""},
        "٠٤": {"pick": "R1", "status": "saved", "comment": ""},  # 全角でない数字（アラビア・インド数字）も断る
    }
    with pytest.raises(ValueError, match="1:.*\n02:") as e:
        choices.import_text(tmp_path, copied(tmp_path, pages))
    assert "03" not in str(e.value)
    assert "٠٤" in str(e.value)
    assert not (tmp_path / "choices").exists()


def test_import_rejects_approved_with_comment_or_without_pick(tmp_path):
    pages = {
        "01": {"pick": "R1", "status": "approved", "comment": "直す"},
        "02": {"pick": None, "status": "approved", "comment": ""},
    }
    with pytest.raises(ValueError, match="01:.*\n02:"):
        choices.import_text(tmp_path, copied(tmp_path, pages))
    assert not (tmp_path / "choices").exists()


def test_import_checks_slides_and_picks_exist(tmp_path):
    valid = {"01": ["R1", "R2"]}
    pages = {
        "01": {"pick": "R9", "status": "saved", "comment": ""},
        "99": {"pick": "R1", "status": "saved", "comment": ""},
    }
    with pytest.raises(ValueError, match="01: 案 R9 はありません.*\n99: このスライドはありません"):
        choices.import_text(tmp_path, copied(tmp_path, pages), valid)
    ok = {"01": {"pick": "R2", "status": "saved", "comment": ""}}
    assert choices.import_text(tmp_path, copied(tmp_path, ok), valid) == []


def test_resolve_clears_comment_and_unapproves(tmp_path):
    _put(tmp_path, "01.json", {"comment": "直す", "pick": "R2", "status": "approved"})
    _put(tmp_path, "02.json", {"comment": "", "pick": "R1", "status": "approved"})
    assert choices.resolve(tmp_path, ["01"]) == ["01"]
    assert choices.load(tmp_path) == {
        "01": {"pick": "R2", "comment": "", "status": "saved"},
        "02": {"pick": "R1", "comment": "", "status": "approved"},
    }


def test_resolve_does_not_unapprove_a_page_without_comment(tmp_path):
    _put(tmp_path, "02.json", {"comment": "", "pick": "R1", "status": "approved"})
    assert choices.resolve(tmp_path, ["02"]) == []
    assert choices.load(tmp_path)["02"]["status"] == "approved"


def test_resolve_unknown_slide_is_error(tmp_path):
    _put(tmp_path, "01.json", {"comment": "直す", "pick": "R1", "status": "saved"})
    with pytest.raises(ValueError, match="09"):
        choices.resolve(tmp_path, ["01", "09"])
    assert choices.load(tmp_path)["01"]["comment"] == "直す"


def test_read_state_is_empty_without_choices_folder(tmp_path):
    assert choices.read_state(tmp_path) == {}
