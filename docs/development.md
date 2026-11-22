# 開発者向けの情報

pptx-maker（v0.1.0）の内部構造・コマンド・テストの説明。利用者向けの説明は [README.md](../README.md)。

## 依存関係

`python run.py --data <絶対パス> doctor`（`run.py` は `plugins/pptx-maker/` にある。スキルの中では `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" doctor`。置き場は環境変数 `PPTX_MAKER_HOME` でも指定でき、そちらが優先される）で、専用の仮想環境の状態を項目ごとの OK/NG で確認できる。

| 区分 | 内容 |
|---|---|
| 必須 | Windows、Python 3.12 以上、Claude Code。`python` が PATH にあること |
| 必須 | **専用の仮想環境**（`<置き場>\venv`。`python-pptx==1.0.2`・`playwright==1.52.0`・`pymupdf==1.28.2`・`lxml==6.1.3`。すべて `==` で固定）。`python run.py --data <絶対パス> setup --yes` で、利用者の承認後に作る。Playwright の chromium（数百 MB）は共有の場所（既定は `%LOCALAPPDATA%\ms-playwright`）に入る |
| 推奨 | BIZ UDPゴシック。未導入だと計測が代替フォントになり、PowerPoint と折り返しがずれることがある |
| 最終確認 | Microsoft PowerPoint（確認用の画像は HTML の撮影で、PPTX の実描画ではない） |

LibreOffice と Playwright MCP は使わない。依存のハッシュ固定は見送っている（Python と CPU の組み合わせが多く、更新の負担が大きいため）。`probe-cache.json`（置き場の下）には `schema_version` を入れている。

## 流れ

成果物は利用者が決めた出力先に置く。

```
<出力先>/
  <成果物名>.pptx
  pptx-maker-source/<成果物名>/   元データ: design.md・script.md・slides/・template.json・material/ など
```

1. チャットで入力・成果物名を受け取り（出力先は聞かず、常にカレントディレクトリ）、`init` で作業フォルダを作る。
2. `design.md` → `script.md`（`lint-script`）。人の承認はない。
3. `slides/` に断片を書く。全ページ `NN-R1.html`〜`NN-R3.html`（2〜3 案。主役の種類が違う案）。`assets/components/` の型は見本。
4. `review-page` が `review.html` を作る。利用者がローカルのブラウザで開き（外へ送らない）、1 ページごとに案を選び、コメントし、承認する。状態はページの中にあり、「Claude に渡す」が選択結果の JSON（`base`＝`choices.stamp`、`check`＝`pages` の FNV-1a）をクリップボードにコピーする。
5. 利用者がチャットに貼り、Claude が本文をファイルにして `choices-import` で `choices/<NN>.json` にする（`base`・`check` が合わなければ全件エラーで何も書かない）。コメントのあるページは断片だけ直して `choices-resolve` でコメントを空にし（承認済みなら `saved` に戻す。そのページの AI 判定の記録も消えるので判定し直す）、`review-page` をやり直して再承認してもらう。承認し直しで指紋が前回（旧形式の `frag` なしを含む）と変わると、そのページの AI 判定も承認を書く前に消える（`pick` だけの変更や、旧形式を同じ断片で承認し直したときも消える。安全側で、判定し直す手間が出るだけ。承認 → 保存済みでは消えない）。加えて、ページごとの判定には記録時のそのページの全案の指紋 `frag`（`choices.page_frag`）が付き、`consulting.evaluate` は今の指紋と違う判定を `pending`（「断片が変わったため、判定し直してください」）にする（承認の経路によらない。`frag` のない古い記録と `deck` の判定は有効のまま。画像・`theme.css` の変更は検知しない。残る限界: `frag` は `rule-review-import` を実行した時点の断片に付くので、判定したあとで断片を編集し、判定し直さずに同じ内容で上書きすると有効になる（仕組みでは防げない。判定は、断片を直したあとの全案で行う）。`collect` が通らない間（断片の名前が読めない・案の数が合わない等）と、断片のないページには、ページ単位の判定を記録できない（`rule-review-import` が終了コード 2 で断る）。`deck` だけの記録は、断片を見ずに通る。`pending_ai`（`finalize` のエラー文）は、断片が変わって戻ったものに「（断片が変わった）」を付ける）。指紋が見るのは選ばれた断片の HTML だけで、画像ファイル・`theme.css`・`base.css`・`icons/`・選ばれなかった案・`script.md`・`final.html` 作成後の変更は検知しない。`collect` の整形（`svgids.uniquify` など）を変えると全ページの指紋が変わり、承認し直しが要る。`review-page` は、指紋が今の断片と合わない承認済みを「保存済み」として埋め込む。選択ページは各案の指紋を埋め込み、「承認」を押したときのページの状態に、見ている案の指紋 `fr` を持たせて、「Claude に渡す」の `pages[nn].fr`（承認のページだけ。`check` に含まれる）に入れる。`choices-import` は、承認のページの `fr` がない・今の断片の指紋と違うときは全件エラーで何も書かない（断片を直したあとの古いタブ・古いページからの承認を断る）。ページの JS は、localStorage から復元した承認の `fr` が今の指紋と違えば「保存済み」に落とす。`finalize --choices <作業フォルダ>` は全ページ承認済み・`comment` が空・原稿の全スライドに断片がある・AI 判定が記録済み・承認した断片の指紋（`choices-import` が承認ページに `frag` として書く）が今の断片と同じことを確かめて `final.html` を作る。
6. `build` が測定 → 検査 → PPTX の書き出し → 再検査。
7. 直しは PowerPoint で行う。構成を大きく変えるときは最初から作り直す。

