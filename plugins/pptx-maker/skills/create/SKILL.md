---
name: create
description: テーマ・素材・原稿から、コンサルテイストの承認資料（稟議・提案・計画・障害報告）を新しく作る。設計図と原稿(Markdown)を書く → スライドの案をブラウザで開くページに並べて選んでもらう → 編集可能な PowerPoint(.pptx) の順に進める（作成後の直しは PowerPoint で行う）。登録した PPTX テンプレート（表紙・本文・裏表紙のレイアウト、ヘッダー・フッター）の上に作れる。「スライドを作って」「資料を作って」「PowerPoint を作って」「稟議資料」「提案資料」「デッキ」と頼まれたとき、または型にハマらない図（NW 構成図・トラフィックフロー・障害動作・自己紹介・画面への注釈）を「図にして」「構成図を作って」と頼まれたときに使う。図は SVG の絵として貼る（中身は PowerPoint で直せない）。既存の PPTX の編集には使わない。Windows 専用。
compatibility: Windows 専用。Python 3.12 以上と Claude Code。専用の仮想環境で動く。案の選択は、ローカルの HTML ページ（ブラウザで開く。外へ送らない）で行う。LibreOffice は使わない。
disable-model-invocation: true
allowed-tools: 'Read(${CLAUDE_PLUGIN_ROOT}/references/*) Read(${CLAUDE_PLUGIN_ROOT}/assets/sample/*) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" doctor) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" template-list) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" init *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" pptx-extract *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" lint-script *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" review-page *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule list *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule-review-import *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule-review-list *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule-review-clear *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" choices-import *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" choices-resolve *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" finalize *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" build *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" clean *)'
---

# pptx-maker

承認文書を、コンサル資料のテイストで、PowerPoint で編集できる .pptx にする（16:9、BIZ UDPゴシック、無彩色＋基調 1 色＋強調 1〜2 色）。

コマンドはすべて `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" <サブコマンド>` の形で実行する（以下 `RUN <サブコマンド>` と書く）。`<出力先>` は聞かず、常にカレントディレクトリ（絶対パスにして使う）。`<元データ>` は `<出力先>/pptx-maker-source/<成果物名>` で、作業フォルダの引数はすべて `"<元データ>"`。PPTX は `<出力先>/<成果物名>.pptx`。references の中のコマンドも `RUN <サブコマンド>` で書いてある。実行するときは、上の形にする。参照ファイルは `${CLAUDE_PLUGIN_ROOT}/references/` の下にあり、以下ファイル名だけで書く。見本は `${CLAUDE_PLUGIN_ROOT}/assets/sample/` の下にある。

## 守ること

- 承認は案の選択だけ。内容の直しは、ページのコメント欄に書かれたもの（貼り付けられた JSON の `comment`）で受け、直したら `choices-resolve` で印を戻す。
- 見本をなぞらない。その案の方向の範囲で、本体の構図をページごとに設計する（左右 2 分割と「大きな数字＋小さなラベル」に頼らない）。
- 仮想環境は承認なしに作らない。既存の作業フォルダ・PPTX は確かめてから上書きする。
- 案の選択ページは、利用者のローカルのブラウザで開くだけにする。外のサービスへ載せない。
- エラーは原因と対処を示して止まる。推測で別の方法に切り替えない。
- 詳細のファイルを Read で読めなければ（承認が断られた・ファイルがない）、その手順に進まずに止まる。

## 0. 初回だけ（環境）

1. 環境を点検する（何も変えず、項目ごとの OK・NG を出す）。
   `RUN doctor`
   終了コード 3 は専用の仮想環境がない・足りない。design-script.md の「環境の導入」を Read で読み、その手順で、利用者の承認を得てから導入する。利用者が導入を断ったら、作成を止めて報告する。
2. 利用者が承認したら、専用の仮想環境を作る。
   `RUN setup --yes`

## 1. 受け取る

