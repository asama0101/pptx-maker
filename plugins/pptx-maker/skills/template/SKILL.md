---
name: template
description: 利用者の PowerPoint テンプレート（.potx / .pptx）を、名前を付けて置き場に登録し、一覧を見る、消す。登録したテンプレートは、create で資料を作るとき、名前で選べる。「テンプレートを登録したい」「テンプレートの一覧を見たい」「登録したテンプレートを消したい」と頼まれたときに使う。資料の作成には使わない（create）。Windows 専用。
compatibility: Windows 専用。create と同じ環境（Python・python-pptx）。
disable-model-invocation: true
allowed-tools: 'Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" template-list) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" template-import *)'
---

# pptx-maker template: PowerPoint テンプレートを管理する

利用者の PowerPoint テンプレート（.potx / .pptx）を、名前を付けて置き場に登録し、一覧を見る、消す。登録したテンプレートは、資料を作るとき（`/pptx-maker:create`）に、名前で選べる。

`${CLAUDE_PLUGIN_ROOT}` は、このプラグインのフォルダ。コマンドはすべて `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" …`。環境が足りず終了コード 3 になったときは、create の 0 章（`${CLAUDE_PLUGIN_ROOT}/skills/create/SKILL.md`）に従う。

## 用語
| 用語 | 意味 |
|---|---|
| 登録名 | 登録したテンプレートの名前。省略するとファイル名（拡張子なし）になる |
| 置き場 | `${CLAUDE_PLUGIN_DATA}` の下の `templates/<名前>.potx`（または `.pptx`）。プラグインを更新しても残る。この PC だけの置き場で、プラグインをアンインストールすると消える |
| 使うレイアウト | テンプレートから使うのは、表紙・本文・裏表紙の 3 つ。名前で探し、見つからない表紙・裏表紙は本文で代える。章扉・目次などの専用レイアウトは使わない（本文で代える） |
| `_template/` | 作成済みの成果物の作業フォルダにある、テンプレートのコピー。登録を消しても、置き換えても影響しない |

## 全体の流れ
| 手順 | やること | 終わりの目印 |
|---|---|---|
| 1 登録する | ファイルを置き場へ登録する | 登録名とパスを伝えた |
| 2 一覧を見る | 登録済みの一覧を表で見せる | 一覧を見せた |
| 3 消す | 選ばれた登録を消す | 消した |
| 4 使い方を伝える | 登録名を `create` で選べると伝える | 伝えた |

利用者の頼みが「登録」「一覧」「削除」のどれかが分からないときだけ、AskUserQuestion（選択肢で質問するツール）で聞く。

## 守ること

- 頼まれた登録・削除以外はしない。置き場のファイルを直接消さない（`template-remove` を使う）。
- テンプレートのファイルの中身を直さない。
- 上書き版の `template-overwrite`（引数は `template-import` と同じ）は、チャットで利用者の承認を得たあとだけ実行する。実行すると権限の確認が出るが、出なくても（許可済みでも）、承認の前には実行しない。
- 削除は元に戻せないので、`template-remove` は事前承認に入れていない。利用者の承認を得たあとの実行で、権限の確認が出る。

## 手順

### 手順1: 登録する
1. 登録するファイルのパス（`.potx` または `.pptx`）を聞く。登録名は、省略するとファイル名（拡張子なし）になる。変えたいときだけ聞く。
2. ファイルを置き場へ登録する。
   `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" template-import "<パス>" [--name "<登録名>"]`
   - 成功（終了コード 0）: 出力の `name`・`path` を伝える。
   - 終了コード 2: 標準エラーのメッセージを、そのまま利用者に伝える。何も登録されていない。拡張子が `.potx`・`.pptx` でない、16:9（13.33×7.5in）でない、本文のレイアウト（タイトルと本文の領域があるもの）がない、名前に使えない文字がある、ファイルが開けない、のどれか。
   - 終了コード 4: 同じ名前が既にある。「置き換える」か「別の名前にする」かを聞く。黙って置き換えない。置き換えるときは、承認を得たあとだけ `template-overwrite` を実行する（守ること）。

### 手順2: 一覧を見る
登録済みの一覧を出す。
`python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" template-list`
出力の `name`・`format`・`path` を表にして見せる。空の配列なら、「登録はない」と伝える。

### 手順3: 消す
1. 手順2 の `template-list` を実行して一覧を見せ、消す名前を選んでもらう。
2. 「作成済みの成果物には影響しない」と伝え、消してよいかを確かめる。
3. 登録を消す。
   `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" template-remove "<名前>"`
   終了コード 2 は、その名前がないとき。

### 手順4: 使い方を伝える
登録が済んだら、資料を作るとき（`/pptx-maker:create`）にテンプレートの有無を聞かれるので、そこで登録名を選べると伝える。
