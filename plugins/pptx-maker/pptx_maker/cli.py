import argparse
import contextlib
import functools
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from . import __version__, env, paths


def _has_font(registered: list[str], family: str) -> bool:
    return any(family in name for name in registered)


def _registered_fonts() -> list[str]:
    """レジストリの登録名（全員向け・利用者向け）。TTC 内のファミリも登録名に並ぶ。"""
    import winreg

    names: list[str] = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as k:
                i = 0
                while True:
                    names.append(winreg.EnumValue(k, i)[0])
                    i += 1
        except OSError:
            pass
    return names


def _font_installed() -> bool:
    return _has_font(_registered_fonts(), "BIZ UDPGothic")


def _ensure_derived(work: Path) -> None:
    """template.json があれば、欠けた派生ファイル（prune 済みのもの）を再生成する。無ければ何もしない。"""
    if (work / "template.json").exists():
        from . import lifecycle

        lifecycle.ensure_derived(work)


def _font_note() -> list[str]:
    """BIZ UDPゴシックが未導入のとき、build の notes に足す案内（測定は代替フォントで行われるため）。"""
    if _font_installed():
        return []
    return ["BIZ UDPゴシックが未導入です。代替フォントで測ったので、PowerPoint で折り返しがずれることがあります"]


def doctor_lines() -> list[str]:
    """doctor の出力。標準項目（OS・実行環境・保存先）、固有の依存、版の順。対処は次の行に `→`。"""
    lines = env.lead_lines(full=False)
    lines.append(f"[OK] 仮想環境: {paths.venv_dir()}（ライブラリ・chromium を含む）")
    if _font_installed():
        lines.append("[OK] BIZ UDPゴシック: 導入済み")
    else:
        lines += [
            "[任意] BIZ UDPゴシック: 未導入（計測は代替フォントで行うため、PowerPoint で折り返しがずれる場合がある）",
            "  → BIZ UDPゴシックを導入する（使わなくても動く）",
        ]
    return lines + env.version_lines()


def cmd_doctor(args) -> int:
    lines = doctor_lines()
    print("\n".join(lines))
    return 3 if any(x.startswith("[NG]") for x in lines) else 0


