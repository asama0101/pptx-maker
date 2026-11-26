"""案を選ぶページの生成。`<作業フォルダ>/review.html` を書く（利用者がローカルのブラウザで開く）。

ページごとに 1 枚のカード（`id="pg-NN"`）に、選んだ案を大きく、案が複数あれば縮小を並べる。案は Shadow DOM の中に
1280x720 のまま入れて縮小して見せる（`theme.css` はページと各案の shadow root の両方に、`base.css` は shadow root に入れる。
`:root` の変数はページから継承し、`.slide[data-layout=…]` の規則は shadow の中で効く）。選択・承認・コメントはページの
中に持ち、「Claude に渡す」で `{"pptx-maker-review": 1, "pages": {"<NN>": {pick, status, comment}}[, "color": {name, accent, emphasis}]}` をコピーする
（利用者がチャットに貼り、Claude が `choices-import` で `choices/<NN>.json` にする。`color` は配色セットを変えたときだけで、設計図の色になる）。開いたときの状態は、
`choices/<NN>.json` から埋め込む（Claude が直したあとの作り直しで、選択と承認が残る）。"""

import base64
import html as htmllib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from . import candidates, choices, color_sets, consulting, paths

# 題の文字数の上限（左の一覧と見出しに出す）
TITLE_CHARS = 24
# ブラウザで開いて重くならない大きさ（画像は data URI でページに入る）
MAX_PAGE_BYTES = 12 * 1024 * 1024
_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
# 画像を指す属性は <img> の src と、SVG <image> の href・xlink:href。タグは引用符の中の > で止まらない
_IMG_TAG = re.compile(r"<(img|image)\b(?:[^>\x22']|\x22[^\x22]*\x22|'[^']*')*>", re.IGNORECASE)
_DATA_URI = re.compile(r"data:[\w.+/-]+;base64,[A-Za-z0-9+/=]+")
_VARIANT = re.compile(r"\bdata-variant\s*=\s*\x22([^\x22]*)\x22")
_PLACEHOLDER = re.compile(r"__(THEME|DATA|RULES|COLORS|CHART|BASE|STATE|FR|STAMP)__")
# shadow root には body がないので、スライドの文字の書体と色は :host から継承させる
_HOST_CSS = (
    ":host{font-family:'BIZ UDPGothic','BIZ UDPゴシック','BIZ UDGothic','Yu Gothic','Meiryo',sans-serif;"
    "color:var(--text)}"
)
_IMG_ATTR = re.compile(r"(?<![\w:-])((?:xlink:)?href|src)(\s*=\s*)([\x22'])(.*?)\3", re.IGNORECASE | re.DOTALL)

