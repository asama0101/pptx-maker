---
name: doctor
description: pptx-maker が動く環境かを点検し、インストール中の版が最新かを確かめる。専用の仮想環境・ライブラリ・chromium・BIZ UDPゴシックの有無と、GitHub をマーケットプレイスに登録していれば新しい版の有無を、項目ごとに伝える。「環境を点検して」「doctor」「最新版か確認して」「動かない原因を調べて」と頼まれたときに使う。資料の作成には使わない（create）。Windows 専用。
compatibility: Windows 専用。Python 3.12 以上。
disable-model-invocation: true
allowed-tools: 'Bash(python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" doctor)'
---

# pptx-maker doctor

環境を変えずに点検して、結果を利用者に伝える。

1. `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" doctor` を実行する。
2. 終了コード 0 なら、出力の行を項目ごとに伝える。
   - `[OK]`: 一言で済ませる。
   - `[任意]`: BIZ UDPゴシック未導入。PowerPoint で折り返しがずれることがあるだけで、使わなくても動く。
   - `[情報]`: プラグインのバージョンの行。かっこの中の文言で伝え方を分ける。
     - 「（最新です）」: 最新と伝える。
     - 「（GitHub のマーケットプレイスに登録していないため、最新かは確認しません）」: 最新かは確認していないと伝える。対処はない。
     - 「（最新のバージョンを確認できませんでした: …）」: 理由と、次の行の対処（ネットワーク・github.com への通信の確認）をそのまま伝える。更新の手順は案内しない。
     - 「（GitHub に v… があります）」: 次の 3 行の更新の手順（`/plugin marketplace update` → `/plugin update` → Claude Code を開き直す）を伝える。
3. 終了コード 3 は、`[NG]` がある（OS・実行環境・保存先、または専用の仮想環境がない・足りない）。出力の `[NG]` の項目と、「→」の対処を伝える。`[情報]` のバージョンの行（2 の伝え方）もここに出る。仮想環境がないときは、出力に BIZ UDPゴシックの行は出ない（導入したあとの `doctor` で出る）。
4. 導入（`setup --yes`）が必要なときは、利用者に「`${CLAUDE_PLUGIN_DATA}` の下に専用の仮想環境と chromium（数百 MB）を入れてよいか」を確かめ、承認を得てから `python "${CLAUDE_PLUGIN_ROOT}/run.py" --data "${CLAUDE_PLUGIN_DATA}" setup --yes` を実行する。
   - ライブラリと chromium の取得に時間がかかる。バックグラウンドで実行して完了の通知を待つ（上限 10 分。超えたら止めて出力を報告する）。
   - 失敗（0 以外の終了コード）したら、出力をそのまま利用者に伝えて止める。自動で再試行しない（原因を直したあと、利用者が頼んだときに 1 回やり直す）。
   - 成功したら、`doctor` をもう一度実行して結果を伝える。
5. 終了コード 2 は、引数の不備（`--data` が置き換わっていない・絶対パスでない、など）。標準エラーのメッセージを伝える。