def cmd_init(args) -> int:
    from . import initdir

    try:
        r = initdir.init(Path(args.workdir), template_path=args.template, force=args.force, footer=args.footer)
    except (FileExistsError, ValueError, OSError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def _template_store(action) -> int:
    """テンプレートの置き場の操作。使えないものは 2、同じ名前があれば 4。結果は JSON で出す。"""
    from . import templatestore

    try:
        result = action(templatestore)
    except FileExistsError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 4
    except (ValueError, OSError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_template_import(args) -> int:
    return _template_store(lambda s: s.import_template(args.path, args.name, args.force))


def cmd_template_list(args) -> int:
    return _template_store(lambda s: s.list_templates())


def cmd_template_remove(args) -> int:
    return _template_store(lambda s: s.remove_template(args.name))


def cmd_pptx_extract(args) -> int:
    from . import pptx_extract

    try:
        text = pptx_extract.extract(Path(args.pptx))
    except pptx_extract.ExtractError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(text)
    return 0


def _no_cfg(work: Path) -> int | None:
    """作業フォルダに template.json がなければ案内を出して 2 を返す（あれば None）。"""
    if (work / "template.json").exists():
        return None
    print(f"エラー: {work} に template.json がありません（成果物の元データが見つかりません）", file=sys.stderr)
    return 2


def _load_cfg(work: Path):
    from . import design_colors, template

    cfg = paths.read_cfg(work)
    return cfg, template.TemplateInfo.from_dict(cfg["info"]), design_colors.load_for(work, cfg)


def _backgrounds(work: Path, cfg: dict, info) -> dict[str, str]:
    from . import template

    return template.background_colors(work / cfg["template"], info)[0]


def _load_rules(work: Path):
    from . import rules

    return rules.load(work)


_LEADING_COMMENTS = re.compile(r"\A\s*(?:<!--.*?-->\s*)*", re.DOTALL)


@contextlib.contextmanager
def _as_page(html: Path, work: Path):
    """`<section` で始まる断片（slides/NN-Rk.html）は、作業フォルダの theme.css・base.css を読む html に包んで返す。
    包んだ一時ファイルは作業フォルダの外に置き、検査後に消す。`<html>` を持つ html はそのまま返す。"""
    text = paths.read_text(html)
    if not _LEADING_COMMENTS.sub("", text).startswith("<section"):  # 見本を写した断片は、先頭に用途のコメントがある
        yield html
        return
    from . import measure

    measure.check_not_unc(work)  # 包んだページは作業フォルダの外に置かれ、測定側の検査が work を見ないので、ここで断る
    base = work.resolve().as_uri() + "/"  # 断片の中の相対パス（icons/・material/）も作業フォルダから引く
    wrapped = (
        f'<!doctype html><html lang="ja"><head><meta charset="utf-8">{paths.CSP_FILE}<base href="{base}">'
        '<link rel="stylesheet" href="theme.css"><link rel="stylesheet" href="base.css">'
        '<script src="chart-preview.js" defer></script></head><body>' + text + "</body></html>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / html.name
        page.write_text(wrapped, encoding="utf-8")
        yield page


def cmd_check(args) -> int:
    from . import check, measure

    html = Path(args.html)
    if not html.is_file():
        print(f"エラー: {html} がありません", file=sys.stderr)
        return 2
    work = paths.resolve_work(args.workdir) if args.workdir else html.parent
    if code := _no_cfg(work):
        return code
    _ensure_derived(work)  # 設計図の色・rules.json を theme.css へ反映してから測る
    cfg, info, palette = _load_cfg(work)
    with _as_page(html, work) as page:
        model = measure.measure(page)
    violations = check.check_model(model, info, palette, _load_rules(work), _backgrounds(work, cfg, info))
    print(json.dumps(violations, ensure_ascii=False, indent=2))
    return 1 if check.errors(violations) else 0


def _check_writable(out: Path) -> str | None:
    """出力先に書けるかを、測定の前に確かめる。書けなければ案内の文を返す。
    既存の PPTX は追記モードで開いて閉じるだけ（中身を変えない）。
    なければ親フォルダを作り、同じ場所に作った一時ファイルで確かめる（out は作らない）。"""
    hint = "PowerPoint で開いていれば閉じてください。別の名前で出すなら --out を使います"
    try:
        if out.exists():
            with out.open("ab"):
                pass
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = paths.make_tmp(out.parent, ".pptx-maker-check-")
            os.close(fd)
            with contextlib.suppress(OSError):  # 作れたので書ける。ウイルス対策ソフトが掴んで消せなくても誤報にしない
                Path(tmp).unlink()
    except OSError as e:
        return f"{out} に書き込めません（{e}）。{hint}。"
    return None


def cmd_build(args) -> int:
    from . import build, check, lifecycle, measure, preview

    work = paths.resolve_work(args.workdir)
    if code := _no_cfg(work):
        return code
    _ensure_derived(work)
    name = paths.deck_name(work)
    try:
        tkey = paths.temp_key(
            name, work
        )  # 確認用の画像の置き場の名前を、書き出す前に確かめる（作業フォルダごとに分ける）
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    cfg, info, palette = _load_cfg(work)
    html = work / "final.html"
    if not html.exists():
        print("エラー: final.html がありません（先に finalize を実行してください）", file=sys.stderr)
        return 2
    default_out = paths.deck_dir(work) / f"{name}.pptx"
    out = Path(args.out).resolve() if args.out else default_out
    if out.is_dir() or out.suffix.lower() != ".pptx":
        print(f"エラー: --out には .pptx のファイル名を指定してください（{out}）", file=sys.stderr)
        return 2
    if out.exists() and not args.force:
        print(
            f"エラー: {out} は既に存在します。"
            "上書きしてよければ build-overwrite、別の名前で出すなら --out <パス> を付けてください。",
            file=sys.stderr,
        )
        return 4
    if msg := _check_writable(out):
        print(f"エラー: {msg}", file=sys.stderr)
        return 2
    with measure.open_browser() as browser:  # 測定と確認用の画像で Chromium を 1 つだけ起動する
        # 絵（pp-picture）は、ここで画像にする
        model = measure.measure(html, raster_dir=paths.temp_dir(tkey) / "picture", browser=browser)
        violations = check.check_model(model, info, palette, _load_rules(work), _backgrounds(work, cfg, info))
        result = {
            "ok": False,
            "violations": violations,
            "pptx": None,
            "previews": [],
            "removed": [],
            "notes": [*info.notes, *_font_note()],
        }
        if check.errors(violations):
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        footer = args.footer if args.footer is not None else cfg.get("footer")
        stage = out.with_name(f".{out.name}.new.pptx")  # 検査に通ってから out に置き換える（前の完成版を守る）
        try:
            try:
                build.build(
                    model, work / cfg["template"], info, palette, stage, base_dir=work, footer=footer, work_name=tkey
                )
            except ValueError as e:  # 不正な data-chart など。誤ったグラフを黙って出さず、PPTX は書かずに止める
                print(f"エラー: {e}", file=sys.stderr)
                return 2
            violations += check.check_pptx(stage)
            result["violations"] = violations
            if not check.errors(violations):
                stage.replace(out)
                result["pptx"] = str(out)
        finally:
            stage.unlink(missing_ok=True)
        try:
            shots = preview.screenshots(html, paths.temp_dir(tkey) / "preview", browser=browser)
            result["previews"] = [str(p) for p in shots]
        except Exception as e:  # noqa: BLE001  # PPTX は出ている。確認用の画像だけ作れなかったことを知らせる
            result["notes"].append(f"確認用の画像を作れませんでした: {e}")
        result["ok"] = not check.errors(violations)
    if result["ok"]:
        result["removed"] = lifecycle.prune(work)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_clean(args) -> int:
    from . import lifecycle

    work = paths.resolve_work(args.workdir)
    name = paths.deck_name(work)
    try:
        target = lifecycle.clean_temp(name, work)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"cleaned": str(target)}, ensure_ascii=False))
    return 0


