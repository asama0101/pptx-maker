# ruff: noqa: S101  # pytest の assert
"""断片の安全検査（script・on* 属性・外部 URL）と、review.html・final.html の CSP。"""

import contextlib
import http.server
import socket
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from pptx_maker import candidates, cli, finalize, measure, paths, review_page

from tests._flow import write_choices

COMP = Path(__file__).resolve().parents[1] / "plugins" / "pptx-maker" / "assets" / "components"

BAD = {
    "script": "<div><script>fetch('x')</script></div>",
    "onerror": '<img src="a.png" onerror="fetch(1)">',
    "onclick": '<div onClick="x()">a</div>',
    "外部画像": '<img src="http://127.0.0.1:8765/x">',
    "外部リンク": '<a href="https://example.com/">a</a>',
    "javascript": '<a href="javascript:alert(1)">a</a>',
    "css url": '<div style="background:url(https://a/b.png)">a</div>',
    "style 要素": "<style>@import url(http://a/b.css);</style><div>a</div>",
    "iframe srcdoc": "<iframe srcdoc=\"<script>top.location='http://x/'</script>\"></iframe>",
    "iframe javascript タブ": '<iframe src="java&#9;script:top.location=1"></iframe>',
    "javascript タブ": '<a href="java	script:x()">a</a>',
    "javascript 改行": '<a href="java&#10;script:x()">a</a>',
    "javascript 制御文字": '<a href="javascript:x()">a</a>',
    "http タブ": '<img src="ht&#9;tp://127.0.0.1:1/x">',
    "http 大文字": '<img src="HTTP://127.0.0.1:1/x">',
    "プロトコル相対": '<img src="//127.0.0.1:1/x">',
    "バックスラッシュ": r'<img src="\\127.0.0.1\x">',
    "data text": '<a href="data:text/html,<b>x</b>">a</a>',
    "file host": '<img src="file://host/x.png">',
    "file": '<img src="file:///C:/x.png">',
    "blob": '<a href="blob:null/x">a</a>',
    "ftp": '<a href="ftp://h/x">a</a>',
    "svg a": '<svg><a xlink:href="ht&#9;tp://h/x"><text>a</text></a></svg>',
    "meta refresh": '<meta http-equiv="refresh" content="0;url=http://h/">',
    "base": '<base target="_top"><div>a</div>',
    "link prefetch": '<link rel="prefetch" href="x.png">',
    "object": '<object data="x.png"></object>',
    "form": '<form action="x"><input></form>',
    "srcset 2つ目": '<img srcset="a.png 1x, http://h/b.png 2x">',
    "ping": '<a ping="http://h/p" href="#">a</a>',
    "image-set": "<div style=\"background:image-set('http://h/a' 1x)\">a</div>",
    "css エスケープ": r'<div style="background:u\72l(http://h/a)">a</div>',
    "css import エスケープ": r"<style>@\69mport 'http://h/a';</style>",
    "css コメント": "<style>@im/**/port 'http://h/a';</style>",
    "style 内の要素": "<svg><style><script>x()</script></style></svg>",
    "スラッシュ区切りの onerror": '<img/src=x/onerror="x()">',
    "CDATA": "<![CDATA[><img src=x onerror=x()>]]>",
    "javascript 数値参照の制御文字": '<a href="&#1;javascript:x()">a</a>',
    "javascript 実制御文字（生）": '<a href="\x01javascript:x()">a</a>',
    "本文の javascript": "<p>javascript:</p>",
    "svg title の meta": '<svg><title><meta http-equiv=refresh content="0;url=http://h/m"></title></svg>',
    "svg title の a": '<svg><title><a id=x href="http://h/p">a</a></title></svg>',
    "空コメントの後の meta": '<!--><meta http-equiv=refresh content="0;url=http://h/m">-->',
    "コメント !>": '<!--!><meta http-equiv=refresh content="0;url=http://h/m">-->',
    "コメント ->": "<!---><img src=x onerror=x()>-->",
    "コメント --!>": "<!-- a --!><img src=x onerror=x()> -->",
    "svg textarea の script": "<svg><textarea><script>x()</script></textarea></svg>",
    "xmp": "<xmp><img src=http://h/x>",
    "plaintext": "<plaintext><img src=http://h/x>",
    "noscript": "<noscript><p title='</noscript><img src=http://h/x>'></noscript>",
    "template": "<template><img src=http://h/x></template>",
    "math": "<math><mtext><table><mglyph><style><img src=http://h/x onerror=x()>",
    "コメント内の meta": '<!-- <meta http-equiv="refresh" content="0;url=http://h/"> -->',
    "コメント内の javascript": "<!-- javascript:x() -->",
    "style 内の <": "<svg><style>a{} <img src=x onerror=x()></style></svg>",
    "css image(": "<div style=\"background:image('http://h/a')\">a</div>",
    "css expression": '<div style="width:expression(x())">a</div>',
    "mailto": '<a href="mailto:a@b">a</a>',
    "tel": '<a href="tel:123">a</a>',
}