絵（型に当てはまらない図）は create スキルの 3 章と `references/picture-craft.md`。`<div class="pp-picture" data-alt="…">` の中のインライン SVG で描き、`build` が Chromium で絵の範囲だけを透過・3 倍の PNG にして貼る。部品は `assets/pictures/parts.svg`、見本 5 種は `assets/components/pictures/`、作法は `references/picture-craft.md`。

## 部品

`plugins/pptx-maker/assets/components/` に 16 本: `layouts/`（`cover`・`closing`・`text`）、`charts/`（`bar`・`hbar`・`line`・`pie`・`stacked`・`waterfall`）、`tables/`（`options`・`actions`）、`pictures/`（5 種）。デザイン違い（`-d2`・`-d3`）はない。ほかのページは自由設計で、指針は `references/html-rules.md` の「自由設計（R）の指針」。アイコンは `assets/icons/` の 30 個（`references/icons.md`）で、ほかは SVG でその場で描く。型を足したら `components.md`・`patterns.md` も更新し、`tests/test_components.py` を通す。

## ファイルの置き場所

| 場所 | 内容 |
|---|---|
| `.claude-plugin/marketplace.json` | 配布の定義（マーケットプレイス名 `pptx-maker`） |
| `plugins/pptx-maker/` | `.claude-plugin/plugin.json`、`run.py`、`requirements.txt`、`skills/`（`create`・`doctor`・`template`・`rules`）、`pptx_maker/`（Python）、`references/`、`assets/`（`components/`・`web/`・`icons/`・`template/standard.potx`・`sample/`・`pictures/parts.svg`） |
| `tests/` | 単体・通しのテスト |
| `%TEMP%\pptx-maker\<成果物名>-<ハッシュ 8 桁>\` | 確認用の画像など一過性のもの |

## コマンド

普段はスキルが呼ぶ。`python run.py --data <絶対パス> <コマンド>`（`--data` は先頭に置く。`PPTX_MAKER_HOME` を設定すれば省ける。どちらもなければ終了コード 3）。`<元データ>` は作業フォルダで、`<出力先>/<成果物名>.pptx` のパスを渡しても同じ作業フォルダに解決される（旧配置は終了コード 2）。

| コマンド | 内容 |
|---|---|
| `doctor` / `setup --yes` | 環境の診断 / 仮想環境と chromium の導入（承認後） |
| `init <元データ> [--template …] [--footer …]` | 作業フォルダを作る。空でないときは終了コード 2。上書きは同じ引数の `init-overwrite` |
| `template-import / template-overwrite / template-list / template-remove` | 利用者のテンプレートの登録・一覧・削除（使うレイアウトは表紙・本文・裏表紙） |
| `pptx-extract <pptx>` | PPTX を読んで Markdown を標準出力に出す（題・本文・表・グラフの数値。ノート・非表示スライド・画像・SmartArt は読まない。読めない PPTX は終了コード 2） |
| `lint-script <script.md>` | 原稿の書式・題・ヘッドメッセージを検査する |
| `review-page <元データ>` | 案を選ぶ `review.html` を作る（ローカルのブラウザで開く。ローカルの画像は data URI に埋め込む。12 MiB まで。`--no-measure` で案を測らない） |
| `choices-import <元データ> --file …` / `choices-resolve <元データ> <NN>…` | ページがコピーした選択結果の取り込み（`base`・`check` が合わなければ全件エラーで何も書かない）/ コメントに応えたページのコメントを空にし、承認済みなら `saved` に戻す。そのページの AI 判定の記録も消す |
| `rule list [--kind …] [--all]` / `rule apply --file ops.json [--dry-run]` | 有効なルールの一覧 / 追加・編集・無効化などの適用（全部検証してから書く。保存先は置き場の `rules/custom.json`。対話は `/pptx-maker:rules`） |
| `rule-report <元データ>` | 鉄板ルールの検査結果を JSON で出す |
| `rule-review-import` / `rule-review-list` / `rule-review-clear` | AI 判定を作業フォルダの `rule-review.json` に記録する / 記録を見る / 消す（`--rule`・`--page` で絞る） |
| `finalize <元データ> --choices <dir>` | 全ページ承認済みの選択結果から `final.html` を作る（`<dir>` は `choices/` の親）。有効な AI ルールの判定が未記録（`pending`）だと、承認が済んでいても終了コード 2 で止まる（`rule-review-import` で記録するか、`/pptx-maker:rules` で無効にする。原稿のスライドに断片がないときも止まる。承認のあとで断片が変わったときと、承認の記録に断片の指紋がない旧形式のときも止まるので、`review-page` をやり直して承認し直す。断片がないスライドの検査は `script.md` がなければ行わない。指紋の検査は `script.md` がなくても動く） |
| `check <final.html>` | 体裁を検査する |
| `build <元データ> [--footer …] [--out …]` | PPTX を書き出す。出力先に同名の PPTX があれば終了コード 4。上書きは同じ引数の `build-overwrite`。検査エラーは終了コード 1、入力の不備は 2 |
| `clean <元データ>` | 一時フォルダの確認用の画像を消す |

## 自動検査

`build` が調べる検査（PPTX を作るとき。1 件でもあると PPTX は作られない）。

| 検査 | rule | 内容 |
|---|---|---|
| 色 | `colorRange`・`colorNeon`・`colorContrast` | 資料全体で、無彩色＋基調 1 色＋強調 1〜2 色の範囲を超えている。蛍光色。文字のコントラストが 4.5 未満 |
| 題・リードの文字 | `chromeSpec` | 題・リードの大きさ・フォント・寄せが規約（`rules.json` で変更可）と違う |
| はみ出し | `overflow`・`outOfSlide`・`pptxBounds` | 文字が枠に収まらない。部品がスライドの外に出ている（`pptxBounds` は書き出した PPTX で調べる） |
| 重なり | `overlap` | 部品どうしが意図せず重なっている |
| 文字の欠け | `textLost` | HTML の書き方のせいで、文字が PPTX に入らない |
| ヘッダー・フッターの領域 | `keepout` | テンプレートのヘッダー・フッターの領域に部品が入っている |
| 文字の小ささ | `fontMin`・`pptxFontMin` | 本文 14pt 未満、注記 10pt 未満（`pptxFontMin` は書き出した PPTX で調べる） |
| 図形の種類 | `shapeKind` | `data-shape` が `rect`・`round`・`ellipse`・`triangle` のどれでもない |

`build` が `check_model`（測ったモデル）と `check_pptx`（できた PPTX）で検査する。ルールは `overflow`・`overlap`・`textLost`・`keepout`・`fontMin` と、`outOfSlide`・`shapeKind`・`pptxBounds`・`pptxFontMin`（`references/check-rules.md`）。不正な `data-chart` は `build` が `エラー:` で止める。`lint-script` は原稿の書式と題（20 字以内の名詞句）、ヘッドメッセージの規則、論点の個数を検査する。利用者が書くファイルは UTF-8（BOM 付きも可）。

古い作業フォルダは `base.css`・`theme.css`・`chart-preview.js` が `init` 時の写しなので、プラグイン側の更新を反映するには `init-overwrite` をやり直す。v1.x の作業フォルダ（`answers-*.md`・`-d2` の断片・`NN-R.html` など）は未対応で、`finalize`・`review-page` が旧い名前を挙げて止まる。

## テスト

リポジトリのルートで、専用の仮想環境の Python を使って実行する。ブラウザを使うテストには `slow` マークが付き、`-m "not slow"` で除ける。

    python plugins/pptx-maker/run.py --data <置き場> setup --yes
    "<置き場>\venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
    set PYTHONUTF8=1
    set PPTX_MAKER_HOME=<置き場>
    "<置き場>\venv\Scripts\python.exe" -m pytest
    "<置き場>\venv\Scripts\python.exe" -m ruff check .
    "<置き場>\venv\Scripts\python.exe" -m ruff format --check .