def cmd_finalize(args) -> int:
    from . import finalize

    if not args.choices:  # 引数の検査は、作業フォルダに触れる前に行う
        print(
            "エラー: --choices <フォルダ> を指定してください（choices/<NN>.json を含む作業フォルダ）",
            file=sys.stderr,
        )
        return 2
    work = paths.resolve_work(args.workdir)
    if code := _no_cfg(work):
        return code
    _ensure_derived(work)
    try:
        print(finalize.finalize(work, Path(args.choices)))
    except ValueError as e:
        print(f"エラー:\n{e}", file=sys.stderr)
        return 2
    return 0


def cmd_review_page(args) -> int:
    import webbrowser

    from . import candidates, review_page, script_lint

    work = paths.resolve_work(args.workdir)
    if code := _no_cfg(work):
        return code
    _ensure_derived(work)
    try:
        notes: list[str] = []
        page = review_page.build(work, measure=not args.no_measure, notes=notes)
        script = work / "script.md"
        exempt = script_lint.exempt_ids(paths.read_text(script)) if script.is_file() else set()
        warnings = candidates.main_visual_warnings(candidates.collect(work), exempt)
        print(json.dumps({"path": str(page), "warnings": warnings + notes}, ensure_ascii=False))
        if not args.no_open:
            with contextlib.suppress(Exception):  # 開けない環境（CI など）でも review-page は成功にする
                webbrowser.open(page.as_uri())
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_choices_import(args) -> int:
    from . import candidates, choices, design_colors, rulebook

    work = paths.resolve_work(args.workdir)
    if code := _no_cfg(work):
        return code
    try:
        cands = candidates.collect(work)
        valid = {nn: sorted(c) for nn, c in cands.items()}
        text = paths.read_text(args.file)
        color = choices.color_of(text)  # 不正な色は、選択を書く前に断る

        # 配色を、選択より先に書く。失敗しても選択は残らず、同じ JSON を貼り直せる（選択が先だと指紋が変わる）
        def before_write() -> None:
            design_colors.set_colors(work, color["accent"], [color["emphasis"]])

        rulebook.read_reviews(work)  # 判定の記録が壊れていれば、選択を書き換える前に止める
        before = choices.read_state(work)

        def clear_stale(parsed: dict[str, dict]) -> None:
            # 承認し直しで、承認した断片の指紋が前回（旧形式の None を含む）と変わったページは、AI 判定が古い。
            # 選択を書く前に消す（ここで失敗すれば選択は書かれず、同じ JSON を貼り直せる）
            for nn, page in parsed.items():
                if (
                    page["status"] == "approved"
                    and nn in before
                    and before[nn]["status"] == "approved"
                    and choices.frag_of(work, nn) != page.get("frag")
                ):
                    rulebook.clear_reviews(work, page=nn)

        commented = choices.import_text(
            work,
            text,
            valid,
            before_write=before_write if color else None,
            cands=cands,
            on_parsed=clear_stale,
        )
    except (OSError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"comments": commented, **({"color": color} if color else {})},
            ensure_ascii=False,
        )
    )
    return 0