def _work(tmp_path: Path, frag: str = "<div>ok</div>") -> Path:
    s = tmp_path / "slides"
    s.mkdir()
    (s / "01-R1.html").write_text(frag, encoding="utf-8")
    (s / "01-R2.html").write_text("<div>ok2</div>", encoding="utf-8")
    for n, body in (("theme.css", ":root{--bg:#fff;}"), ("base.css", ""), ("chart-preview.js", "")):
        (tmp_path / n).write_text(body, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("frag", BAD.values(), ids=BAD.keys())
def test_unsafe_fragment_is_error(tmp_path, frag):
    with pytest.raises(ValueError, match=r"01-R1\.html: "):
        candidates.collect(_work(tmp_path, frag))


def test_all_unsafe_reported_together(tmp_path):
    w = _work(tmp_path, BAD["script"] + BAD["onerror"])
    (w / "slides" / "01-R2.html").write_text(BAD["外部画像"], encoding="utf-8")
    with pytest.raises(ValueError, match="01-R1.html") as e:
        candidates.collect(w)
    msg = str(e.value)
    assert "01-R1.html" in msg
    assert "01-R2.html" in msg


def test_namespace_and_local_urls_pass(tmp_path):
    frag = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<use xlink:href="#a"/></svg><img src="material/a.png"><p>on=1 http://x</p>'
    )
    assert "01" in candidates.collect(_work(tmp_path, frag))


@pytest.mark.parametrize("f", sorted(COMP.rglob("*.html")), ids=lambda f: f.name)
def test_component_samples_are_safe(f):
    assert candidates.unsafe_parts(f.read_text(encoding="utf-8")) == []


def test_review_page_has_csp(tmp_path):
    html = review_page.build(_work(tmp_path)).read_text(encoding="utf-8")
    assert html.startswith(paths.CSP_REVIEW)
    assert "connect-src 'none'" in html
    assert "img-src data:;" in html


def test_final_html_has_csp(tmp_path):
    w = _work(tmp_path, "<section>ONE</section>")
    (w / "slides" / "01-R2.html").write_text("<section>TWO</section>", encoding="utf-8")
    ch = write_choices(tmp_path / "ch", {"01": "R1"}, w)
    html = finalize.finalize(w, ch).read_text(encoding="utf-8")
    assert paths.CSP_FILE in html
    assert "connect-src 'none'" in html


OK = {
    "相対パス": '<img src="material/a.png"><img src="./b.png"><a href="a/b?c:d#e">a</a>',
    "#id": '<svg><use href="#i-x"/><use xlink:href="#i-y"/></svg>',
    "data image": '<img src="data:image/png;base64,AAAA"><i style="background:url(data:image/png;base64,AAAA)">a</i>',
    "css url 相対": "<div style=\"background:url('material/a.png')\">a</div><style>/* c */ .a{fill:url(#m)}</style>",
    "srcset 相対": '<img srcset="a.png 1x, b.png 2x">',
    "内容の文字": "<p>http://x on=1 &lt;meta&gt;</p>",
    "属性値の /on": '<img alt="a/onx=1" title="/onerror=" src="a.png">',
    "on で始まる名前": '<div data-one="1">a</div>',
    "svg の図形": (
        '<svg viewBox="0 0 9 9"><defs><linearGradient id="g"/></defs><path d="M0 0L9 9" fill="url(#g)"/></svg>'
    ),
}


@pytest.mark.parametrize("frag", OK.values(), ids=OK.keys())
def test_safe_fragment_passes(frag):
    assert candidates.unsafe_parts(frag) == []


