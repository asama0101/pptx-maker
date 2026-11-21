"""配色セット（基調色 1 + 強調色 1〜2）。案の選択ページ（review.html）で、目で見て選べる。

選んだセットは、「Claude に渡す」の JSON の `color` として渡り、`choices-import` が設計図の
`基調色:`・`強調色:` に書く（検査と theme.css は、書かれた色から theme.derive で作る）。
"""

from pathlib import Path

from . import design_colors, paths, theme

# (名前, 基調色, 強調色, 向く場面)。強調色は 1 色（2 色目を使うときは設計図に足す）
SETS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("紺とオレンジ", "#1F3A5F", ("#D9730D",), "稟議・提案・計画。堅実で、要点が一点で光る（定番）"),
    ("紺と赤", "#1F3A5F", ("#C0392B",), "課題・リスク・障害の報告。問題の箇所を強く示す"),
    ("青と黄土", "#1E4FA0", ("#A86A00",), "技術・製品・サービスの説明。明るく、見やすい"),
    ("青緑と赤", "#0E6B73", ("#C0392B",), "運用・監査・品質の報告。落ち着いた地に、警告が目立つ"),
    ("深青緑と琥珀", "#0E5E6F", ("#B26B00",), "事業計画・効果の説明。信頼感と、伸びを示す色"),
    ("緑と琥珀", "#1B5E3F", ("#B26B00",), "環境・人事・ESG の資料。安心感がある"),
    ("えんじと金茶", "#7A1F3D", ("#9A6B00",), "経営会議・方針・IR。重みと格がある"),
    ("墨と青", "#2B2B2B", ("#1F5FBF",), "無彩色が主役。図表・データを引き立てたいとき"),
)


def derived(accent: str, emphasis: tuple[str, ...]) -> theme.Palette:
    """検査と同じ作り方（白地で 4.5:1 になるよう暗くした色）。ページの色はこの色で描く。"""
    return theme.derive(accent, emphasis[0] if emphasis else None)


def review_data(work: Path) -> dict:
    """案の選択ページに埋め込む配色のデータ: 8 つのセットと、今の設計図の色。
    各セットの `vars` は、ページの CSS 変数に当てる色（theme.css と同じ作り方）。"""
    sets = [
        {
            "name": name,
            "note": note,
            "accent": accent,
            "emphasis": emph[0],
            "vars": theme.css_vars(derived(accent, emph)),
        }
        for name, accent, emph, note in SETS
    ]
    has_cfg = (Path(work) / "template.json").is_file()  # 作業フォルダの設定がなくても、設計図の色だけで決める
    palette = (
        design_colors.load_for(Path(work), paths.read_cfg(work)) if has_cfg else design_colors.load(Path(work), {})
    )
    raw_accent, raw_emph = design_colors._read_design(Path(work))  # noqa: SLF001
    accent = raw_accent or palette.accent
    emphasis = raw_emph[0] if raw_emph else palette.emphasis
    name = next(
        (
            s["name"]
            for s in sets
            if s["accent"].upper() == accent.upper() and s["emphasis"].upper() == emphasis.upper()
        ),
        None,
    )
    return {
        "sets": sets,
        "current": {"name": name, "accent": accent, "emphasis": emphasis, "vars": theme.css_vars(palette)},
    }