def cmd_choices_resolve(args) -> int:
    from . import choices, rulebook

    work = paths.resolve_work(args.workdir)
    if code := _no_cfg(work):
        return code
    try:
        rulebook.read_reviews(work)  # 判定の記録が壊れていれば、選択を書き換える前に止める
        for nn in choices.resolve(work, args.slides):
            rulebook.clear_reviews(work, page=nn)  # 断片を直したので、そのページの AI 判定は古い。判定し直す
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    return 0


def cmd_lint_script(args) -> int:
    from . import script_lint

    md = paths.read_text(args.script)
    design = Path(args.script).parent / "design.md"  # 同じフォルダの設計図があれば、証拠対応表も検査する（R16）
    problems = script_lint.lint(md, paths.read_text(design) if design.is_file() else None)
    for p in problems:
        print(p)
    for n in script_lint.title_notes(md):  # 題の抜けの案内は、エラーにしない（終了コードに影響しない）
        print(n)
    return 1 if problems else 0


def cmd_rule_report(args) -> int:
    from . import consulting

    work = paths.resolve_work(args.workdir)
    try:
        print(json.dumps(consulting.evaluate(work), ensure_ascii=False, indent=2))
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    return 0


def _reports_errors(fn):
    """入力の不備（ValueError・OSError）を、`エラー: …` と終了コード 2 にするコマンドの飾り。"""

    @functools.wraps(fn)
    def run(args) -> int:
        try:
            return fn(args)
        except (ValueError, OSError) as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 2

    return run


def _rule_home() -> Path:
    try:
        return paths.home_dir()
    except RuntimeError as e:
        raise ValueError(str(e)) from e


def _load_json_file(path) -> object:
    try:
        return json.loads(paths.read_text(path))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} は JSON として読めません: {e}") from e


@_reports_errors
def cmd_rule_list(args) -> int:
    from . import rulebook

    print(json.dumps(rulebook.listing(_rule_home(), args.kind, args.all), ensure_ascii=False, indent=2))
    return 0


