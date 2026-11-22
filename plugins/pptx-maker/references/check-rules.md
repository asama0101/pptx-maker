# 検査の rule と直し方

SKILL.md の 6 章から参照する。違反の `rule` ごとの直し方。違反は、`build` の出力 JSON（`ok`・`violations`・`pptx`・`previews` …のオブジェクト）の `violations` と、`check` の出力（違反の配列そのもの）に、`{rule, slide, message, severity}` で出る。`pptxFontMin`・`pptxBounds` は PPTX を作ったあとの検査なので、`build` の出力だけに出る。内容（文言・数字）は変えず、配置・サイズで直す。検査は、はみ出しと重なりを中心に絞ってある（画像の使い方・字数・ダッシュなどの検査はない）。

| rule | 直し方 |
|---|---|
| `overflow` | 文字の枠を広げるか、文章を減らす（枠の高さは、行数 × line-height × 文字サイズ 以上にする） |
| `outOfSlide`・`pptxBounds` | 部品がスライドの外にはみ出している。位置かサイズを直す（`pptxBounds` は書き出した PPTX の検査） |
| `textLost` | `pp-text` の中の文字が PPTX に入らない（**エラー**）。段落は `p`・`div`・`li` で並べ、入れ子の `ul`、`p` と混ざった裸の文字を使わない |
| `overlap` | 位置をずらす。意図的なら両方に `data-overlap` |
| `keepout` | テンプレートのヘッダー・フッターの領域（y 676 以降が標準）を避ける |
| `fontMin`・`pptxFontMin` | 本文 14pt（19px）・注記 10pt（14px）以上にする。表の中の文字は、注記でも 14pt が下限 |
| `shapeKind` | `data-shape` は `rect`・`round`・`ellipse`・`triangle` のどれかにする |
| `colorRange` | 資料全体の色相の系統が基調 1＋強調 2 を超えている。超えた色を基調色の濃淡か強調色に置き換える |
| `colorNeon` | 蛍光色・彩度が高すぎる色。落ち着いた色にする |
| `colorContrast` | 文字と背景のコントラストが 4.5 未満。文字色か背景を変える |
| `chromeSpec` | 題・ヘッドメッセージの大きさ・フォント・寄せが規約と違う。規約（既定 37px・27px・BIZ UDPゴシック・左寄せ）に合わせるか、`rules.json` の `size_px`・`align` で規約を変える（フォントは固定） |

`orphanLine` は警告（`severity: warn`。`build` は止めない。案の選択ページの R20 に出る）: 題・ヘッドメッセージの最終行が 1〜2 字分しかない（文字が 1 つだけ次の行に落ちている）。文を短くするか言い換えて、1 行に収めるか、最終行を 3 字分以上にする。

表の rule は、すべて `severity: error` で、`build` は 1 件でもあれば PPTX を書かない。不正な `data-chart`（型は `bar`・`barh`・`line`・`pie`・`stacked`・`waterfall`、`highlight` は 0 〜 カテゴリ数 − 1、`axis` は `min` < `max`・`major` > 0、ウォーターフォールの累計は 0 以上、カテゴリと系列は空にしない）は、検査の違反ではなく `build` が「エラー: …」で止める（終了コード 2）。`build` の前に見るときは `RUN check "<元データ>/final.html"`（確認用の画像 `previews` は `final.html` の撮影で、PPTX の実描画ではない）。

## build の出力

出力は `ok`・`violations`・`pptx`・`previews`・`removed`・`notes`。`previews` は `final.html` の撮影で、PPTX の実描画ではない。`review.html`・`final.html` などの派生ファイルは、`build` が成功したときに消えている（元データは消さない）。

`build-overwrite` は、承認を得たあとだけ実行する。実行すると権限の確認が出るが、出なくても（許可済みでも）、チャットで承認を得る前には実行しない。

## 直す手順（build の終了コード 1）

検査違反（色の `colorRange`・`colorNeon`・`colorContrast` を含む）。該当ページの断片の配置・サイズだけを直し（案は選び直させない）、`review-page` をやり直す。直したページは承認前（保存済み）で出るので、利用者に新しい断片を見て承認し直してもらい（5 章の 2 から）、`choices-import` → `finalize` → `build`。直さなかったページの承認は残る。承認し直したページの AI 判定は `choices-import` で消えるので、`finalize` が「AI 判定が済んでいません」で止まったら、4.1 で判定し直す。文言や構成を変えないと直らないときだけ利用者に確かめる。直し方は上の表。

## build の終了コード 2

`エラー:` のメッセージで対処を分ける。
- 「書き込めません」: 利用者に、その PPTX を PowerPoint で閉じてもらい、同じコマンドをやり直す（断片は直さない）。
- 「final.html がありません」: 6 章の 1 の `finalize` からやり直す。
- 「--out には .pptx のファイル名を指定してください」: `--out` を直してやり直す。
- 「template.json がありません」「一時フォルダの名前が不正です」: `"<元データ>"` の指定が違う。冒頭の `<元データ>` の形と照らして伝え、止まる。
- 不正な `data-chart`: 断片を直し、終了コード 1 と同じく `review-page` をやり直して、利用者に承認し直してもらう（5 章の 2 から）。
- 「ブラウザでの測定に失敗しました」（タイムアウトなど）: 重い SVG など、断片の内容を疑う。
