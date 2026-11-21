# ruff: noqa: S101  # pytest の assert
"""配色セット: 全セットが検査の制約（白地で 4.5:1、基調と強調が別の色）を満たす。"""

from pptx_maker import color_sets, theme


def test_全セットで基調色と強調色は白地で読める():
    for name, accent, emph, _ in color_sets.SETS:
        p = color_sets.derived(accent, emph)
        assert theme.contrast(p.accent, "#FFFFFF") >= 4.5, name
        assert theme.contrast(p.emphasis, "#FFFFFF") >= 4.5, name


def test_全セットで基調色と強調色は見分けられる():
    for name, accent, emph, _ in color_sets.SETS:
        p = color_sets.derived(accent, emph)
        assert theme.hue_distance(p.accent, p.emphasis) >= 40 or theme.is_gray(p.accent), name


def test_名前は重ならず_強調色は2色まで():
    names = [s[0] for s in color_sets.SETS]
    assert len(names) == len(set(names)) >= 6
    assert all(1 <= len(s[2]) <= 2 for s in color_sets.SETS)