_PAGE = """<title>スライド案の選択</title>
<style>
__THEME__
/* 以下はこのページの枠。変数は --rv- を付け、テーマ側（--bg・--line など）と混ぜない */
:root { --rv-bg:#f2f4f7; --rv-surface:#fff; --rv-fg:#17202b; --rv-mut:#566272; --rv-line:#d8dde4; --rv-acc:#1f3a5f; --rv-acc-ink:#fff; --rv-ok:#18743f; --rv-sel:#a8510a; --rv-soft:#e7ecf3; --rv-ng:#b3261e; --rv-warn:#8a5a00; color-scheme:light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --rv-bg:#0f141a; --rv-surface:#171e27; --rv-fg:#e8edf3; --rv-mut:#9aa7b6; --rv-line:#2a3441; --rv-acc:#8fb2e0; --rv-acc-ink:#0d1722; --rv-ok:#5fd09a; --rv-sel:#f0a85a; --rv-soft:#1f2a38; --rv-ng:#ff8a80; --rv-warn:#f0c060; color-scheme:dark; } }
:root[data-theme="dark"] { --rv-bg:#0f141a; --rv-surface:#171e27; --rv-fg:#e8edf3; --rv-mut:#9aa7b6; --rv-line:#2a3441; --rv-acc:#8fb2e0; --rv-acc-ink:#0d1722; --rv-ok:#5fd09a; --rv-sel:#f0a85a; --rv-soft:#1f2a38; --rv-ng:#ff8a80; --rv-warn:#f0c060; color-scheme:dark; }
body { margin:0; background:var(--rv-bg); color:var(--rv-fg); font:15px/1.6 "BIZ UDPGothic","Yu Gothic UI","Meiryo",system-ui,sans-serif; padding-left:max(16px,env(safe-area-inset-left,0px)); padding-right:max(16px,env(safe-area-inset-right,0px)); padding-bottom:48px; }
button { font:inherit; color:inherit; cursor:pointer; }
#rv { max-width:1240px; margin:0 auto; }
.rvtop { position:sticky; top:0; z-index:20; background:var(--rv-bg); padding:14px 0 10px; border-bottom:1px solid var(--rv-line); display:flex; gap:12px 20px; align-items:center; flex-wrap:wrap; justify-content:space-between; }
.rvtop h1 { font-size:19px; margin:0; }
.rvprog { display:flex; align-items:center; gap:12px; font-size:14px; }
.rvbar { width:160px; height:8px; border-radius:4px; background:var(--rv-soft); overflow:hidden; }
.rvbar i { display:block; height:100%; background:var(--rv-ok); width:0; transition:width .25s; }
.rvptxt { color:var(--rv-mut); } .rvptxt b { color:var(--rv-fg); }
.rvintro { padding-top:12px; font-size:14px; color:var(--rv-mut); }
.rvintro p { margin:0 0 4px; }
.rvA { display:grid; grid-template-columns:200px minmax(0,1fr); gap:28px; align-items:start; padding-top:14px; }
.rvA nav { position:sticky; top:calc(var(--rvh, 64px) + 8px); display:grid; gap:2px; }
.rvA nav a { display:grid; grid-template-columns:14px 28px 1fr; gap:6px; align-items:center; padding:7px 10px; border-radius:6px; color:inherit; text-decoration:none; }
.rvA nav a:hover { background:var(--rv-soft); }
.rvA nav b { font-size:13px; } .rvA nav span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; }
.rvA nav em { grid-column:3; font-style:normal; font-size:12px; color:var(--rv-mut); }
.rvA main { display:grid; gap:22px; min-width:0; }
section.rvpg { background:var(--rv-surface); border:1px solid var(--rv-line); border-radius:10px; padding:18px 20px; display:grid; gap:14px; scroll-margin-top:calc(var(--rvh, 72px) + 12px); min-width:0; }
section.rvpg h2 { margin:0; font-size:16px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
.rvbd { font-size:12px; padding:1px 10px; border-radius:11px; border:1px solid var(--rv-line); color:var(--rv-mut); white-space:nowrap; font-weight:400; }
.rvbd.ok { color:var(--rv-ok); border-color:var(--rv-ok); } .rvbd.sel { color:var(--rv-sel); border-color:var(--rv-sel); }
.rvdot { display:inline-block; width:10px; height:10px; border-radius:50%; border:2px solid var(--rv-mut); box-sizing:border-box; }
.rvdot.ok { background:var(--rv-ok); border-color:var(--rv-ok); } .rvdot.sel { background:var(--rv-sel); border-color:var(--rv-sel); }
.rvbig { max-width:980px; }
.rvf { width:100%; aspect-ratio:16/9; overflow:hidden; position:relative; background:#fff; border:1px solid var(--rv-line); border-radius:4px; }
.rvh { position:absolute; left:0; top:0; width:1280px; height:720px; transform-origin:0 0; }
.rvthumbs { display:flex; gap:10px; flex-wrap:wrap; }
.rvthumb { width:min(200px,30%); background:none; border:2px solid transparent; border-radius:8px; padding:3px; text-align:left; display:grid; gap:3px; }
.rvthumb.on { border-color:var(--rv-acc); }
.rvthumb small { font-size:12px; color:var(--rv-mut); } .rvthumb.on small { color:var(--rv-acc); }
.rvctl { display:grid; gap:6px; }
.rvrow { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
.rvbtn { border-radius:6px; padding:8px 16px; border:1px solid var(--rv-acc); background:transparent; color:var(--rv-acc); }
.rvbtn.pri { background:var(--rv-acc); color:var(--rv-acc-ink); font-weight:700; }
.rvbtn[disabled] { opacity:.4; cursor:not-allowed; }
.rvlnk { background:none; border:0; color:var(--rv-mut); text-decoration:underline; padding:4px; }
.rvmsg, .rvnote { font-size:13px; color:var(--rv-mut); }
.rvta { width:100%; box-sizing:border-box; font:inherit; color:inherit; background:var(--rv-bg); border:1px solid var(--rv-line); border-radius:6px; padding:8px 10px; resize:vertical; }
.rvtop .rvmsg { flex-basis:100%; margin:0; text-align:right; }
.rvmsg:empty { display:none; }
.rvout { width:100%; box-sizing:border-box; font:12px/1.4 monospace; height:7em; }
#rv [hidden] { display:none !important; }
.rv-tabs { flex-basis:100%; display:flex; gap:4px; border-bottom:1px solid var(--rv-line); margin-bottom:-11px; }
.rv-tab { background:none; border:0; border-bottom:3px solid transparent; padding:6px 16px; color:var(--rv-mut); }
.rv-tab[aria-selected="true"] { color:var(--rv-acc); border-bottom-color:var(--rv-acc); font-weight:700; }
.rv-panel { padding-top:14px; display:grid; gap:12px; min-width:0; }
.rv-legend { font-size:13px; color:var(--rv-mut); display:grid; gap:4px; }
.rv-legend b { color:var(--rv-fg); }
.rv-detail { border:1px solid var(--rv-line); border-radius:8px; background:var(--rv-surface); padding:10px 14px; font-size:14px; }
.rv-detail p { margin:2px 0; }
.rv-scroll { overflow-x:auto; }
table.rv-t { border-collapse:collapse; width:100%; background:var(--rv-surface); font-size:13px; }
table.rv-t th, table.rv-t td { border:1px solid var(--rv-line); padding:5px 8px; text-align:left; vertical-align:top; }
table.rv-t thead th { background:var(--rv-soft); }
table.rv-t td.rv-c { text-align:center; cursor:pointer; white-space:nowrap; min-width:48px; }
table.rv-t tr.rv-r { cursor:pointer; } table.rv-t tr.rv-r:hover th { background:var(--rv-soft); }
table.rv-t tr.rv-on th { box-shadow:inset 3px 0 0 var(--rv-acc); }
.rv-lv { font-size:11px; color:var(--rv-mut); margin-left:6px; font-weight:400; }
.rv-st { font-weight:700; } .rv-st-ok { color:var(--rv-ok); } .rv-st-ng { color:var(--rv-ng); } .rv-st-warn { color:var(--rv-warn); }
.rv-st-manual, .rv-st-build, .rv-st-none { color:var(--rv-mut); font-weight:400; }
.rv-badges { display:flex; flex-wrap:wrap; gap:3px; }
.rv-badges span { font-size:11px; border:1px solid var(--rv-line); border-radius:9px; padding:0 6px; color:var(--rv-mut); white-space:nowrap; }
details.rv-prules { border:1px solid var(--rv-line); border-radius:8px; padding:6px 12px; font-size:13px; }
details.rv-prules summary { cursor:pointer; } details.rv-prules table { margin-top:8px; }
details.rv-prules .rvbtn { padding:2px 10px; font-size:12px; white-space:nowrap; }
details.rv-prules table.rv-t td:nth-child(-n+4) { white-space:nowrap; }  /* ルール・判定者・対象・結果は折り返さない */
.rv-st-done { color:var(--rv-ok); } .rv-st-undone { color:var(--rv-warn); } .rv-st-pending { color:var(--rv-mut); }
.rv-human { border:1px solid var(--rv-line); border-radius:8px; padding:8px 12px; display:grid; gap:4px; font-size:13px; }
.rv-human b { font-size:13px; }
label.rv-hc { display:flex; gap:8px; align-items:flex-start; cursor:pointer; }
label.rv-hc input { margin-top:4px; }
.rv-hwarn { font-size:13px; color:var(--rv-warn); border-left:3px solid var(--rv-warn); padding:2px 10px; }
.rv-hdone { font-size:13px; color:var(--rv-ok); }
.rv-rubric { white-space:pre-wrap; margin:2px 0; }
.rv-color { flex-basis:100%; display:flex; align-items:center; gap:10px; min-width:0; }
.rv-color-label { font-size:13px; font-weight:700; white-space:nowrap; }
.rv-color-row { display:flex; flex-wrap:nowrap; gap:6px; overflow-x:auto; padding:3px 3px 5px; min-width:0; }
.rv-cs { display:inline-flex; align-items:center; gap:5px; border:1px solid var(--rv-line); background:var(--rv-surface); color:var(--rv-fg); border-radius:18px; padding:4px 12px 4px 8px; font:inherit; font-size:13px; cursor:pointer; white-space:nowrap; }
.rv-cs[aria-pressed="true"] { border-color:var(--rv-acc); box-shadow:0 0 0 2px var(--rv-acc); font-weight:700; }
.rv-chip { width:14px; height:14px; border-radius:50%; border:1px solid #0003; display:inline-block; }
.rv-vert-closing { background:var(--rv-surface); border:1px solid var(--rv-line); border-radius:8px; padding:10px 14px; font-size:14px; }
@media (max-width:820px) {
  .rvA { grid-template-columns:1fr; }
  .rvA nav { position:static; grid-auto-flow:column; justify-content:start; overflow-x:auto; }
  .rvA nav span, .rvA nav em { display:none; }
}
</style>
<div id="rv">
  <header class="rvtop">
    <h1>スライド案の選択</h1>
    <div class="rvprog"><div class="rvbar"><i id="bar"></i></div><span class="rvptxt" id="ptxt"></span><button class="rvbtn pri" type="button" id="share">Claude に渡す</button><button class="rvbtn" type="button" id="rv-bulk" title="案を選んであり、コメントがなく、人の確認の項目が済んでいるページを、まとめて承認します">選択済みを一括承認</button></div>
    <p class="rvmsg" id="st"></p>
    <p class="rvmsg" id="rv-bulk-msg" role="status"></p>
    <textarea class="rvout" id="out" readonly hidden></textarea>
    <nav class="rv-tabs" id="rv-tabs" role="tablist" hidden>
      <button class="rv-tab" type="button" role="tab" id="rv-tab-pick" data-tab="pick">案の選択</button>
      <button class="rv-tab" type="button" role="tab" id="rv-tab-rules" data-tab="rules">ルール一覧</button>
      <button class="rv-tab" type="button" role="tab" id="rv-tab-vert" data-tab="vert">縦読み</button>
    </nav>
    <div class="rv-color" id="rv-color-panel"></div>
  </header>
  <div class="rvintro" id="rv-intro">
    <p>各ページで案を選び、直したい点があればコメント欄に書き、よければ「承認」を押してください。</p>
    <p>終わったら「Claude に渡す」を押して、コピーされた内容をチャットに貼り付けてください。<b>貼り付けたあとは、Claude が作り直したページを開き直してください</b>（古いページから渡した内容は、受け取れません）。</p>
  </div>
  <div class="rvA" id="rv-pick"><nav id="nav"></nav><main id="pages"></main></div>
  <div class="rv-panel" id="rv-rules" hidden></div>
  <div class="rv-panel" id="rv-vert" hidden></div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script type="application/json" id="rv-data">__RULES__</script>
<script type="application/json" id="rv-color">__COLORS__</script>
<script>__CHART__</script>
<script>
var BASE = __BASE__;
var INIT = __STATE__;
var FR = __FR__;  // 各スライド・各案の断片の指紋（choices.fragment_hash）。承認が、見た断片に結びつくように、承認に持たせる
var STAMP = "__STAMP__";
(function () {
var PAGES = JSON.parse(document.getElementById("data").textContent);
var FRAMES = [], P = {}, S = {}, order = [], syncs = [], pending = [], WARN = {}, SHADOWS = [];
var RV = JSON.parse(document.getElementById("rv-data").textContent);  // ルール表示のデータ。原稿がなければ null（タブを出さない）
var HUM = RV ? RV.human : [];  // 人の確認の項目（有効な人のルール）。確認は本文スライドだけ
var BODY = {};
if (RV) RV.vertical.rows.forEach(function (r) { BODY[r.nn] = true; });
function cleanChecks(c) {  // 人の確認の状態。今ある項目の、true だけを残す（順序は項目の順）
  var o = {};
  HUM.forEach(function (x) { if (c && c[x.rule] === true) o[x.rule] = true; });
  return o;
}
// --- 編集モード（文言・位置の直し）: 断片の文字列から数えた番号（fragedit.parts と同じ規則）で要素を指す ---
var PPKIND = /^pp-(text|shape|line|image|table|chart|picture)$/, GEO = ["left", "top", "width", "height"];
function ppKind(el) {
  var t = (el.getAttribute("class") || "").split(/\\s+/);
  for (var i = 0; i < t.length; i++) { var m = PPKIND.exec(t[i]); if (m) return m[1]; }
  return null;
}
function ppEls(root) { return [].filter.call(root.querySelectorAll("*"), function (e) { return ppKind(e); }); }
function ownTexts(el) {  // 入れ子の pp-* の中を除く、空白だけでないテキストノード
  var o = [];
  (function walk(n) {
    for (var c = n.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) { if (c.nodeValue.trim()) o.push(c); } else if (c.nodeType === 1 && !ppKind(c)) walk(c);
    }
  })(el);
  return o;
}
function partsOf(html) {
  var doc = new DOMParser().parseFromString(html, "text/html");
  return ppEls(doc).map(function (el, i) {
    var nested = false, st = {}, m, re = /([^;:]+):([^;]*)/g, sa = el.getAttribute("style") || "";
    for (var a = el.parentElement; a; a = a.parentElement) if (ppKind(a)) nested = true;
    while ((m = re.exec(sa))) st[m[1].trim().toLowerCase()] = m[2].trim();
    return {i: i, kind: ppKind(el), nested: nested, fixed: el.hasAttribute("data-chrome") || el.hasAttribute("data-ph"), style: st, texts: ownTexts(el).map(function (n) { return n.nodeValue; })};
  });
}
function cleanEdits(nn, e) {  // 今ある案で、断片の指紋が今と同じ編集だけを残す
  var o = {};
  if (!e || typeof e !== "object") return o;
  Object.keys(e).forEach(function (k) {
    var x = e[k];
    if (P[nn].keys.indexOf(k) >= 0 && x && typeof x === "object" && x.ef === (FR[nn] || {})[k] && x.items && typeof x.items === "object" && Object.keys(x.items).length) o[k] = {ef: x.ef, items: x.items};
  });
  return o;
}
PAGES.forEach(function (p) {
  var ks = Object.keys(p[1]), i = INIT[p[0]] || {};
  order.push(p[0]);
  P[p[0]] = {keys: ks, c: p[1], labels: p[2], title: p[3]};
  // 開いたときの状態は choices/<NN>.json から。1 案のページは選択済み。案が今はない pick は捨てる
  var had = ks.indexOf(i.pick) >= 0;
  S[p[0]] = {
    pick: had ? i.pick : (ks.length === 1 ? ks[0] : null),
    status: had && (i.status === "approved" || i.status === "saved") ? i.status : null,
    comment: typeof i.comment === "string" ? i.comment : "",
    checks: cleanChecks(i.checks),
    edits: {},
    fr: null
  };
  if (S[p[0]].status === "approved") S[p[0]].fr = (FR[p[0]] || {})[S[p[0]].pick] || null;  // 埋め込み状態の承認は、指紋が今と合うものだけ（_embedded_state）
});
// 選んだ内容はこのブラウザに自動で残す（誤って閉じても戻る）。ページが作り直されると指紋が変わり、使わない
var KEY = "pptx-maker-review:" + STAMP;
try {
  var sv = JSON.parse(localStorage.getItem(KEY) || "null") || {};
  order.forEach(function (nn) {
    var x = sv[nn];
    if (x && (x.pick === null || P[nn].keys.indexOf(x.pick) >= 0) && typeof x.comment === "string" && (x.status === "approved" || x.status === "saved" || x.status === null)) {
      var fr = x.pick === null ? null : (FR[nn] || {})[x.pick] || null;
      // 承認は、見た断片の指紋 fr が今の断片と同じときだけ復元する（断片が直されていたら saved に落とす）
      S[nn] = {pick: x.pick, status: x.status === "approved" && x.fr !== fr ? "saved" : x.status, comment: x.comment, checks: cleanChecks(x.checks), edits: cleanEdits(nn, x.edits), fr: x.status === "approved" && x.fr === fr ? fr : null};
    }
  });
} catch (e) {}
var SHEET = null;  // 同じ CSS を案ごとに複製しないよう、1 枚のシートを全 shadow root で共有する
try { SHEET = new CSSStyleSheet(); SHEET.replaceSync(BASE); } catch (e) { SHEET = null; }
// 要素を作る。文字は必ず textContent で入れる（断片の題・案の特徴を HTML として解釈しない）
function h(t, a, c) {
  var e = document.createElement(t);
  for (var k in (a || {})) { if (k === "class") e.className = a[k]; else if (k === "text") e.textContent = a[k]; else e.setAttribute(k, a[k]); }
  (c || []).forEach(function (x) { if (x) e.appendChild(x); });
  return e;
}
function $(id) { return document.getElementById(id); }
var hdr = new ResizeObserver(function () { document.documentElement.style.setProperty("--rvh", document.querySelector(".rvtop").offsetHeight + "px"); });
hdr.observe(document.querySelector(".rvtop"));
var ro = new ResizeObserver(function (es) { es.forEach(function (en) { var f = en.target; f.firstElementChild.style.transform = "scale(" + (f.clientWidth / 1280) + ")"; }); });
// 案の枠。中身は文書に入れたあとで flush() が入れる（グラフは文書に入った要素から変数を読む）
function frame(nn, k) { var f = h("div", {class: "rvf", "data-k": k}, [h("div", {class: "rvh"})]); pending.push([f, nn, k]); return f; }
// 1 つの案のグラフが描けなくても（data-chart の不備）、ほかの案とページ全体は動かす
function drawChart(c) {
  if (!window.__chartPreview) return;
  try { window.__chartPreview(c); } catch (e) {
    console.error("chart-preview:", e, c.dataset.chart);
    c.textContent = e instanceof SyntaxError ? "グラフを描けません（data-chart が JSON として読めません）" : "グラフを描けません（プレビューの描画に失敗しました: " + e.message + "）";
  }
}
function flush() {
  pending.splice(0).forEach(function (x) {
    var f = x[0], sh = f.firstChild.attachShadow({mode: "open"});
    SHADOWS.push(sh);
    FRAMES.push([sh, x[1], x[2]]);
    if (SHEET) sh.adoptedStyleSheets = [SHEET];
    paint(sh, x[1], x[2]);
    ro.observe(f);
  });
}
function paint(sh, nn, k) {  // 断片を入れ、編集を反映してから、グラフ・矢印を描く（編集は描く前の素の DOM に当てる）
  sh.innerHTML = (SHEET ? "" : "<style>" + BASE + "</style>") + P[nn].c[k];
  applyEdits(sh, nn, k);
  sh.querySelectorAll(".pp-chart").forEach(drawChart);
  if (window.__arrows) window.__arrows(sh);
}
function applyEdits(sh, nn, k) {
  var e = S[nn].edits[k];
  if (!e) return;
  var ps = partsOf(P[nn].c[k]), els = ppEls(sh);
  if (els.length !== ps.length) return;  // 数が違うフレームには反映しない
  Object.keys(e.items).forEach(function (key) {
    var it = e.items[key], el = els[+key], p = ps[+key];
    if (!el || !p) return;
    GEO.forEach(function (g) { if (typeof it[g] === "number") el.style.setProperty(g, it[g] + "px"); });
    if (it.text) {
      var ns = ownTexts(el);
      if (ns.length !== p.texts.length || ns.length !== it.text.length) return;
      ns.forEach(function (n, j) {
        var raw = n.nodeValue;
        n.nodeValue = raw.slice(0, raw.length - raw.trimStart().length) + it.text[j] + raw.slice(raw.trimEnd().length);
      });
    }
  });
}
function setEdit(nn, k, i, patch) {
  if (!P[nn] || !(FR[nn] || {})[k]) return;
  var ps = partsOf(P[nn].c[k]), p = ps[i], e = S[nn].edits[k] || {ef: FR[nn][k], items: {}};
  if (!p) return;
  var it = Object.assign({}, e.items[i], patch);
  GEO.forEach(function (g) { if (g in it && parseFloat(p.style[g]) === it[g]) delete it[g]; });
  if (it.text && it.text.length === p.texts.length && it.text.every(function (t, j) { return t === p.texts[j]; })) delete it.text;
  if (Object.keys(it).length) e.items[i] = it; else delete e.items[i];
  if (Object.keys(e.items).length) S[nn].edits[k] = e; else delete S[nn].edits[k];
  touch(nn);
  FRAMES.forEach(function (f) { if (f[1] === nn && f[2] === k && f[0].host.isConnected) paint(f[0], nn, k); });
  refresh();
}
window.__rvEdit = {parts: partsOf, set: setEdit};
function info(nn) {
  var s = S[nn];
  if (s.comment.trim()) return {c: "sel", t: "コメントあり"};
  if (s.status === "approved") return {c: "ok", t: "承認済み"};
  if (s.pick && P[nn].keys.length > 1) return {c: "sel", t: "選択中（未承認）"};
  return {c: "", t: "未承認"};
}
function refresh() {
  syncs.forEach(function (f) { f(); });
  try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {}
}
function shown(nn) { return S[nn].pick || P[nn].keys[0]; }
function vname(k) { return k; }
// --- ルール表示（RV があるときだけ） ---
var RVR = {}, MARK = {ok: "OK", ng: "NG", warn: "注意", manual: "確認", build: "build時", none: "・", pending: "AI判定待ち", done: "確認済み", undone: "未確認"};
if (RV) RV.rules.forEach(function (r) { RVR[r.id] = r; });
function pageRules(nn, k) {  // そのページ（ページ単位）と、案 k（案単位）の検査結果
  var pg = RV && RV.pages[nn];
  if (!pg) return [];
  return pg.deck_rules.map(function (x) { return {rule: x.rule, status: x.status, message: x.message, by: x.by, scope: "ページ"}; })
    .concat(((pg.variants || {})[k] || []).map(function (x) { return {rule: x.rule, status: x.status, message: x.message, by: x.by, scope: "案"}; }))
    .sort(function (a, b) { return a.rule < b.rule ? -1 : a.rule > b.rule ? 1 : 0; });  // R01 から順
}
function cnt(list) { var c = {ok: 0, ng: 0, warn: 0, pending: 0}; list.forEach(function (x) { if (x.status in c) c[x.status]++; }); return c; }
function ngwarn(c) { return (c.ng ? "NG " + c.ng : "") + (c.ng && c.warn ? "／" : "") + (c.warn ? "注意 " + c.warn : ""); }
function stMark(st) { return h("span", {class: "rv-st rv-st-" + st, text: MARK[st]}); }
function goPage(nn) {
  goTab("pick");
  var e = $("pg-" + nn);
  if (e) e.scrollIntoView();
}
function setBig(nn) {
  var big = $("pg-" + nn).querySelector(".rvbig");
  if (big.firstChild && big.firstChild.dataset.k === shown(nn)) return;
  big.textContent = "";
  big.appendChild(frame(nn, shown(nn)));
  flush();
}
// 選び直し・コメントは承認をやり直しにする（承認は「今見えている案とコメントなし」への承認）
function touch(nn) { if (S[nn].status === "approved") { S[nn].status = "saved"; S[nn].fr = null; } $("st").textContent = ""; $("rv-bulk-msg").textContent = ""; }
function approveOne(nn) { if (!S[nn].pick) S[nn].pick = shown(nn); S[nn].status = "approved"; S[nn].fr = (FR[nn] || {})[S[nn].pick] || null; WARN[nn] = true; }
function bulkApprove() {  // 案を選んであり、コメントが空で、人の確認の項目が全部済んでいるページを承認する。承認済みは変えない
  var done = [], why = {comment: [], checks: [], nopick: []};
  order.forEach(function (nn) {
    var s = S[nn];
    if (s.status === "approved") return;
    if (!s.pick) why.nopick.push(nn);
    else if (s.comment.trim()) why.comment.push(nn);
    else if (unchecked(nn).length) why.checks.push(nn);
    else { approveOne(nn); done.push(nn); }
  });
  refresh();
  var parts = [["コメントあり", why.comment], ["確認項目が未チェック", why.checks], ["案が未選択", why.nopick]].filter(function (x) { return x[1].length; }).map(function (x) { return x[0] + " " + x[1].length + " 件（" + x[1].join("・") + "）"; });
  $("rv-bulk-msg").textContent = "承認 " + done.length + " 件" + (parts.length ? "。承認しなかったページ: " + parts.join("、") : "。");
}
function unchecked(nn) { return BODY[nn] ? HUM.filter(function (x) { return !S[nn].checks[x.rule]; }) : []; }
function humanLeft() { return order.reduce(function (a, n) { return a + unchecked(n).length; }, 0); }
var nav = $("nav"), main = $("pages");
syncs.push(function () {
  var ok = order.filter(function (n) { return S[n].status === "approved"; }).length, t = $("ptxt"), hl = humanLeft();
  $("bar").style.width = (ok / order.length * 100) + "%";
  t.textContent = "";
  t.appendChild(h("b", {text: "承認 " + ok + "/" + order.length}));
  t.appendChild(document.createTextNode("　未承認 " + (order.length - ok)));
  if (hl) t.appendChild(document.createTextNode("　人の確認 未了 " + hl + " 件"));
});
order.forEach(function (nn) {
  var p = P[nn], title = p.title || "";
  var dot = h("i", {class: "rvdot"}), em = h("em");
  nav.appendChild(h("a", {href: "#pg-" + nn}, [dot, h("b", {text: nn}), h("span", {text: title}), em]));
  var bd = h("span", {class: "rvbd"}), big = h("div", {class: "rvbig"});
  var thumbs = null;
  if (p.keys.length > 1) {
    thumbs = h("div", {class: "rvthumbs"});
    p.keys.forEach(function (k) {
      var b = h("button", {class: "rvthumb", type: "button", "data-k": k}, [frame(nn, k), h("small", {text: vname(k) + "　" + (p.labels[k] || "")}), RV && RV.meta[nn] ? badges(nn, k) : null]);
      b.addEventListener("click", function () { pick(nn, k); });
      thumbs.appendChild(b);
    });
  }
  var ta = h("textarea", {class: "rvta", rows: "3", "aria-label": "スライド " + nn + " へのコメント", placeholder: "直してほしい点があれば書いてください（なければ空のまま）"});
  ta.value = S[nn].comment;
  var ok = h("button", {class: "rvbtn pri", type: "button", "data-act": "approve", text: "承認"});
  var undo = h("button", {class: "rvlnk", type: "button", "data-act": "undo", text: "承認を取り消す"});
  var note = h("div", {class: "rvnote"});
  ta.addEventListener("input", function () { S[nn].comment = ta.value; touch(nn); refresh(); });
  ok.addEventListener("click", function () { approveOne(nn); $("st").textContent = ""; $("rv-bulk-msg").textContent = ""; refresh(); });  // 未確認の項目があっても承認は止めない（警告だけ）
  undo.addEventListener("click", function () { S[nn].status = "saved"; WARN[nn] = false; $("st").textContent = ""; $("rv-bulk-msg").textContent = ""; refresh(); });
  var human = BODY[nn] && HUM.length ? humanBox(nn) : null;
  var hwarn = h("div", {class: "rv-hwarn", role: "alert"}), hdone = h("div", {class: "rv-hdone"});
  var sec = h("section", {class: "rvpg", id: "pg-" + nn}, [
    h("h2", {}, [h("span", {text: "スライド " + nn + (title ? "　" + title : "")}), bd]),
    big, thumbs, RV && RV.pages[nn] ? prules(nn, ta) : null,
    h("div", {class: "rvctl"}, [ta, human, h("div", {class: "rvrow"}, [ok, undo]), hwarn, hdone, note])
  ]);
  main.appendChild(sec);
  big.appendChild(frame(nn, shown(nn)));
  syncs.push(function () {
    var i = info(nn), s = S[nn], appr = s.status === "approved", cm = !!s.comment.trim();
    dot.className = "rvdot " + i.c; em.textContent = i.t;
    bd.className = "rvbd " + i.c; bd.textContent = i.t;
    if (thumbs) [].forEach.call(thumbs.children, function (b) { b.classList.toggle("on", b.dataset.k === s.pick); });
    ok.disabled = appr || !s.pick || cm;
    ok.textContent = appr ? "承認済み ✓" : "承認";
    undo.hidden = !appr;
    var left = unchecked(nn);
    hwarn.hidden = !(WARN[nn] && appr && left.length);
    hwarn.textContent = hwarn.hidden ? "" : "未確認の項目があります: " + left.map(function (x) { return x.rule + " " + x.name; }).join("、") + "。確認してから承認してください";
    hdone.hidden = !(appr && human);
    hdone.textContent = hdone.hidden ? "" : "確認済み " + (HUM.length - left.length) + "/" + HUM.length;
    note.textContent = appr ? "このページは承認済みです。" : !s.pick ? "案を選んでください。" : cm ? "コメントがあるうちは承認できません。Claude に直してもらってから承認してください。" : "直したい点があればコメント欄へ。よければ「承認」。";
  });
});

// 人が確認する項目: チェックは S[nn].checks に持ち、localStorage と「Claude に渡す」の JSON に入る
function humanBox(nn) {
  var box = h("div", {class: "rv-human"}, [h("b", {text: "人が確認する項目（承認の前に確認してください）"})]);
  HUM.forEach(function (x) {
    var cb = h("input", {type: "checkbox"});
    cb.checked = !!S[nn].checks[x.rule];
    cb.addEventListener("change", function () {
      if (cb.checked) S[nn].checks[x.rule] = true; else delete S[nn].checks[x.rule];
      S[nn].checks = cleanChecks(S[nn].checks);
      refresh();
    });
    box.appendChild(h("label", {class: "rv-hc", "data-rule": x.rule}, [cb, h("span", {text: x.rule + " " + x.name + "　" + x.question})]));
  });
  return box;
}
function badges(nn, k) {
  var m = RV.meta[nn][k], c = cnt(pageRules(nn, k));
  var t = ["主役 " + m.kind, "強調 " + m.emph, "文字 " + m.chars + "字"];
  if (RV.pages[nn]) t.push("ルール OK " + c.ok + "／注意 " + (c.ng + c.warn));
  return h("div", {class: "rv-badges"}, t.map(function (x) { return h("span", {text: x}); }));
}
// 各ページの「このページのルール」: 選んでいる案の検査結果と、コメント欄へ定型文を足すボタン
function prules(nn, ta) {
  var sum = h("summary"), body = h("tbody"), key = null;
  var el = h("details", {class: "rv-prules"}, [sum, h("div", {class: "rv-scroll"}, [h("table", {class: "rv-t"}, [
    h("thead", {}, [h("tr", {}, [h("th", {text: "ルール"}), h("th", {text: "判定者"}), h("th", {text: "対象"}), h("th", {text: "結果"}), h("th", {text: "内容"}), h("th")])]), body])])]);
  syncs.push(function () {
    var k = shown(nn);
    if (key === k) return;
    key = k;
    var list = pageRules(nn, k), c = cnt(list);
    sum.textContent = "このページのルール" + (c.ng + c.warn ? "（" + ngwarn(c) + "）" : "") + (c.pending ? "　AI 判定待ち " + c.pending + " 件" : "");
    body.textContent = "";
    list.forEach(function (x) {
      var r = RVR[x.rule], btn = null;
      if (x.status === "ng" || x.status === "warn") {
        btn = h("button", {class: "rvbtn", type: "button", text: "このルールで直して"});
        btn.addEventListener("click", function () {
          var t = x.rule + "（" + r.name + "）: " + (x.message || "要確認").replace(/^S\\d{2}: /, "") + "。直してください";
          if (ta.value.indexOf(t) >= 0) return;
          ta.value += (ta.value && !/\\n$/.test(ta.value) ? "\\n" : "") + t;
          ta.dispatchEvent(new Event("input"));
        });
      }
      body.appendChild(h("tr", {"data-rule": x.rule}, [h("td", {text: x.rule + " " + r.name}), h("td", {text: x.by || r.kind}), h("td", {text: x.scope}), h("td", {}, [stMark(x.status)]), h("td", {text: (x.by === "AI" && x.status !== "pending" ? "AI 判定: " : "") + x.message}), h("td", {}, [btn])]));
    });
  });
  return el;
}
var tabs = {pick: $("rv-pick"), rules: $("rv-rules"), vert: $("rv-vert")};
function goTab(name) {
  for (var t in tabs) { tabs[t].hidden = t !== name; $("rv-tab-" + t).setAttribute("aria-selected", String(t === name)); }
  $("rv-intro").hidden = name !== "pick";
  $("rv-color-panel").hidden = name !== "pick";
  if (name === "rules") renderRules();
  if (name === "vert") renderVert();
}
function cellOf(rid, nn) {  // ルールのセル: [status, message]。nn が null なら「全体」
  var ids = RV.vertical.rows.map(function (r) { return r.nn; }).filter(function (n) { return P[n]; });
  if (RVR[rid].kind === "人") {  // そのページの確認の状態。全体は、全ページが確認済みか
    if (nn !== null) return S[nn] && S[nn].checks[rid] ? ["done", "確認済み"] : ["undone", "未確認（人が質問に答えて確認する）"];
    var n = ids.filter(function (m) { return S[m].checks[rid]; }).length;
    return n === ids.length && n ? ["done", "全ページ確認済み"] : ["undone", "確認済み " + n + "/" + ids.length + " ページ"];
  }
  var src = nn === null ? RV.deck : pageRules(nn, shown(nn));
  if (nn === null && RV.measured && (rid === "R20" || rid === "R23" || rid === "R26")) {  // 測った結果は、選んでいる案で集める
    src = []; ids.forEach(function (m) { src = src.concat(pageRules(m, shown(m))); });
  }
  var list = src.filter(function (x) { return x.rule === rid; });
  if (!list.length) return ["none", "検査なし"];
  if (list.every(function (x) { return x.status === "build"; })) return ["build", list[0].message];
  var ai = RVR[rid].kind === "AI", pend = list.every(function (x) { return x.status === "pending"; });
  var st = list.some(function (x) { return x.status === "ng"; }) ? "ng" : list.some(function (x) { return x.status === "warn"; }) ? "warn" : pend ? "pending" : "ok";
  var msg = list.map(function (x) { return x.message; }).filter(Boolean).join(" / ");
  return [st, (ai && !pend ? "AI 判定: " : "") + (msg || "問題なし")];
}
function renderRules() {
  var box = $("rv-rules"), pages = RV.vertical.rows.map(function (r) { return r.nn; }).filter(function (n) { return P[n]; });
  box.textContent = "";
  var all = RV.deck.slice();
  pages.forEach(function (n) { all = all.concat(pageRules(n, shown(n))); });
  var c = cnt(all);
  var detail = h("div", {class: "rv-detail", id: "rv-detail"}, [h("p", {text: "ルールの行をクリックすると、説明が出ます。セルをクリックすると、そのページへ移ります。"})]);
  var legend = h("div", {class: "rv-legend", id: "rv-legend"}, [
    h("div", {}, [h("b", {text: "凡例　"}), document.createTextNode("OK＝指摘なし　NG＝必須の自動検査の指摘　注意＝推奨・要確認の指摘　確認済み／未確認＝人が質問に答えて確認する項目（各ページのチェック）　build時＝PPTX を作るとき（build）に自動検査　・＝そのページ・案には当たらない")]),
    h("div", {}, [document.createTextNode("AI＝Claude が採点表で判定（誤りうる）　AI判定待ち＝Claude がまだ判定していない（記録がない。案を直して判定を消したときも、この表示になる。判定は rule-review-import で記録する）")]),
    h("div", {}, [h("b", {text: "いまの指摘　"}), document.createTextNode("NG " + c.ng + " 件／注意 " + c.warn + " 件／AI 判定待ち " + c.pending + " 件（案は、各ページで選んでいる案。選んでいなければ先頭の案。AI 判定待ちは NG・注意に数えない）")])
  ]);
  var head = h("tr", {}, [h("th", {text: "ルール"})]);
  pages.forEach(function (n) { head.appendChild(h("th", {text: "S" + n})); });
  head.appendChild(h("th", {text: "全体"}));
  var body = h("tbody"), on = null;
  RV.rules.slice().sort(function (a, b) { return a.id < b.id ? -1 : a.id > b.id ? 1 : 0; }).forEach(function (r) {
    var tr = h("tr", {class: "rv-r", "data-rule": r.id}, [h("th", {}, [document.createTextNode(r.id + " " + r.name), h("span", {class: "rv-lv", text: r.level})])]);
    pages.concat([null]).forEach(function (n) {
      var v = cellOf(r.id, n), td = h("td", {class: "rv-c", "data-pg": n === null ? "all" : n, title: r.id + ": " + v[1]}, [stMark(v[0])]);
      if (n !== null) td.addEventListener("click", function (e) { e.stopPropagation(); goPage(n); });
      tr.appendChild(td);
    });
    tr.addEventListener("click", function () {
      if (on) on.classList.remove("rv-on");
      on = tr; tr.classList.add("rv-on");
      detail.textContent = "";
      detail.appendChild(h("p", {}, [h("b", {text: r.id + " " + r.name})]));
      detail.appendChild(h("p", {text: r.description}));
      if (r.rubric) detail.appendChild(h("p", {class: "rv-rubric", text: "採点表（AI が判定する基準）\\n" + r.rubric}));
      if (r.question) detail.appendChild(h("p", {text: "質問（人が確認する）: " + r.question}));
      detail.appendChild(h("p", {class: "rvnote", text: "区分: " + r.level + "　検査の種類: " + r.kind + "　場所: " + r.where}));
    });
    body.appendChild(tr);
  });
  [legend, detail, h("div", {class: "rv-scroll"}, [h("table", {class: "rv-t"}, [h("thead", {}, [head]), body])])].forEach(function (x) { box.appendChild(x); });
}
function renderVert() {
  var box = $("rv-vert"), body = h("tbody");
  box.textContent = "";
  RV.vertical.rows.forEach(function (r) {
    var c = cnt(P[r.nn] ? pageRules(r.nn, shown(r.nn)) : []);
    var tr = h("tr", {class: "rv-r"}, [h("td", {text: "S" + r.nn}), h("td", {text: r.title}), h("td", {text: r.head}), h("td", {text: r.issue}), h("td", {text: r.conn}), h("td", {text: ngwarn(c) || "指摘なし"}), h("td", {text: P[r.nn] && HUM.length ? "確認済み " + (HUM.length - unchecked(r.nn).length) + "/" + HUM.length : "・"})]);
    if (P[r.nn]) tr.addEventListener("click", function () { goPage(r.nn); });
    body.appendChild(tr);
  });
  var cols = ["ページ", "題", "ヘッドメッセージ", "論点", "直前からの接続語", "指摘", "人の確認"];
  box.appendChild(h("p", {class: "rvnote", text: "ヘッドだけを上から読んで、結論と根拠が「なぜ」「だから」でつながるかを確かめます。行をクリックすると、そのページへ移ります。"}));
  box.appendChild(h("div", {class: "rv-scroll"}, [h("table", {class: "rv-t"}, [h("thead", {}, [h("tr", {}, cols.map(function (x) { return h("th", {text: x}); }))]), body])]));
  box.appendChild(h("div", {class: "rv-vert-closing"}, [h("b", {text: "裏表紙の要点　"}), document.createTextNode(RV.vertical.closing || "（なし）")]));
}
if (RV) {
  $("rv").classList.add("rvhas");
  $("rv-tabs").hidden = false;
  [].forEach.call(document.querySelectorAll(".rv-tab"), function (b) { b.addEventListener("click", function () { goTab(b.dataset.tab); }); });
  goTab("pick");
}
flush();  // 枠をすべて文書に入れてから、中身を入れてグラフを描く
// --- 配色セット: 選ぶとページの CSS 変数を差し替えて、全ページの案の色を変える。選んだ色は「Claude に渡す」の color で渡す ---
var CD = JSON.parse(document.getElementById("rv-color").textContent);
var CKEY = KEY + ":color", COLOR = CD.current, CBTNS = [];
function sameColor(a, b) { return a.accent.toUpperCase() === b.accent.toUpperCase() && a.emphasis.toUpperCase() === b.emphasis.toUpperCase(); }
function applyColor(c) {
  Object.keys(c.vars).forEach(function (k) { document.documentElement.style.setProperty("--" + k, c.vars[k]); });
  SHADOWS.forEach(function (sh) {
    sh.querySelectorAll(".pp-chart").forEach(drawChart);
    if (window.__arrows) window.__arrows(sh);
  });
}
function colorList() {
  var l = CD.sets.slice();
  if (!CD.current.name) l.unshift({name: "今の色", note: "設計図・テンプレートの色", accent: CD.current.accent, emphasis: CD.current.emphasis, vars: CD.current.vars});
  return l;
}
function paintColorButtons() { CBTNS.forEach(function (b) { b[0].setAttribute("aria-pressed", String(sameColor(b[1], COLOR))); }); }
function chooseColor(c) {
  COLOR = c;
  applyColor(c);
  paintColorButtons();
  try { localStorage.setItem(CKEY, JSON.stringify({accent: c.accent, emphasis: c.emphasis})); } catch (e) {}
}
(function () {
  var box = $("rv-color-panel"), row = h("div", {class: "rv-color-row", role: "group", "aria-label": "配色セット"});
  box.appendChild(h("span", {class: "rv-color-label", text: "配色", title: "選ぶと、全ページの案の色が変わります。「Claude に渡す」で、設計図の色に反映します"}));
  colorList().forEach(function (c) {
    var a = h("span", {class: "rv-chip"}), e = h("span", {class: "rv-chip"});
    a.style.background = c.accent; e.style.background = c.emphasis;
    var b = h("button", {class: "rv-cs", type: "button", "data-set": c.name, title: c.note || ""}, [a, e, h("span", {text: c.name})]);
    b.addEventListener("click", function () { chooseColor(c); });
    CBTNS.push([b, c]);
    row.appendChild(b);
  });
  box.appendChild(row);
  try {
    var sc = JSON.parse(localStorage.getItem(CKEY) || "null");
    var hit = sc && colorList().filter(function (c) { return sameColor(c, sc); })[0];
    if (hit) COLOR = hit;
  } catch (e) {}
  paintColorButtons();
})();
if (!sameColor(COLOR, CD.current)) applyColor(COLOR);  // 前回選んだ色（グラフは flush のあとに描き直す）
refresh();
function pick(nn, k) {
  var s = S[nn];
  if (s.pick === k) return;
  s.pick = k;
  touch(nn);
  setBig(nn);
  refresh();
}
// 「Claude に渡す」: 選択・承認・コメントを JSON にして、クリップボードへ。使えないときは欄に出して手でコピーしてもらう
// 貼り付けの途中で内容が変わっていないかを、取り込みが確かめる検査値（choices.checksum と同じ計算: UTF-8 の FNV-1a）
function fnv(str) {
  var b = new TextEncoder().encode(str), h = 0x811c9dc5;
  for (var i = 0; i < b.length; i++) { h ^= b[i]; h = Math.imul(h, 0x01000193) >>> 0; }
  return ("0000000" + h.toString(16)).slice(-8);
}
function payload() {
  var pages = {};
  order.forEach(function (nn) {
    var s = S[nn];
    if (s.pick || s.status || s.comment.trim() || INIT[nn]) {
      pages[nn] = {pick: s.pick, status: s.status || "saved", comment: s.comment.trim()};
      if (s.status === "approved" && s.fr) pages[nn].fr = s.fr;  // 承認したときに見ていた断片の指紋（承認のページだけ）
    }
    if (Object.keys(s.checks).length) {  // 人の確認が 1 つでもあるページだけ（なければ従来の形）
      pages[nn] = pages[nn] || {pick: s.pick, status: "saved", comment: ""};
      pages[nn].checks = cleanChecks(s.checks);
    }
    if (Object.keys(s.edits).length) {  // 編集のあるページだけ（なければ従来の形）。編集は承認を外す
      pages[nn] = pages[nn] || {pick: s.pick, status: "saved", comment: ""};
      pages[nn].status = "saved";
      delete pages[nn].fr;
      pages[nn].edits = s.edits;
    }
  });
  var out = {"pptx-maker-review": 1, base: STAMP, check: fnv(JSON.stringify(pages)), pages: pages};
  if (!sameColor(COLOR, CD.current)) out.color = {name: COLOR.name, accent: COLOR.accent, emphasis: COLOR.emphasis};  // 設計図の色と違うときだけ
  return JSON.stringify(out);
}
$("rv-bulk").addEventListener("click", bulkApprove);
$("share").addEventListener("click", async function () {
  var t = payload(), box = $("out"), st = $("st");
  box.value = t;
  try {
    await navigator.clipboard.writeText(t);
    box.hidden = true;
    st.textContent = "コピーしました。チャットに貼り付けてください。";
  } catch (e) {
    box.hidden = false;
    box.focus(); box.select();
    st.textContent = "自動でコピーできませんでした。下の欄を全選択してコピーし、チャットに貼り付けてください。";
  }
});
})();
</script>
"""