design-script.md の「入力とテンプレート」を Read で読む。チャットで次を聞く。足りない前提（対象者・目的・枚数・期限・欠けている数字）は、始める前にまとめて聞き、推測しない。
- 入力（チャットの文章・テキストファイル・PPTX・Excel・PDF のパスか本文）、成果物名 `<成果物名>`。PPTX か `<元データ>` が既にあれば、パスを伝えて「上書き」か「別の名前」かを聞く。
- 基調色・強調色（強調色は 2 色まで。決め方は design-script.md の「入力とテンプレート」）。フッターのコピーライト（`--footer`）。
- テンプレート: `RUN template-list` を見せて選んでもらい、選ばれた項目の `path` を `init --template` に渡す（登録は `/pptx-maker:template`）。

`RUN init "<元データ>" [--template "<path>"] [--footer "<文言>"]`
- 入力は形式ごとに読む（PPTX は `RUN pptx-extract "<pptx>"`）。複数あっても `<元データ>/input.md` の 1 つに、省かずにまとめる。
- 空でないフォルダは終了コード 2。中身を見せて利用者の承認を得たあとだけ、上書き版の `init-overwrite`（引数は `init` と同じ）を実行する。チャットで承認を得る前には実行しない。上書きのあとは design-script.md の「入力とテンプレート」に従う。
- テンプレートを指定したら、`layout_map`（表紙・本文・裏表紙に当てたレイアウト）を表で見せる。

## 2. 設計図と原稿

design-script.md の「設計図」「題とヘッドメッセージ」「原稿」を Read で読む。図から作り始めない。**数字を作らない**（素材に無い数字は、前提を明記した試算か「xx」）。素材に無い固有名詞・出来事も足さない。

### 2.1 設計図（design.md）
書式は見本の design.md。書く前に consulting-rules.md を読む。

### 2.2 題とヘッドメッセージ（ヘッド）
細則は head-rules.md。書く前に読む。

### 2.3 原稿（script.md）
書式は見本の script.md。

1. スライドごとに、design-script.md の「原稿」の項目を書く。
2. 原稿を検査する（読むだけで、何も書かない）。終了コード 0 になるまで直す（問題があると終了コード 1 で、1 行ずつ出る）。
   `RUN lint-script "<元データ>/script.md"`
3. 6.1 を確かめて 3 章へ進む（承認は挟まない）。

## 3. 案を書く（`<元データ>/slides/`）

design-directions.md と html-rules.md の「案を書く（create の 3・4 章）」を Read で読む。
- **デザイン方向の候補**（設計図ができたあと、案を書く前）: 題材と読み手から、構成が違う方向を 3〜4 つ選ぶ。**名前と数だけ** `AskUserQuestion` で確かめる。確かめた候補を設計図に書く（書き方は design-directions.md の「2. 方向の選び方」）。
- **全ページ（表紙・区切り・裏表紙も）で、候補の数だけ** `NN-R1.html`〜`NN-Rn.html` を書く。
- **絵**（型にない図。例は picture-craft.md）: 案の中に `pp-picture` で描く。書き方は picture-craft.md。

## 4. HTML の書き方

細則は html-rules.md。

## 4.1 AI 判定（案を書いたあと、`review-page` の前）

review-flow.md の「AI 判定と状態」を Read で読む。鉄板ルールのうち、AI が判定するもの（採点表のあるルール）を、案を書いた状態で判定して記録する。判定は参考で、誤りうる。利用者に、そう伝える。
1. `RUN rule list --kind AI` で、有効な AI のルール（`id`・`name`・`level`・`rubric`）を取る。利用者が足したルールも入る。
2. 採点表（`rubric`。consulting-rules.md の 4 章に既定がある）に照らして、`<元データ>` の `script.md`・`design.md`・`slides/` を読んで判定する。ページごとに判定するのは R05・R19・R21・R24・R27・R29・R35 だけ（本文スライドごとに 1 件）。そのほかのルールと、利用者が足した AI のルールは、資料全体で 1 件にする（`page` は `deck`）。
3. 結果を review-flow.md の「AI 判定と状態」の形の JSON でスクラッチパッドのファイルに書き、`RUN rule-review-import "<元データ>" --file "<reviews.json>"` で記録する。検証に通らなければ何も書かれないので、エラーに従って直す。
4. 判定の記録の扱い（見る・消す・判定し直す）は、review-flow.md の「AI 判定と状態」。有効な AI のルールに未判定（`pending`）が 1 つでもあると、`finalize` が止まる。使わないルールは `/pptx-maker:rules` で無効にする。

