() => {
  const px = (v) => parseFloat(v) || 0;
  const hex2 = (n) => Math.round(n).toString(16).padStart(2, '0').toUpperCase();
  const parseColor = (c) => {
    c = c || '';
    let m = /rgba?\(([^)]+)\)/.exec(c);
    if (m) {
      const [r, g, b, a = 1] = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
      return { hex: hex2(r) + hex2(g) + hex2(b), a };
    }
    m = /color\(srgb ([^)]+)\)/.exec(c);       // color-mix() の結果は color(srgb r g b / a) で返る
    if (m) {
      const [r, g, b, a = 1] = m[1].split(/[ \/]+/).filter(Boolean).map(Number);
      return { hex: hex2(r * 255) + hex2(g * 255) + hex2(b * 255), a };
    }
    return null;
  };
  const slides = [...document.querySelectorAll('section.slide')];

  return slides.map((slide, si) => {
    const sr = slide.getBoundingClientRect();
    const rel = (r) => ({ x: r.left - sr.left, y: r.top - sr.top, w: r.width, h: r.height });
    const els = [...slide.querySelectorAll('.pp-text,.pp-shape,.pp-line,.pp-image,.pp-table,.pp-chart,.pp-picture')];

    const runsOf = (block) => {
      const runs = [];
      const walk = (node) => {
        if (node.nodeType === 3) {
          const t = node.textContent.replace(/\s+/g, ' ');
          if (!t.trim() && !runs.length) return;
          const cs = getComputedStyle(node.parentElement);
          runs.push({
            text: t, size_px: px(cs.fontSize), bold: parseInt(cs.fontWeight) >= 600,
            italic: cs.fontStyle === 'italic', color: (parseColor(cs.color) || { hex: '000000' }).hex,
          });
        } else if (node.nodeType === 1) {
          if (node.tagName === 'BR') { runs.push({ br: true }); return; }
          if (node.tagName === 'UL' || node.tagName === 'OL') return;
          node.childNodes.forEach(walk);
        }
      };
      block.childNodes.forEach(walk);
      const first = runs.find((r) => r.text !== undefined);
      if (first) first.text = first.text.replace(/^\s+/, '');
      const last = [...runs].reverse().find((r) => r.text !== undefined);
      if (last) last.text = last.text.replace(/\s+$/, '');
      return runs.filter((r) => r.br || r.text);
    };

    const alignOf = (cs) => {
      const a = cs.textAlign;
      return a === 'center' || a === 'right' || a === 'justify' ? a : a === 'end' ? 'right' : 'left';
    };

    // 行ボックス（line-height の高さ）の行ごとの中心。Range の矩形は文字そのものの範囲で、行間の余りを含まない
    const linesOf = (b, lpx) => {
      const range = document.createRange();
      range.selectNodeContents(b);
      const rs = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0)
        .map((r) => ({ top: r.top - sr.top, bottom: r.bottom - sr.top, left: r.left - sr.left, right: r.right - sr.left }))
        .sort((a, c) => (a.top + a.bottom) - (c.top + c.bottom));
      const lines = [];
      for (const r of rs) {
        const cy = (r.top + r.bottom) / 2;
        const last = lines[lines.length - 1];
        if (last && cy - last.cy <= lpx * 0.5) {
          last.top = Math.min(last.top, r.top); last.bottom = Math.max(last.bottom, r.bottom);
          last.left = Math.min(last.left, r.left); last.right = Math.max(last.right, r.right);
        } else lines.push({ cy, top: r.top, bottom: r.bottom, left: r.left, right: r.right });
      }
      return lines;
    };

    // withDiv: pp-text では直下の div も段落として取る（表のセルは従来どおり）。display が inline 系の div は行内の文字として扱う
    const parasOf = (el, withDiv = false) => {
      let blocks = [...el.querySelectorAll(':scope > p, :scope > ul > li, :scope > ol > li' + (withDiv ? ', :scope > div' : ''))]
        .filter((b) => b.tagName !== 'DIV' || !getComputedStyle(b).display.startsWith('inline'));
      if (!blocks.length) blocks = [el];
      return blocks.map((b) => {
        const cs = getComputedStyle(b);
        const fs = px(cs.fontSize);
        const lh = cs.lineHeight === 'normal' ? 1.2 : px(cs.lineHeight) / fs;
        const para = {
          align: alignOf(cs), bullet: b.tagName === 'LI', lh, mb: px(cs.marginBottom),
          runs: runsOf(b),
        };
        if (withDiv) {
          const lpx = lh * fs;
          const ls = linesOf(b, lpx);
          const lastLine = ls[ls.length - 1] || null;
          Object.assign(para, { lpx, lines: ls.length, first: ls[0] || null, last: lastLine, lastW: lastLine ? lastLine.right - lastLine.left : 0 });
        }
        return para;
      }).filter((p) => p.runs.length);
    };

    const base = (el, kind, idx) => {
      const r = rel(el.getBoundingClientRect());
      return {
        kind, idx, rect: r, role: el.dataset.role || null, ph: el.dataset.ph || null,
        overlap: el.dataset.overlap !== undefined, chrome: el.dataset.chrome !== undefined,
        family: getComputedStyle(el).fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, ''),
      };
    };

    const borderOf = (cs, side) => {
      const w = px(cs['border' + side + 'Width']);
      const c = parseColor(cs['border' + side + 'Color']);
      return w > 0 && cs['border' + side + 'Style'] !== 'none' && c && c.a > 0 ? { hex: c.hex, w } : null;
    };

    // 破線・点線は border-top（横線）か、なければ border-left（縦線 vl）から読む。pp-shape は border-top のまま
    const dashSide = (cs) => (cs.borderTopStyle === 'dashed' || cs.borderTopStyle === 'dotted') ? 'Top'
      : (cs.borderLeftStyle === 'dashed' || cs.borderLeftStyle === 'dotted') ? 'Left' : null;
    const dashOf = (cs) => { const s = dashSide(cs); if (!s) return null; const v = cs['border' + s + 'Style']; return v === 'dashed' ? 'dash' : 'sysDot'; };

    const elements = els.map((el, idx) => {
      const cs = getComputedStyle(el);
      if (el.classList.contains('pp-text')) {
        const e = base(el, 'text', idx);
        const range = document.createRange();
        range.selectNodeContents(el);
        const cr = range.getBoundingClientRect();
        const crr = rel(cr);
        const padL = px(cs.paddingLeft), padR = px(cs.paddingRight);
        if (cr.width === 0 && cr.height === 0) {
          // 中身が空だと範囲の矩形が (0,0) になるので、要素の位置を使う
          e.box = { x: e.rect.x + padL, y: e.rect.y + px(cs.paddingTop), w: e.rect.w - padL - padR, h: 0 };
          e.overflow = false;
        } else {
          e.box = { x: e.rect.x + padL, y: crr.y, w: e.rect.w - padL - padR, h: crr.h };
          e.overflow = crr.x + crr.w > e.rect.x + e.rect.w + 2;
        }
        e.paras = parasOf(el, true);
        // 行ボックスの範囲（lbox）。最初の行の上端から最後の行の下端まで。行間の余りの半分（lead）は、文字の範囲の上にある
        const p0 = e.paras.find((p) => p.first), p1 = [...e.paras].reverse().find((p) => p.last);
        e.lbox = e.box;
        e.lead = 0;
        if (p0 && p1) {
          const top = p0.first.cy - p0.lpx / 2, bottom = p1.last.cy + p1.lpx / 2;
          e.lbox = { x: e.box.x, y: top, w: e.box.w, h: bottom - top };
          e.lead = (p0.lpx - (p0.first.bottom - p0.first.top)) / 2;
          e.overflow = e.overflow || bottom > e.rect.y + e.rect.h + 2;
        }
        e.placed = el.style.top !== '' && el.style.height !== '';   // 題・副題（data-ph）が style で位置を明示しているか
        // 取りこぼした文字: 全文字（空白を除く）のうち、runs に取り込めなかったものを並べる（入れ子の ul、p と混ざった裸の文字など）
        const got = new Map();
        for (const ch of e.paras.flatMap((p) => p.runs.map((r) => r.text || '')).join('').replace(/\s/g, '')) got.set(ch, (got.get(ch) || 0) + 1);
        e.lost = '';
        for (const ch of el.textContent.replace(/\s/g, '')) {
          if (got.get(ch)) got.set(ch, got.get(ch) - 1); else e.lost += ch;
        }
        return e;
      }
      if (el.classList.contains('pp-shape')) {
        const e = base(el, 'shape', idx);
        const f = parseColor(cs.backgroundColor);
        const radius = px(cs.borderTopLeftRadius);
        e.shape = el.dataset.shape || (radius > 0 ? 'round' : 'rect');
        e.fill = f && f.a > 0 ? f : null;
        e.line = borderOf(cs, 'Top');
        e.dash = e.line ? dashOf(cs) : null;
        e.radius_px = radius;
        return e;
      }
      if (el.classList.contains('pp-line')) {
        const e = base(el, 'line', idx);
        e.fill = parseColor(cs.backgroundColor) || { hex: '000000', a: 1 };
        e.dash = dashOf(cs);
        const bt = borderOf(cs, dashSide(cs) || 'Top');
        e.w = bt ? bt.w : null;
        if (e.dash && bt) e.fill = { hex: bt.hex, a: 1 };   // 破線・点線は border-top（縦線 vl は border-left）の色で描かれる
        e.arrow = el.dataset.arrow === 'end';
        e.reverse = el.dataset.dir === 'rev';      // 矢印を逆向き（右→左、下→上）にする
        e.diag = el.dataset.dir === 'diag' ? 'down' : el.dataset.dir === 'diag-up' ? 'up' : null;   // 斜め線（左上→右下、左下→右上）。太さは border-top か 3px
        return e;
      }
      if (el.classList.contains('pp-image')) {
        const e = base(el, 'image', idx);
        e.src = el.currentSrc || el.getAttribute('src') || '';
        e.alt = el.getAttribute('alt') || '';
        return e;
      }
      if (el.classList.contains('pp-picture')) {
        // 絵: インライン SVG を 1 枚の画像にして貼る（画像にするのは measure.py）。ここでは位置と代替テキストだけを測る。
        const e = base(el, 'picture', idx);
        e.alt = el.dataset.alt || '';
        return e;
      }
      if (el.classList.contains('pp-chart')) {
        const e = base(el, 'chart', idx);
        try { e.chart = JSON.parse(el.dataset.chart); }
        catch (err) { e.chart = { type: null, _error: String(err && err.message || err) }; }
        return e;
      }
      // pp-table
      const e = base(el, 'table', idx);
      const cells = [...el.querySelectorAll('td,th')].map((c) => rel(c.getBoundingClientRect()));
      const xs = [...new Set(cells.flatMap((c) => [Math.round(c.x), Math.round(c.x + c.w)]))].sort((a, b) => a - b);
      const rows = [...el.rows].map((tr) => ({
        h: tr.getBoundingClientRect().height,
        cells: [...tr.cells].map((td) => {
          const r = rel(td.getBoundingClientRect());
          const tcs = getComputedStyle(td);
          const f = parseColor(tcs.backgroundColor);
          const c0 = xs.indexOf(Math.round(r.x));
          const c1 = xs.indexOf(Math.round(r.x + r.w));
          return {
            c0, c1, rowspan: td.rowSpan || 1,
            fill: f && f.a > 0 ? f : null,
            borders: { l: borderOf(tcs, 'Left'), r: borderOf(tcs, 'Right'), t: borderOf(tcs, 'Top'), b: borderOf(tcs, 'Bottom') },
            pad: { l: px(tcs.paddingLeft), r: px(tcs.paddingRight), t: px(tcs.paddingTop), b: px(tcs.paddingBottom) },
            valign: tcs.verticalAlign === 'top' || tcs.verticalAlign === 'bottom' ? tcs.verticalAlign : 'middle',
            paras: parasOf(td),
          };
        }),
      }));
      e.table = { xs, rows };
      return e;
    });
    return { index: si + 1, layout: slide.dataset.layout || 'content', elements };
  });
}