def _asset(work: Path, name: str) -> str:
    f = work / name
    if not f.exists():
        raise ValueError(f"{f} がありません（init で作業フォルダを作り直してください）")
    return paths.read_text(f)


def _data_uri(work: Path, ref: str, cache: dict[str, str]) -> str:
    """作業フォルダ内の画像を data URI にする。問題があれば ValueError（メッセージは理由だけ）。"""
    if ref in cache:
        return cache[ref]
    f = (work / ref).resolve()
    if not f.is_relative_to(work.resolve()):
        raise ValueError("作業フォルダの外です")
    mime = _MIME.get(f.suffix.lower())
    if mime is None:
        raise ValueError("対応していない拡張子です（PNG・JPEG・GIF・WebP・SVG のみ）")
    if not f.is_file():
        raise ValueError("ファイルがありません")
    cache[ref] = f"data:{mime};base64,{base64.b64encode(f.read_bytes()).decode('ascii')}"
    return cache[ref]


def _embed_images(work: Path, nn: str, key: str, frag: str, cache: dict[str, str], errors: list[str]) -> str:
    """断片の相対パスの画像を data URI に置き換える。data:・#id はそのまま（外部 URL・file: は collect が先に止める）。"""

    def attr(m: re.Match, tag: str) -> str:
        name, eq, q, ref = m.groups()
        is_img = tag.lower() == "img"
        if (name.lower() == "src") != is_img or re.match(r"data:|#", ref, re.IGNORECASE):
            return m.group(0)
        try:
            return f"{name}{eq}{q}{_data_uri(work, ref, cache)}{q}"
        except ValueError as e:
            errors.append(f"スライド {nn} の案 {key}: {ref}（{e}）")
            return m.group(0)

    return _IMG_TAG.sub(lambda t: _IMG_ATTR.sub(lambda m: attr(m, t.group(1)), t.group(0)), frag)


