---
name: rules
description: pptx-maker の鉄板ルール（コンサル資料の作法）を、対話で一覧し、追加・編集・無効化・有効化・削除・既定に戻す。ルールは全資料共通で、利用者のデータ置き場に残る。「ルールを足したい」「ルールを消したい」「ルールを直したい」「このルールを無効にしたい」「ルールの一覧を見たい」と頼まれたときに使う。資料の作成には使わない（create）。
compatibility: Windows 専用。create と同じ環境（Python・python-pptx）。
disable-model-invocation: true
allowed-tools: 'Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule list *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule apply --file * --dry-run)'
---

# pptx-maker rules: 鉄板ルールを管理する

pptx-maker が資料を検査するときに使う「鉄板ルール」（コンサル資料の作法）を、利用者との対話で、一覧・追加・編集・無効化・有効化・削除・既定に戻す。変更は全資料に効く。

`${CLAUDE_PLUGIN_ROOT}` は、このプラグインのフォルダ。コマンドは `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule …` の 2 つだけ（`rule list` と `rule apply`）。環境が足りず終了コード 3 になったときは、create の 0 章（`${CLAUDE_PLUGIN_ROOT}/skills/create/SKILL.md`）に従う。

## 用語
| 用語 | 意味 |
|---|---|
| 機械・AI・人 | ルールの検査の種類。**機械**はコードが判定する（組み込みは検査の実装があり、種類を変えられない。利用者が足せるのは、正規表現で当てるもの）。**AI** は Claude が採点表（`rubric`）で判定して記録する。**人**は利用者が質問（`question`）に答えて確認する |
| 組み込み・カスタム | 組み込みは R01〜R35。削除できないので、無効にする。カスタムは `C01`・`C02`… の ID で、追加・編集・削除ができる |
| 区分 | 必須か推奨か。機械のルールに一致したとき、必須なら ng、推奨なら warn になる |
| 保存先 | `${CLAUDE_PLUGIN_DATA}` の下の `rules/custom.json`。全資料共通で、プラグインを更新しても残る。この PC だけの置き場で、プラグインをアンインストールすると消える。既定の内容は [references/consulting-rules.md](${CLAUDE_PLUGIN_ROOT}/references/consulting-rules.md) |
| 操作の JSON | 変更の内容を、操作の配列にして書いたファイル（手順4）。`rule apply --file` に渡す |

## 全体の流れ
| 手順 | やること | 終わりの目印 |
|---|---|---|
| 1 現状を取る | ルールの一覧を取り、短く伝える | 一覧を伝えた（一覧だけの依頼なら、ここで終わる） |
| 2 何をするかを聞く | 追加・編集・無効化などを選んでもらう | 操作が決まった |
| 3 項目を聞く | 操作に必要な項目を、順に聞く | 項目がそろった |
| 4 操作の JSON を書く | 操作をファイルに書く | ファイルを書いた |
| 5 変更前後を見せる | `--dry-run` で、変わる内容を見せる | 変更前後を見せた |
| 6 確認して反映する | 利用者の承認を得て、書き込む | 反映した（または、やめた） |
| 7 反映を見せる | 反映後の一覧を見せる | 該当行を見せた |

## 守ること

- 利用者が操作の途中で「やめる」と言ったら、何も書かずに終わる。
- 操作の JSON は、スクラッチパッドなど作業側のテキストファイル（例 `ops.json`）に書く。`${CLAUDE_PLUGIN_DATA}` や `${CLAUDE_PLUGIN_ROOT}` には書かない。
- 書き込む `rule apply`（`--dry-run` なし）は、利用者の承認を得たあとだけ実行する。選択は AskUserQuestion（選択肢で質問するツール）で聞く。

## 手順

### 手順1: 現状を取る
目的: 今のルールの状態を、利用者に伝える。

ルールの一覧を、無効なものも含めて取る。
`python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule list --all`
種類別（機械・AI・人）の件数、無効なルール、上書きのあるルール、カスタムルールを短く伝える（ID・名前・区分・種類の表）。

### 手順2: 何をするかを聞く
目的: 利用者がしたい操作を決める。

