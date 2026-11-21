---
name: rules
description: pptx-maker の鉄板ルール（コンサル資料の作法）を、対話で一覧し、追加・編集・無効化・有効化・削除・既定に戻す。ルールは全資料共通で、利用者のデータ置き場に残る。「ルールを足したい」「ルールを消したい」「ルールを直したい」「このルールを無効にしたい」「ルールの一覧を見たい」と頼まれたときに使う。資料の作成には使わない（create）。
compatibility: Windows 専用。create と同じ環境（Python・python-pptx）。
disable-model-invocation: true
allowed-tools: 'Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule list *) Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule apply --file * --dry-run)'
---

# pptx-maker rules

`${CLAUDE_PLUGIN_ROOT}` は、このプラグインのフォルダ。コマンドは `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule …` の 2 つだけ。環境が足りず終了コード 3 になったときは、create の 0 章（`${CLAUDE_PLUGIN_ROOT}/skills/create/SKILL.md`）に従う。

ルールは、検査の種類が 3 つある。**機械**（コードが判定。組み込みは検査の実装があり、種類を変えられない。利用者が足せるのは、正規表現で当てるもの）、**AI**（Claude が採点表で判定して記録する）、**人**（利用者が質問に答えて確認する）。組み込みの R01〜R35 は削除できない（無効にする）。カスタムは `C01`・`C02`… の ID で、追加・編集・削除ができる。保存先は `${CLAUDE_PLUGIN_DATA}` の下の `rules/custom.json`（全資料共通。プラグインを更新しても残る。この PC だけの置き場で、プラグインをアンインストールすると消える）。既定の内容は [references/consulting-rules.md](${CLAUDE_PLUGIN_ROOT}/references/consulting-rules.md)。

## 手順（Claude と利用者の対話。選択は AskUserQuestion で聞く）

利用者が操作の途中で「やめる」と言ったら、何も書かずに終わる。

1. **現状を取る**: `rule list --all` を実行し、種類別（機械・AI・人）の件数、無効なルール、上書きのあるルール、カスタムルールを短く伝える（ID・名前・区分・種類の表）。
2. **何をするかを聞く**: 一覧を見る／追加／編集／無効化・有効化／削除／既定に戻す。一覧だけなら、1 で終わる。
3. **必要な項目を、1 回 1〜3 問で順に聞く**。
   - **追加**: 名前 → 種類（機械の正規表現／AI／人）→ 区分（必須／推奨）→ 種類ごとの項目。機械は、検査する場所（`head`＝ヘッドメッセージ、`slide`＝案の断片の文字、`script`＝原稿の本文）・`pattern`（正規表現）・`message`（指摘の文）。AI は `rubric`（採点表。ok・warn・ng の基準と、理由に書く証拠を 3〜5 行）。人は `question`（確認の質問 1〜2 行）。説明（`description`）は省いてよい（名前になる）。一致したら、区分が必須なら ng、推奨なら warn になる。
   - **パターン**: 利用者に正規表現を書かせない。検出したい語や言い回しを聞き、Claude が例（一致する例・しない例）を付けて提案し、利用者が確認する。
   - **編集**: 対象を選んでもらい、変える項目だけ聞く（`name`・`description`・`level`・`kind`・`rubric`・`question`、カスタムは `pattern`・`scope`・`message` も）。組み込みの機械ルールは、`kind` を変えられない（検査の実装が変わらないため）。AI と人は、組み込みでも入れ替えられる（変えた先の `rubric` か `question` も渡す）。
   - **削除**: カスタムだけ。組み込みは、削除できないので、無効にする（disable）ことを案内する。
   - **有効化・無効化・既定に戻す**: 組み込みもカスタムも `enable`・`disable` で切り替える。`reset` は組み込みの上書き（名前・区分などの変更と無効化）を消して既定に戻す操作で、カスタムには使えない（カスタムは `edit` で直す）。
4. **操作の JSON をファイルに書く**: スクラッチパッドなど作業側のテキストファイル（例 `ops.json`）に書く。`${CLAUDE_PLUGIN_DATA}` や `${CLAUDE_PLUGIN_ROOT}` には書かない。形は操作の配列で、1 件が 1 つの操作:
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
5. **変更前後を見せる**: `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" rule apply --file "<ops.json>" --dry-run` を実行する（何も書かれない）。結果 `results` の各操作の `before`・`after` から、変わる項目を表で見せる（add は採番される ID も）。エラー（`エラー: <操作の番号>: <理由>`。1 件でもあれば何も書かれない）は、理由を伝えて 3 に戻る。
6. **確認する**: 操作に `remove`（カスタムの削除）があるときは、先に「削除したカスタムは戻せない（作り直すと別の ID になることがある）」と伝える。そのうえで「この内容で反映しますか」を AskUserQuestion で聞く（反映する／直す／やめる）。承認されたときだけ、`--dry-run` なしで同じ `rule apply --file "<ops.json>"` を実行する（`written` が true）。書き込みは事前承認に入れていないので、権限の確認が出る。取り消しは、組み込みなら `reset`、カスタムの `edit`・`enable`・`disable` なら逆の操作で戻せると伝える。
7. **反映を見せる**: `rule list --all` の該当行を見せる。

## 資料への効き方

有効なルールだけが、`rule-report` と案の選択ページの検査に出る。追加した機械のルールは、次の `rule-report`・`review-page` から効く。AI のルールは、create の 4.1 章で判定して記録するまで `pending`（AI 判定待ち）。人のルールは、案の選択ページで利用者が確認する。