def _label(frag: str) -> str:
    """断片の data-variant（案の特徴。旧形式の「…｜案の特徴」も受ける）から、案の特徴の部分を返す。"""
    m = _VARIANT.search(frag)
    return htmllib.unescape(m.group(1)).split("｜", 1)[-1] if m else ""


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _TitleText(HTMLParser):
    """最初の data-role="title"・data-ph="title" の要素の文字を集める。"""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0  # 題の要素の中の深さ（0 は外）
        self.done = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self.done or tag in _VOID:
            return
        if self.depth:
            self.depth += 1
        elif ("data-role", "title") in attrs or ("data-ph", "title") in attrs:
            self.depth = 1

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        pass  # <br/> などは深さを変えない

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag not in _VOID:
            self.depth -= 1
            self.done = self.depth == 0

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def _title(frags: dict[str, str]) -> str:
    """案の断片から、ページの題（空白を詰め、TITLE_CHARS 字まで）を返す。なければ空文字。"""
    for frag in frags.values():
        p = _TitleText()
        p.feed(frag)
        text = " ".join("".join(p.parts).split())
        if text:
            return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1] + "…"
    return ""


def _script_safe(js: str) -> str:
    """<script> の中で終わりを見失わせない（</ と、<!--<script の組み合わせ）。どちらも JSON の文字列の中だけに現れる。"""
    return js.replace("</", "<\\/").replace("<!--", "\\u003c!--")


