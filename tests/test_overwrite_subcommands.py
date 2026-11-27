"""上書きは別のサブコマンド（*-overwrite）で行い、--force は受け付けない。権限（allowed-tools）が上書き版に届かない。"""

# ruff: noqa: S101  # pytest の assert
import re

import pytest
from pptx import Presentation
from pptx_maker import cli, paths

from tests._paths import PKG

SKILLS = sorted((PKG / "skills").rglob("SKILL.md"))
RUN = 'python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}"'


def main(capsys, *argv):
    capsys.readouterr()
    rc = cli.main(list(argv))
    return rc, capsys.readouterr().err


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PPTX_MAKER_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.mark.parametrize("cmd", ["init", "build", "template-import"])
def test_force_は認識されず終了コード2(cmd, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([cmd, str(tmp_path / "x"), "--force"])
    assert e.value.code == 2
    assert "--force" in capsys.readouterr().err


def test_init_は空でないと終了コード2_init_overwrite_は上書きする(tmp_path, capsys):
    base = tmp_path / "out" / ".pptx-maker-source" / "deck"
    assert cli.main(["init", str(base), "--footer", "A"]) == 0
    work = paths.resolve_work(base)
    capsys.readouterr()
    rc, err = main(capsys, "init", str(base))
    assert rc == 2
    assert "init-overwrite" in err
    assert cli.main(["init-overwrite", str(base)]) == 0
    assert paths.read_cfg(work)["footer"] == "A"  # 渡さない設定は残る


def test_template_import_は終了コード4_template_overwrite_は置き換える(home, tmp_path, capsys):
    old, new = tmp_path / "o.pptx", tmp_path / "n.pptx"
    prs = Presentation()
    prs.slide_width, prs.slide_height = 12192000, 6858000
    prs.save(str(old))
    prs.core_properties.title = "新しい版"
    prs.save(str(new))
    assert cli.main(["template-import", str(old), "--name", "標準"]) == 0
    rc, err = main(capsys, "template-import", str(new), "--name", "標準")
    assert rc == 4
    assert "template-overwrite" in err
    assert (home / "templates" / "標準.pptx").read_bytes() == old.read_bytes()
    assert cli.main(["template-overwrite", str(new), "--name", "標準"]) == 0
    assert (home / "templates" / "標準.pptx").read_bytes() == new.read_bytes()


def _allowed_patterns(path):
    m = re.search(r"^allowed-tools: '(.*)'$", path.read_text(encoding="utf-8"), re.M)
    assert m, path
    return re.findall(r"Bash\((.*?)\)(?= Bash\(|$)", m.group(1))


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("cmd", ["init-overwrite", "build-overwrite", "template-overwrite"])
def test_allowed_tools_は上書き版のコマンドに一致しない(skill, cmd):
    command = f'{RUN} {cmd} "<元データ>" --out "x.pptx"'
    for pat in _allowed_patterns(skill):
        regex = "^" + ".*".join(re.escape(x) for x in pat.split("*")) + "$"
        assert not re.match(regex, command), (skill.parent.name, pat)


def test_allowed_tools_の検査は通常版には一致する():
    pats = _allowed_patterns(PKG / "skills" / "create" / "SKILL.md")
    command = f'{RUN} build "<元データ>"'
    assert any(re.match("^" + ".*".join(re.escape(x) for x in p.split("*")) + "$", command) for p in pats)