@_reports_errors
def cmd_rule_apply(args) -> int:
    from . import rulebook

    ops = _load_json_file(args.file)
    result = rulebook.apply(_rule_home(), ops, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


@_reports_errors
def cmd_rule_review_import(args) -> int:
    from . import rulebook

    n = rulebook.import_reviews(paths.resolve_work(args.workdir), _load_json_file(args.file))
    print(json.dumps({"imported": n}, ensure_ascii=False))
    return 0


@_reports_errors
def cmd_rule_review_list(args) -> int:
    from . import rulebook

    print(
        json.dumps({"reviews": rulebook.read_reviews(paths.resolve_work(args.workdir))}, ensure_ascii=False, indent=2)
    )
    return 0


@_reports_errors
def cmd_rule_review_clear(args) -> int:
    from . import rulebook

    n = rulebook.clear_reviews(paths.resolve_work(args.workdir), args.rule, args.page)
    print(json.dumps({"cleared": n}, ensure_ascii=False))
    return 0


def entry(argv: list[str]) -> int:
    """python -m pptx_maker の入口。依存が足りない仮想環境では、traceback ではなく案内を出す。"""
    from .measure import BrowserLaunchError

    try:
        return main(argv)
    except ModuleNotFoundError as e:
        print(f"必要なモジュールがありません: {e.name}")
        print(
            "専用の仮想環境が壊れているか、依存が足りません。"
            '`python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" doctor` で確認し、'
            "利用者の承認後に `setup --yes`（同じ `--data` 付き）を実行してください。"
        )
        return 3
    except (
        ValueError,
        OSError,
    ) as e:  # 個別に捕まえていない入力の不備（ファイルがない・書けない・テンプレートが消えた等）
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    except BrowserLaunchError as e:
        # 終了コード 1 は検査違反の意味なので、ブラウザを起動できないときは 3（環境の不備）で返す
        print(f"エラー: ブラウザを起動できません: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        if type(e).__module__.split(".")[0] != "playwright":
            raise
        # 起動後の失敗（タイムアウトなど）は、環境ではなく内容が原因のことが多い。setup は案内しない
        print(f"エラー: ブラウザでの測定に失敗しました（内容が原因の可能性があります）: {e}", file=sys.stderr)
        return 2


def _init_args(p) -> None:
    p.add_argument("workdir")
    p.add_argument("--template", default=None, help="利用者の .potx / .pptx")
    p.add_argument(
        "--footer",
        default=None,
        help='左下に出すコピーライトの文字列（例: "© 2026 〇〇"）。省略すると空欄（init-overwrite なら既存の値を残す）',
    )


def _template_import_args(p) -> None:
    p.add_argument("path")
    p.add_argument("--name", default=None, help="登録名。省略するとファイル名（拡張子なし）")


def _build_args(p) -> None:
    p.add_argument("workdir")
    p.add_argument("--footer", default=None)
    p.add_argument("--out", default=None, help="PPTX の出力先（省略すると <出力先>/<成果物名>.pptx）")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="pptx-maker")
    ap.add_argument("--version", action="version", version=f"pptx-maker {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    # 上書き版は別のサブコマンド（権限の許可リストに入れない）。引数は通常版と同じ
    p = sub.add_parser("init")
    _init_args(p)
    p.set_defaults(fn=cmd_init, force=False)
    p = sub.add_parser("init-overwrite", help="空でない作業フォルダを上書きして作り直す（利用者の承認のあとだけ）")
    _init_args(p)
    p.set_defaults(fn=cmd_init, force=True)
    p = sub.add_parser("template-import", help="利用者のテンプレート（.potx / .pptx）を、名前を付けて置き場に登録する")
    _template_import_args(p)
    p.set_defaults(fn=cmd_template_import, force=False)
    p = sub.add_parser(
        "template-overwrite", help="同じ名前の登録済みテンプレートを置き換えて登録する（利用者の承認のあとだけ）"
    )
    _template_import_args(p)
    p.set_defaults(fn=cmd_template_import, force=True)
    sub.add_parser("template-list", help="登録済みのテンプレートの一覧").set_defaults(fn=cmd_template_list)
    p = sub.add_parser("template-remove", help="登録済みのテンプレートを消す（作成済みの成果物には影響しない）")
    p.add_argument("name")
    p.set_defaults(fn=cmd_template_remove)
    p = sub.add_parser("pptx-extract", help="PPTX を読んで Markdown を標準出力に出す（題・本文・表・グラフの数値）")
    p.add_argument("pptx")
    p.set_defaults(fn=cmd_pptx_extract)
    p = sub.add_parser("check")
    p.add_argument("html")
    p.add_argument("--workdir", default=None)
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("build")
    _build_args(p)
    p.set_defaults(fn=cmd_build, force=False)
    p = sub.add_parser("build-overwrite", help="既存の PPTX を上書きして書き出す（利用者の承認のあとだけ）")
    _build_args(p)
    p.set_defaults(fn=cmd_build, force=True)
    p = sub.add_parser("clean")
    p.add_argument("workdir")
    p.set_defaults(fn=cmd_clean)
    p = sub.add_parser("finalize")
    p.add_argument("workdir")
    p.add_argument(
        "--choices",
        default=None,
        help="選択結果。choices/<NN>.json を含むフォルダ（choices/ の親。作業フォルダ）を渡す（必須）",
    )
    p.set_defaults(fn=cmd_finalize)
    p = sub.add_parser(
        "review-page",
        help="案を選ぶページ（review.html）を作る（ブラウザで開く。選択結果は choices-import で取り込む）",
    )
    p.add_argument("workdir")
    p.add_argument(
        "--no-measure", action="store_true", help="案を測らずに作る（R20・R23・R26 は build 時の表示のまま）"
    )
    p.add_argument("--no-open", action="store_true", help="review.html をブラウザで開かない")
    p.set_defaults(fn=cmd_review_page)
    p = sub.add_parser("choices-import", help="選択ページがコピーした JSON のファイルを choices/<NN>.json に取り込む")
    p.add_argument("workdir")
    p.add_argument("--file", required=True, help="コピーした JSON を貼ったテキストファイル")
    p.set_defaults(fn=cmd_choices_import)
    p = sub.add_parser(
        "choices-resolve",
        help="コメントに応えたページのコメントを消し、承認済みなら未承認に戻す（そのページの AI 判定の記録も消す）",
    )
    p.add_argument("workdir")
    p.add_argument("slides", nargs="+", help="スライド番号（2 桁）")
    p.set_defaults(fn=cmd_choices_resolve)
    p = sub.add_parser("lint-script")
    p.add_argument("script")
    p.set_defaults(fn=cmd_lint_script)
    p = sub.add_parser("rule-report", help="鉄板ルールの検査結果を JSON で出す（案の選択ページと自己確認が使う）")
    p.add_argument("workdir")
    p.set_defaults(fn=cmd_rule_report)
    p = sub.add_parser(
        "rule",
        help="ルールの一覧（list）と、追加・編集・無効化などの適用（apply）。保存先は --data の rules/custom.json",
    )
    rule_ops = p.add_subparsers(dest="rule_cmd", required=True)
    q = rule_ops.add_parser("list", help="有効なルールを JSON で出す")
    q.add_argument("--kind", choices=["機械", "AI", "人"], default=None)
    q.add_argument("--all", action="store_true", help="無効なルールも出す")
    q.set_defaults(fn=cmd_rule_list)
    q = rule_ops.add_parser("apply", help="操作の配列（JSON ファイル）を、全部検証してから適用する")
    q.add_argument("--file", required=True, help='[{"op": "add|edit|remove|enable|disable|reset", ...}, ...] の JSON')
    q.add_argument("--dry-run", action="store_true", help="書かずに変更前後だけ返す")
    q.set_defaults(fn=cmd_rule_apply)
    p = sub.add_parser("rule-review-import", help="AI 判定の結果（JSON）を、作業フォルダの rule-review.json に記録する")
    p.add_argument("workdir")
    p.add_argument("--file", required=True, help='{"reviews": [{"rule", "page", "status", "message"}]} の JSON')
    p.set_defaults(fn=cmd_rule_review_import)
    p = sub.add_parser("rule-review-list", help="記録した AI 判定を JSON で出す")
    p.add_argument("workdir")
    p.set_defaults(fn=cmd_rule_review_list)
    p = sub.add_parser("rule-review-clear", help="記録した AI 判定を消す（--rule・--page で絞る。省くと全部）")
    p.add_argument("workdir")
    p.add_argument("--rule", default=None)
    p.add_argument("--page", default=None)
    p.set_defaults(fn=cmd_rule_review_clear)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except paths.LayoutError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