def _rules_blob(work: Path, cands: dict[str, dict[str, str]], measure: bool, notes: list[str]) -> str:
    """ルール一覧・縦読み・案のバッジのデータ（JSON）。script.md がない・読めないときは null（ページはルール表示を出さない）。
    script.md があるのに出せないとき（ルール設定の破損など）は、理由を notes に足す。"""
    try:
        data = consulting.evaluate(work, measure=measure)
        data["vertical"] = consulting.vertical_reading(work)
    except (ValueError, OSError) as e:
        if (work / "script.md").is_file():
            notes.append(f"ルール表示を出せません: {e}")
        return "null"
    if data.get("measure_error"):
        notes.append(f"R20・R23・R26 を測れませんでした（build のまま出します）: {data['measure_error']}")
    data["meta"] = {nn: {k: candidates.variant_meta(frag) for k, frag in c.items()} for nn, c in cands.items()}
    return _script_safe(json.dumps(data, ensure_ascii=False))


def _embedded_state(work: Path, cands: dict[str, dict[str, str]]) -> dict[str, dict]:
    """ページに埋め込む選択結果。承認した断片の指紋が今の断片と合わない承認済み（旧形式を含む）は、saved にして出す
    （利用者が見ていない断片が、承認のまま「Claude に渡す」で通るのを防ぐ。ディスクの choices/ は変えない）。"""
    state = choices.read_state(work)
    for nn, s in state.items():
        html = cands.get(nn, {}).get(s["pick"]) if isinstance(s["pick"], str) else None
        if s["status"] == "approved" and (html is None or choices.frag_of(work, nn) != choices.fragment_hash(html)):
            state[nn] = {**s, "status": "saved"}
    return state