def test_error_names_tag_line_and_fix(tmp_path):
    with pytest.raises(ValueError, match="直し方: 画像は作業フォルダの相対パス") as e:
        candidates.collect(_work(tmp_path, "<div>a</div>\n<iframe></iframe>"))
    assert "01-R1.html: 2 行目: <iframe>" in str(e.value)


def test_as_page_has_csp(tmp_path):
    w = _work(tmp_path, "<section>a</section>")
    with cli._as_page(w / "slides" / "01-R1.html", w) as page:
        html = page.read_text(encoding="utf-8")
    assert paths.CSP_FILE in html
    assert html.index(paths.CSP_FILE) < html.index("<base ")


def test_csp_blocks_frames_objects_and_inline_handlers():
    assert "frame-src 'none'" in paths.CSP_REVIEW
    assert "object-src 'none'" in paths.CSP_REVIEW
    assert "base-uri 'none'" in paths.CSP_REVIEW
    assert "script-src-attr 'none'" in paths.CSP_REVIEW
    assert "frame-src 'none'" in paths.CSP_FILE
    assert "object-src 'none'" in paths.CSP_FILE


def test_all_samples_pass_checks():
    """assets の見本（部品・絵・アイコン）が誤検出されない。"""
    root = COMP.parent
    files = [*root.rglob("*.html"), *root.rglob("*.svg")]
    assert files
    for f in files:
        assert candidates.unsafe_parts(f.read_text(encoding="utf-8")) == [], f.name


@pytest.mark.parametrize("unit", ["url(", "url(a", "/*", '<i style="background:url(">'])
def test_many_unclosed_urls_are_fast(unit):
    t = time.perf_counter()
    candidates.unsafe_parts("<style>" + unit * 8000 + "</style>")
    assert time.perf_counter() - t < 0.5


def test_css_error_names_the_word():
    msg = "\n".join(candidates.unsafe_parts("<div style=\"background:image('a')\">a</div>"))
    assert "image(" in msg
    msg = "\n".join(candidates.unsafe_parts(r'<style>a:before{content:"\2022"}</style>'))
    assert "文字を直接書く" in msg


def test_measure_blocks_network_and_navigation(tmp_path):
    """検査を外して直接測っても、meta refresh・画像は 127.0.0.1 の待ち受けに届かない。"""
    hits: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    u = f"127.0.0.1:{srv.server_address[1]}"
    f = tmp_path / "m.html"
    f.write_text(
        f'<!doctype html><html><head><meta http-equiv="refresh" content="0;url=http://{u}/m"></head><body>'
        f'<img src="http://{u}/i"><section class="slide" style="width:1280px;height:720px">a</section></body></html>',
        encoding="utf-8",
    )
    try:
        with contextlib.suppress(ValueError, PlaywrightError):  # 遷移の中断で測れなくてもよい。届かないことが本題
            measure.measure(f)
        time.sleep(0.5)
    finally:
        srv.shutdown()
        srv.server_close()
    assert hits == []


class _Route:
    """Playwright の route の代わり。continue_・abort のどちらが呼ばれたかだけを残す。"""

    def __init__(self, url: str) -> None:
        self.request = type("R", (), {"url": url})()
        self.result = ""

    def continue_(self) -> None:
        self.result = "continue"

    def abort(self) -> None:
        self.result = "abort"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///C:/work/final.html", "continue"),
        ("file://localhost/C:/work/theme.css", "continue"),
        ("data:image/png;base64,AAAA", "continue"),
        ("about:blank", "continue"),
        ("file://127.0.0.9/share/x.png", "abort"),
        ("file://evil.example/share/x.css", "abort"),
        ("file:////evil.example/share/x.png", "abort"),
        ("file:///%2F%2Fevil.example/share/x.png", "abort"),
        ("file:///\\evil.example/share/x.png", "abort"),
        ("http://127.0.0.1:1/x", "abort"),
        ("ws://127.0.0.1:1/x", "abort"),
    ],
)
def test_only_local_blocks_unc_and_remote(url, expected):
    """測定側の遮断は、ホスト名つきの file: と UNC になる形も中断する（SMB で認証情報が送られうる）。"""
    r = _Route(url)
    measure._only_local(r)
    assert r.result == expected


_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8"></head><body>{body}'
    '<section class="slide" style="width:1280px;height:720px">a</section></body></html>'
)