一覧を見る／追加／編集／無効化・有効化／削除／既定に戻す、のどれかを聞く。一覧だけなら、手順1 で終わる。

### 手順3: 項目を聞く
目的: 操作に必要な項目を、利用者から集める。1 回 1〜3 問で順に聞く。

- **追加**: 名前 → 種類（機械の正規表現／AI／人）→ 区分（必須／推奨）→ 種類ごとの項目。機械は、検査する場所（`scope`。`head`＝ヘッドメッセージ、`slide`＝案の断片の文字、`script`＝原稿の本文）・`pattern`（正規表現）・`message`（指摘の文）。AI は `rubric`（採点表。ok・warn・ng の基準と、理由に書く証拠を 3〜5 行）。人は `question`（確認の質問 1〜2 行）。説明（`description`）は省いてよい（名前になる）。一致したら、区分が必須なら ng、推奨なら warn になる。
- **パターン**: 利用者に正規表現を書かせない。検出したい語や言い回しを聞き、Claude が例（一致する例・しない例）を付けて提案し、利用者が確認する。
- **編集**: 対象を選んでもらい、変える項目だけ聞く（`name`・`description`・`level`・`kind`・`rubric`・`question`、カスタムは `pattern`・`scope`・`message` も）。組み込みの機械ルールは、`kind` を変えられない（検査の実装が変わらないため）。AI と人は、組み込みでも入れ替えられる（変えた先の `rubric` か `question` も渡す）。
- **削除**: カスタムだけ。組み込みは、削除できないので、無効にする（disable）ことを案内する。
- **有効化・無効化・既定に戻す**: 組み込みもカスタムも `enable`・`disable` で切り替える。`reset` は組み込みの上書き（名前・区分などの変更と無効化）を消して既定に戻す操作で、カスタムには使えない（カスタムは `edit` で直す）。

### 手順4: 操作の JSON を書く
目的: 決めた操作を、`rule apply` に渡せる形のファイルにする。

操作の JSON を、手順3 で決めた内容で書く（保存先は「守ること」）。形は操作の配列で、1 件が 1 つの操作:
```json
[
  {"op": "add", "name": "要検討を残さない", "kind": "機械", "level": "必須", "scope": "slide", "pattern": "要検討", "message": "「要検討」が残っています"},
  {"op": "edit", "id": "R13", "set": {"level": "推奨"}},
  {"op": "disable", "id": "R14"},
  {"op": "enable", "id": "R14"},
  {"op": "reset", "id": "R13"},
  {"op": "remove", "id": "C01"}
]
```

### 手順5: 変更前後を見せる
目的: 書き込む前に、変わる内容を利用者に確かめてもらう。

何も書かずに、変更前後を計算する。
`python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule apply --file "<ops.json>" --dry-run`
結果 `results` の各操作の `before`・`after` から、変わる項目を表で見せる（add は採番される ID も）。エラー（`エラー: <操作の番号>: <理由>`。1 件でもあれば何も書かれない）は、理由を伝えて手順3 に戻る。

### 手順6: 確認して反映する
目的: 利用者の承認を得て、ルールを書き込む。

操作に `remove`（カスタムの削除）があるときは、先に「削除したカスタムは戻せない（作り直すと別の ID になることがある）」と伝える。そのうえで「この内容で反映しますか」を AskUserQuestion で聞く（反映する／直す／やめる）。承認されたときだけ、`--dry-run` なしで、同じ操作を書き込む（結果の `written` が true）。書き込みは事前承認に入れていないので、権限の確認が出る。
`python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule apply --file "<ops.json>"`
取り消しは、組み込みなら `reset`、カスタムの `edit`・`enable`・`disable` なら逆の操作で戻せると伝える。

### 手順7: 反映を見せる
目的: 反映の結果を、利用者に見せる。

`rule list --all` の該当行を見せる（手順1 と同じコマンド）。

## 資料への効き方

有効なルールだけが、`rule-report` と案の選択ページの検査に出る。追加した機械のルールは、次の `rule-report`・`review-page` から効く。AI のルールは、create の 4.1 章で判定して記録するまで `pending`（AI 判定待ち）。人のルールは、案の選択ページで利用者が確認する。