def build(work: Path, measure: bool = True, notes: list[str] | None = None) -> Path:
    """`<work>/review.html` を書いて、そのパスを返す。案・派生ファイルが足りなければ ValueError。
    measure=True なら、案を測って R20・R23・R26 の結果を載せる（測れなければ build のままにして、理由を notes に足す）。"""
    notes = [] if notes is None else notes
    work = Path(work)
    cands = candidates.collect(work)
    cache: dict[str, str] = {}
    errors: list[str] = []
    embedded = [
        [
            nn,
            {k: _embed_images(work, nn, k, frag, cache, errors) for k, frag in c.items()},
            {k: _label(frag) for k, frag in c.items()},
            _title(c),
        ]
        for nn, c in sorted(cands.items())
    ]
    if errors:
        raise ValueError("画像を埋め込めません:\n" + "\n".join(errors))
    data = _script_safe(json.dumps(embedded, ensure_ascii=False))
    theme = _asset(work, "theme.css")
    subs = {
        "THEME": theme,
        "DATA": data,
        "RULES": _rules_blob(work, cands, measure, notes),
        "COLORS": _script_safe(json.dumps(color_sets.review_data(work), ensure_ascii=False)),
        "CHART": _asset(work, "chart-preview.js").replace("</script", "<\\/script"),
        # shadow root の CSS。テーマ（.slide[data-layout=…] の規則）・base.css・:host の書体
        "BASE": json.dumps(f"{theme}\n{_asset(work, 'base.css')}\n{_HOST_CSS}", ensure_ascii=False).replace(
            "</", "<\\/"
        ),
        "STATE": _script_safe(json.dumps(_embedded_state(work, cands), ensure_ascii=False)),
        "FR": _script_safe(
            json.dumps(
                {nn: {k: choices.fragment_hash(frag) for k, frag in c.items()} for nn, c in cands.items()},
                ensure_ascii=False,
            )
        ),
        "STAMP": choices.stamp(work),
    }
    # 1 回で置き換える（断片や CSS の中の __BASE__ などを、もう一度置き換えない）
    html = paths.CSP_REVIEW + _PLACEHOLDER.sub(lambda m: subs[m.group(1)], _PAGE)
    size = len(html.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        images = sum(len(u) for u in _DATA_URI.findall(html))  # 同じ画像も、ページに入った回数だけ数える
        raise ValueError(
            f"案を選ぶページが大きすぎます（{size / 1048576:.1f} MiB。上限 {MAX_PAGE_BYTES / 1048576:.0f} MiB）。"
            f"うち画像が {images / 1048576:.1f} MiB です。画像を小さくしてください"
        )
    out = work / "review.html"
    out.write_text(html, encoding="utf-8", newline="\n")
    return out