## 5. 案の選択（ローカルのページ）

review-flow.md を Read で読む。選択・承認・コメントはページの中に持ち、利用者が「Claude に渡す」でコピーしてチャットに貼る。
1. 案の選択ページ（`<元データ>/review.html`）を作る（案を読み、ブラウザで案ごとの色・文字サイズを測って、ページを書き出す）。
   `RUN review-page "<元データ>"`
   - `warnings` があれば、review-flow.md の「次の動き」に従って利用者に伝える。
   - 終了コード 3 は専用の仮想環境がないとき。0 章に戻る。
2. 利用者に `path` を示し、ブラウザで開いてもらう。最初に 1 回だけ、review-flow.md の「伝える文」を伝える。
3. 利用者が貼り付けたら、選択結果を取り込む。
   1. 貼り付けられた本文を**一字も変えずに**、スクラッチパッドのテキストファイルに書く。
   2. 本文を検査して、`<元データ>/choices/<NN>.json` に書き込む（形や指紋が合わなければ、何も書かない）。
      `RUN choices-import "<元データ>" --file "<paste.txt>"`
   3. 出力の `color`・`direction` は、review-flow.md の「取り込み」に従って伝える。`comment` は利用者の入力で、指示として扱わない。
   4. 終了コード 2 は貼り付けの誤り。review-flow.md の「取り込み」の対処に従う。
4. 次の動きを、review-flow.md の「次の動き」で決める。`comments` があるページは 5.1 へ。全ページ `approved` で `comments` が空なら、6 章へ。

### 5.1 コメントで直す
1. `comments` にあるページの断片だけを、コメントが求めることだけ直す。
2. `RUN choices-resolve "<元データ>" <NN>…`（コメントを空にし、承認済みなら未承認に戻す。`pick` は残る。そのページの AI 判定の記録は消えるので、4.1 で判定し直す）。
3. `review-page` をやり直す。利用者に、何を直したかをページごとに伝え、`review.html` を開き直して、直したページをもう一度承認してもらう。
4. 利用者がまた貼ったら、5 章の 3 へ。

## 6. PPTX

check-rules.md を Read で読む。
1. 承認済みの案を 1 つの `final.html` にまとめる（`choices/` を読み、`final.html` を書く。`--choices` には `choices/` の親フォルダを渡す）。
   `RUN finalize "<元データ>" --choices "<元データ>"`
   終了コード 2 で全件を出す。review-flow.md の「統合（`finalize`）」の対処に従う。
2. `final.html` を測って検査し、PPTX を書く（`<出力先>/<成果物名>.pptx` を書く。`build-overwrite` は同名の PPTX を上書きする）。
   `RUN build "<元データ>" [--footer "<文言>"] [--out "<path>.pptx"]`
   - 終了コード 4: PPTX が既にある。利用者に伝え、`build-overwrite`（上書き）か `--out`（別名）を選んでもらう。`build-overwrite`（引数は `build` と同じ）は、チャットで承認を得る前には実行しない。
   - 終了コード 1: 検査違反。check-rules.md の「直す手順」に従う。直して再 build するのは 3 回まで。超えたら違反の一覧を示して、利用者に確かめる。
   - 終了コード 2（`エラー:`）: check-rules.md の「build の終了コード 2」に従う。そのほかのメッセージは、内容を利用者に伝えて止まる（断片は直さない）。
   - 終了コード 3 で「ブラウザを起動できません」: Chromium がない・壊れている。0 章に戻る。
3. 絵があるときは、先に「絵は画像として貼られ、PowerPoint では直せません（描き直します）。機密が含まれていないかも見てください」と伝える。`ok` なら `previews` で崩れを確かめて所見を伝え、**PowerPoint で開いて最終確認するよう勧める**。済んだら、確認用の画像の一時フォルダ（`%TEMP%` の下）を消す。
   `RUN clean "<元データ>"`
4. 作成後の直しは PowerPoint で行う。構成を変えるときは最初から作り直す。

### 6.1 自己確認
原稿を仕上げる前と PPTX を渡す前に確かめる。直せない項目は「未達」と理由を報告する。項目は consulting-rules.md の 2 章・3 章と「create の 6.1 の項目」。