def _listen(port: int = 0) -> tuple[socket.socket, list[bytes]]:
    """127.0.0.9 で待ち受け、届いた接続の先頭バイトを記録する（外のホストには接続しない）。"""
    srv = socket.socket()
    srv.bind(("127.0.0.9", port))
    srv.listen()
    srv.settimeout(0.2)
    got: list[bytes] = []
    stop = threading.Event()

    def run():
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except OSError:
                continue
            got.append(c.recv(16))
            c.close()

    threading.Thread(target=run, daemon=True).start()
    srv.stop = stop.set  # type: ignore[attr-defined]
    return srv, got


def test_measure_blocks_unc_style_urls_in_real_chromium(tmp_path, monkeypatch):
    """実際の Chromium の URL 正規化を通しても、127.0.0.9 への file: は中断される。
    445 はシステムの SMB が持つので待ち受けられない。代わりに、Chromium が route に渡す URL の判定を記録する。
    待ち受けが取れる環境（445 が空き）では、届かないことも確かめる。"""
    seen: list[tuple[str, bool]] = []
    orig = measure._only_local

    def spy(route):
        r = _Route(route.request.url)
        orig(r)
        seen.append((r.request.url, r.result == "abort"))
        orig(route)

    monkeypatch.setattr(measure, "_only_local", spy)
    try:
        srv, got = _listen(445)
    except OSError:
        srv, got = None, []
    f = tmp_path / "unc.html"
    f.write_text(
        _PAGE.format(
            body="<svg><style>a{background:u&#114;l(//127.0.0.9/share/x.png)}</style></svg>"
            '<img src="file:////127.0.0.9/share/x.png"><img src="file://127.0.0.9/share/y.png">'
        ),
        encoding="utf-8",
    )
    try:
        measure.measure(f)
        time.sleep(0.5)
    finally:
        if srv:
            srv.stop()
            srv.close()
    remote = [(u, aborted) for u, aborted in seen if "127.0.0.9" in u]
    assert remote
    assert all(aborted for _, aborted in remote)
    assert got == []


def test_measure_blocks_popup_and_websocket(tmp_path):
    """window.open の先と WebSocket は、page.route では止まらない。context の遮断で止める。"""
    hits: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.9", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    u = f"127.0.0.9:{srv.server_address[1]}"
    f = tmp_path / "p.html"
    f.write_text(
        _PAGE.format(body=f"<script>window.open('http://{u}/popup');new WebSocket('ws://{u}/x');</script>"),
        encoding="utf-8",
    )
    try:
        measure.measure(f)
        time.sleep(0.7)
    finally:
        srv.shutdown()
        srv.server_close()
    assert hits == []


def test_measure_works_in_non_ascii_work_dir(tmp_path):
    """通常の file:/// の測定は、日本語・空白を含む作業フォルダでも成功する。"""
    d = tmp_path / "作業 フォルダ"
    d.mkdir()
    f = d / "final.html"
    f.write_text(_PAGE.format(body=""), encoding="utf-8")
    assert len(measure.measure(f)) == 1


def test_measure_rejects_unc_work_dir():
    """UNC の作業フォルダは、接続せずに明示的なエラーにする。"""
    with pytest.raises(ValueError, match="UNC"):
        measure.measure(Path(r"\\srv\share\work\final.html"))


def test_check_not_unc_rejects_unc_forms():
    """先頭が 2 本のバックスラッシュの形（拡張パスの UNC や、スラッシュ区切りも）は断る。"""
    for p in (r"\\srv\share\w", "//srv/share/w", r"\\?\UNC\srv\share\w"):
        with pytest.raises(ValueError, match="UNC"):
            measure.check_not_unc(Path(p))


def test_check_not_unc_rejects_path_resolving_to_unc(monkeypatch):
    """Z: のようなネットワークドライブは、resolve すると UNC になる。そのときも断る。"""
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: Path(r"\\srv\share\x"))
    with pytest.raises(ValueError, match="UNC"):
        measure.check_not_unc(Path(r"Z:\w\final.html"))


def test_as_page_rejects_unc_work_dir(tmp_path):
    """断片の測定（review-page・check）も、UNC の作業フォルダは明示的なエラーにする。"""
    from pptx_maker import cli

    frag = tmp_path / "01-R1.html"
    frag.write_text('<section class="slide">a</section>', encoding="utf-8")
    with pytest.raises(ValueError, match="UNC"), cli._as_page(frag, Path(r"\\srv\share\w")):  # noqa: SLF001
        pass
