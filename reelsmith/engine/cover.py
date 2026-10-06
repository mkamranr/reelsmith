"""9:16 cover image. Headline lives inside the 3:4 centre crop Instagram uses for the profile grid."""
import math
import re

import skia

from .lib import *
from .highlight import highlight
from .scenes import mark, initials, split_name, draw_tokens, S, window
from .timeline import Timeline

CW, CH = 1080, 1350
SAMP = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear)


def _card(scene, name, footer):
    """Render one scene's content as a static 1080x1350 'slide' image."""
    surf = skia.Surface(CW, CH); c = surf.getCanvas()
    c.drawColor(col(TH.panel))
    sh = skia.GradientShader.MakeRadial(skia.Point(80, 80), 900, [col(TH.acc, 0.16), col(TH.acc, 0)])
    c.drawRect(skia.Rect.MakeWH(CW, CH), skia.Paint(Shader=sh))
    rrect(c, 0, 0, CW, 12, 0, shader=acc_grad(0, 0, CW, 0))
    rrect(c, 90, 150, 36, 6, 3, TH.acc)
    text(c, name.upper()[:28], 142, 162, M(800, 30), TH.muted, track=4)
    k = scene['type']
    head = S(scene, 'caption') or S(scene, 'title') or S(scene, 'text') or S(scene, 'big') or ' '.join(scene.get('lines') or [])
    y = 280
    if k in ('rank', 'chapter'):
        num = S(scene, 'rank') or S(scene, 'number')
        text(c, num, 90, 520, I(900, 300), TH.acc, track=-6)
        y = 640
    if k == 'quote':
        text(c, '\u201c', 70, 470, I(800, 300), TH.acc)
        y = 520
    if head:
        sz, lines = fit_block(head, 'inter', 800, 900, 84, 2, 40, -0.02)
        for ln in lines:
            text(c, ln, 90, y, I(800, sz), TH.text, track=-sz * 0.02); y += sz * 1.12
        y += 40
    if k == 'code':
        ls = scene.get('lines', [])[:12]
        L = max([len(l) for l in ls] + [1]); size = int(min(38, 0.95 * 820 / (0.6 * L)))
        bh = len(ls) * size * 1.6 + 90
        rrect(c, 90, y, 900, bh, 26, TH.codebg); rrect(c, 90, y, 900, bh, 26, TH.border, stroke=2)
        for i, l in enumerate(ls):
            draw_tokens(c, highlight(l, scene.get('language', 'code')), 130, y + 70 + i * size * 1.6, size)
    elif k in ('bullets', 'steps', 'features'):
        items = scene.get('items') or scene.get('steps') or []
        for i, it in enumerate(items[:5]):
            t = it.get('title', '') if isinstance(it, dict) else str(it)
            rrect(c, 90, y, 900, 130, 26, TH.surf); rrect(c, 90, y, 900, 130, 26, TH.border, stroke=2)
            rrect(c, 120, y + 30, 70, 70, 18, TH.acc_bg)
            text(c, str(i + 1), 155, y + 80, I(800, 36), TH.acc, 1, 'c')
            fs = fit_size(t, 'inter', 700, 740, 42, 22)
            text(c, t, 220, y + 80, I(700, fs), TH.text); y += 152
    elif k == 'stats':
        for it in scene.get('items', [])[:3]:
            vs = fit_size(it['value'], 'inter', 900, 880, 160, 50)
            text(c, it['value'], 90, y + vs * 0.8, I(900, vs), TH.acc, track=-vs * 0.03)
            text(c, it['label'], 90, y + vs * 0.8 + 60, I(600, 40), TH.text); y += vs + 120
    elif k == 'terminal':
        cmd = '$ ' + S(scene, 'command')
        size = int(min(36, 0.95 * 820 / (0.6 * max(len(cmd), 1))))
        rrect(c, 90, y, 900, 260, 26, TH.codebg); rrect(c, 90, y, 900, 260, 26, TH.border, stroke=2)
        draw_tokens(c, highlight(cmd, 'sh'), 130, y + 90, size)
        for i, o in enumerate(scene.get('outputs', [])[:3]):
            text(c, o, 130, y + 150 + i * size * 1.5, M(500, size), TH.green if o.startswith('✓') else TH.muted)
    else:
        sub = S(scene, 'sub') or S(scene, 'tagline') or S(scene, 'punch')
        if sub:
            sz, lines = fit_block(sub, 'inter', 500, 900, 46, 4, 26)
            for ln in lines: text(c, ln, 90, y, I(500, sz), TH.muted); y += sz * 1.35
    line(c, 90, CH - 130, CW - 90, CH - 130, TH.border, 1, 2)
    circle(c, 98, CH - 72, 8, TH.acc)
    text(c, footer[:40], 122, CH - 60, I(500, 32), TH.muted)
    return surf.makeImageSnapshot().withDefaultMipmaps()


def _card3d(c, img, cx, cy, d, cw=540, ch=675):
    ad = abs(d)
    x3 = math.copysign(min(ad, 1) * cw * 0.56 + max(ad - 1, 0) * cw * 0.28, d)
    z3 = min(ad, 1) * 320 + max(ad - 1, 0) * 140
    pts = [(x + x3, y, z + z3) for x, y, z in roty([(-cw / 2, -ch / 2, 0), (cw / 2, -ch / 2, 0), (cw / 2, ch / 2, 0), (-cw / 2, ch / 2, 0)], -clamp(d, -1, 1) * 52)]
    m = skia.Matrix(); m.setPolyToPoly([skia.Point(0, 0), skia.Point(CW, 0), skia.Point(CW, CH), skia.Point(0, CH)], project_quad(pts, cx, cy))
    rr = skia.RRect.MakeRectXY(skia.Rect.MakeWH(CW, CH), 40, 40)
    c.save(); c.concat(m)
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(0, 60, CW, CH), 40, 40), paint((0, 0, 0), .6 * TH.shadow_alpha, blur=60))
    c.save(); c.clipRRect(rr, skia.ClipOp.kIntersect, True)
    c.drawImageRect(img, skia.Rect.MakeWH(CW, CH), SAMP)
    if ad > 0: c.drawRect(skia.Rect.MakeWH(CW, CH), paint(TH.bg[:3], clamp(ad * 0.32, 0, 0.7)))
    c.restore()
    c.drawRRect(rr, paint((60, 74, 90), 0.7, stroke=3))
    c.restore()


# ------------------------------------------------------------------ cover layouts
STYLES = ['stack', 'headline', 'device', 'split', 'magazine', 'poster', 'breaking', 'terminal', 'sticker', 'minimal']
STYLE_NAMES = {'stack': 'Card stack', 'headline': 'Big headline', 'device': 'Phone mockup', 'split': 'Split', 'magazine': 'Magazine',
               'poster': 'Film poster', 'breaking': 'Breaking news', 'terminal': 'Terminal', 'sticker': 'Stickers', 'minimal': 'Minimal'}
TEMPLATE_COVER = {'midnight': 'stack', 'editorial': 'magazine', 'terminal': 'terminal', 'pop': 'sticker', 'minimal': 'minimal',
                  'aurora': 'headline', 'cinema': 'poster', 'showcase': 'device', 'broadcast': 'breaking'}


def default_style(sb):
    return TEMPLATE_COVER.get(sb.get('template') or 'midnight', 'stack')


def alternatives(sb, chosen, n=2):
    """Two contrasting layouts to offer next to the chosen one."""
    has_page = any(x['type'] == 'scroll' for x in sb['scenes'])
    pref = ['headline', 'device' if has_page else 'split', 'split', 'stack', 'minimal']
    out = []
    for st in pref:
        if st != chosen and st not in out: out.append(st)
    return out[:n]


def _hook(sb):
    co = next((x for x in sb['scenes'] if x['type'] == 'coldopen'), None)
    if co: return co.get('text', ''), co.get('accent', '')
    if sb.get('hook_line'): return sb['hook_line'].get('text', ''), sb['hook_line'].get('accent', '')
    cv = sb.get('cover') or {}
    if cv.get('lines'): return ' '.join(cv['lines']), cv['lines'][min(cv.get('accent_line', 0), len(cv['lines']) - 1)]
    return sb.get('name', ''), ''


def _page(sb):
    import os
    sc = next((x for x in sb['scenes'] if x['type'] == 'scroll' and x.get('image')), None)
    if not sc: return None, 0
    p = sc['image'] if os.path.isabs(sc['image']) else os.path.join(sb.get('asset_dir') or '', sc['image'])
    try:
        return skia.Image.MakeFromEncoded(skia.Data.MakeFromFileName(p)).withDefaultMipmaps(), int(sc.get('focus_y') or 0)
    except Exception:
        return None, 0


def _norm_w(w): return re.sub(r'[^\w]', '', w.lower())


def _big(c, txt, accent, x, y, max_w, size, max_lines=4, align='c', weight=900, rgb=None, track_em=-0.03, lh=1.02,
         marker=False, min_size=48):
    """Headline block. Accent words get the accent gradient, or a marker highlight behind them. Returns the bottom y."""
    rgb = rgb or TH.text
    sz, lines = fit_block(txt, 'inter', weight, max_w, size, max_lines, min_size, track_em)
    f = I(weight, sz); tr = track_em * sz * TH.track; sp = tw(' ', f)
    acc = {_norm_w(w) for w in (accent or '').split() if _norm_w(w)}
    for i, ln in enumerate(lines):
        yy = y + sz * 0.82 + i * sz * lh
        lw = tw(ln, f, tr); xx = x - lw / 2 if align == 'c' else x
        for w in ln.split(' '):
            ww = tw(w, f, tr); on = _norm_w(w) in acc
            if on and marker:
                rrect(c, xx - sz * 0.08, yy - sz * 0.80, ww + sz * 0.16, sz * 0.98, sz * 0.12, TH.acc)
                text(c, w, xx, yy, f, TH.ink, track=tr)
            else:
                text(c, w, xx, yy, f, rgb, shader=acc_grad(xx, yy - sz, xx + ww, yy) if on else None, track=tr)
            xx += ww + sp + tr
    return y + sz * lh * len(lines) + sz * 0.18


def _brand(c, sb, y, align='c', x=540, size=54):
    name = sb.get('name', '')
    a, b = split_name(name)
    ns = fit_size(name, 'inter', 700, 700, size, 26, track_em=-0.026)
    fn = I(700, ns); tr = -ns * 0.026; m = ns * 1.75
    total = m + 22 + tw(name, fn, tr)
    x0 = x - total / 2 if align == 'c' else x
    mark(c, x0 + m / 2, y, m, 10, initials(name))
    tx = x0 + m + 22
    text(c, a, tx, y + ns * 0.36, fn, TH.text, track=tr)
    if b:
        xa = tx + tw(a, fn, tr) + tr
        text(c, b, xa, y + ns * 0.36, fn, shader=acc_grad(xa, y - ns, xa + tw(b, fn, tr), y), track=tr)


def _foot(sb):
    h = (sb.get('handle') or '').strip()
    if h and not h.startswith('@') and ' ' not in h and '.' not in h and '/' not in h: h = '@' + h
    return h or sb.get('url') or ''


def _screen(c, page, focus, x, y, w, h, r, frame='phone', tilt=0.0, rot=0.0, fallback=None):
    """A phone or browser frame showing the page from where the README starts, with optional perspective."""
    bar = 70 if frame == 'browser' else 0; inset = 20 if frame == 'phone' else 0
    c.save()
    if rot: c.rotate(rot, x + w / 2, y + h / 2)
    if tilt:
        pts = [(-w / 2, -h / 2, 0), (w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0)]
        rr_ = roty(pts, tilt)
        quad = project_quad(rr_, x + w / 2, y + h / 2, 1800)
        m = skia.Matrix(); m.setPolyToPoly([skia.Point(0, 0), skia.Point(w, 0), skia.Point(w, h), skia.Point(0, h)], quad)
        c.concat(m)
    else:
        c.translate(x, y)
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(0, 40, w, h), r, r), paint((0, 0, 0), 0.55 * TH.shadow_alpha, blur=60))
    body = (18, 18, 22) if frame == 'phone' else TH.panel
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(w, h), r, r), paint(body))
    if bar:
        for i, rgb in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]): circle(c, 30 + i * 24, bar / 2, 8, rgb)
    vx, vy, vw, vh = inset, inset + bar, w - 2 * inset, h - 2 * inset - bar
    c.save(); c.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(vx, vy, vw, vh), max(4, r - inset), max(4, r - inset)), skia.ClipOp.kIntersect, True)
    img = page or fallback
    if img:
        k = vw / img.width(); top = max(0, focus - 40) if page else 0
        src_h = min(img.height() - top, vh / k)
        c.drawImageRect(img, skia.Rect.MakeXYWH(0, top, img.width(), src_h), skia.Rect.MakeXYWH(vx, vy, vw, src_h * k), SAMP)
    c.restore()
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(w, h), r, r), paint((255, 255, 255), 0.16, stroke=3))
    if frame == 'phone': rrect(c, w / 2 - 60, inset + 12, 120, 30, 15, (0, 0, 0))
    c.restore()


def _cards(sb):
    name = sb.get('name', ''); footer = _foot(sb) or name
    pref = ['code', 'terminal', 'bullets', 'steps', 'features', 'rank', 'chapter', 'quote', 'stats', 'statement', 'teaser', 'hook']
    picks = []
    for kind in pref:
        for s in sb['scenes']:
            if s['type'] == kind and s not in picks: picks.append(s)
    picks = picks[:3] or sb['scenes'][:1]
    return [_card(s, name, footer) for s in picks]


# ---- the layouts ----
def _cover_stack(c, sb, tl):
    page, focus = _page(sb); imgs = _cards(sb)
    if page:
        s2 = skia.Surface(CW, CH); c2 = s2.getCanvas(); c2.clear(col(TH.panel))
        k = CW / page.width(); top = max(0, focus - 60)
        c2.drawImageRect(page, skia.Rect.MakeXYWH(0, top, page.width(), min(page.height() - top, CH / k)),
                         skia.Rect.MakeXYWH(0, 0, CW, min(page.height() - top, CH / k) * k), SAMP)
        imgs.insert(0, s2.makeImageSnapshot().withDefaultMipmaps())
    while len(imgs) < 3: imgs.append(imgs[len(imgs) % max(1, len(imgs))])
    g = skia.GradientShader.MakeRadial(skia.Point(540, 1060), 620, [col(TH.acc, .22), col(TH.acc, 0)])
    c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=g))
    for img, d in sorted([(imgs[1], -1), (imgs[2], 1), (imgs[1], 2), (imgs[2], -2)], key=lambda x: -abs(x[1])): _card3d(c, img, 540, 1125, d)
    _card3d(c, imgs[0], 540, 1125, 0)
    txt, acc = _hook(sb)
    if sb.get('audience'):
        ks = fit_size(sb['audience'].upper(), 'mono', 800, 900, 32, 18, track_em=0.2)
        text(c, sb['audience'].upper(), 540, 300, M(800, ks), TH.muted, 1, 'c', track=ks * 0.2)
    _big(c, txt, acc, 540, 340, 960, 124, 3)
    _brand(c, sb, 1580)
    f = _foot(sb)
    if f: text(c, f, 540, 1690, I(600, fit_size(f, 'inter', 600, 900, 34, 18)), TH.muted, 1, 'c')


def _cover_headline(c, sb, tl):
    txt, acc = _hook(sb)
    if sb.get('audience'):
        ks = fit_size(sb['audience'].upper(), 'mono', 800, 900, 34, 18, track_em=0.2)
        text(c, sb['audience'].upper(), 540, 420, M(800, ks), TH.acc, 1, 'c', track=ks * 0.2)
    sz, lines = fit_block(txt, 'inter', 900, 960, 200, 5, 70, -0.03)
    hh = sz * 1.02 * len(lines)
    _big(c, txt, acc or txt.split()[-1], 540, 960 - hh / 2 - 40, 960, 200, 5, marker=True, min_size=70)
    _brand(c, sb, 1560, size=48)
    f = _foot(sb)
    if f: text(c, f, 540, 1665, I(600, fit_size(f, 'inter', 600, 900, 32, 18)), TH.muted, 1, 'c')


def _cover_device(c, sb, tl):
    page, focus = _page(sb)
    fb = None if page else _cards(sb)[0]
    g = skia.GradientShader.MakeRadial(skia.Point(560, 1300), 700, [col(TH.acc, .30), col(TH.acc, 0)])
    c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=g))
    txt, acc = _hook(sb)
    bottom = _big(c, txt, acc, 540, 250, 960, 118, 3)
    _screen(c, page, focus, 230, max(bottom + 30, 640), 620, 1120, 82, 'phone', tilt=-14, rot=-4, fallback=fb)
    with xf(c, 0, 0, 1, -4, 820, 1640):
        f = _foot(sb) or sb.get('name', '')
        fn = I(800, fit_size(f, 'inter', 800, 520, 34, 20)); w = tw(f, fn) + 56
        rrect(c, 820 - w / 2, 1606, w, 70, 35, TH.acc); text(c, f, 820, 1653, fn, TH.ink, 1, 'c')


def _cover_split(c, sb, tl):
    page, focus = _page(sb)
    fb = None if page else _cards(sb)[0]
    p = skia.Path(); p.moveTo(0, 0); p.lineTo(W, 0); p.lineTo(W, 980); p.lineTo(0, 1080); p.close()
    c.drawPath(p, paint(TH.acc))
    txt, acc = _hook(sb)
    if sb.get('audience'):
        text(c, sb['audience'].upper(), 80, 250, M(800, fit_size(sb['audience'].upper(), 'mono', 800, 900, 30, 18, track_em=0.2)), TH.ink, 0.8, track=6)
    _big(c, txt, '', 80, 290, 920, 132, 4, align='l', rgb=TH.ink)
    _screen(c, page, focus, 120, 900, 840, 760, 30, 'browser', fallback=fb)
    _brand(c, sb, 1760, size=44)


def _cover_magazine(c, sb, tl):
    name = sb.get('name', '')
    mast = name.upper() if len(name) <= 14 else name
    ms = fit_size(mast, 'inter', 800, 940, 230, 90, track_em=-0.02)
    text(c, mast, 70, 150 + ms * 0.78, I(800, ms), TH.acc, 1, track=-ms * 0.02 * TH.track)
    yr = 170 + ms * 0.82
    line(c, 70, yr, 1010, yr, TH.text, 1, 3, False)
    issue = (sb.get('audience') or sb.get('topic') or '')[:40]
    text(c, 'No. 01', 70, yr + 46, M(700, 26), TH.muted, 1, track=3)
    if issue: text(c, issue.upper(), 1010, yr + 46, M(700, 24), TH.muted, 1, 'r', track=3)
    txt, acc = _hook(sb)
    bottom = _big(c, txt, acc, 70, yr + 110, 560, 96, 6, align='l', weight=800, track_em=-0.02, lh=1.05)
    lines = [x.get('title') for x in sb['scenes'] if x['type'] in ('chapter', 'bullets', 'features') and x.get('title')]
    lines += [it.get('title') for x in sb['scenes'] for it in (x.get('items') or []) if isinstance(it, dict) and it.get('title')]
    y = max(bottom + 30, 1250)
    for ln in [l for l in lines if l][:3]:
        rrect(c, 70, y - 26, 34, 5, 2, TH.acc)
        text(c, ln[:34], 120, y, I(600, 36), TH.text); y += 66
    page, focus = _page(sb)
    fb = None if page else _cards(sb)[0]
    _screen(c, page, focus, 660, yr + 110, 360, 700, 18, 'card', fallback=fb)
    f = _foot(sb)
    line(c, 70, 1770, 1010, 1770, TH.border, 1, 2, False)
    if f: text(c, f, 70, 1820, I(600, 30), TH.muted)


def _cover_poster(c, sb, tl):
    name = sb.get('name', ''); txt, acc = _hook(sb)
    g = skia.GradientShader.MakeLinear([skia.Point(0, 900), skia.Point(0, H)], [col((0, 0, 0), 0), col((0, 0, 0), 0.75)])
    c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=g))
    tf = fit_size(txt.upper(), 'mono', 700, 900, 30, 18, track_em=0.25)
    for i, ln in enumerate(wrap(txt.upper(), M(700, tf), 880, tf * 0.25, 2)):
        text(c, ln, 540, 420 + i * tf * 1.6, M(700, tf), TH.text, 0.9, 'c', track=tf * 0.25)
    ns = fit_size(name, 'inter', 800, 980, 210, 80, track_em=-0.02)
    sz, lines = fit_block(name, 'inter', 800, 980, ns, 2, 80, -0.02)
    y = 1260
    for i, ln in enumerate(lines):
        w = tw(ln, I(800, sz), -sz * 0.02)
        text(c, ln, 540, y + i * sz, I(800, sz), TH.text, 1, 'c', track=-sz * 0.02, shader=acc_grad(540 - w / 2, y - sz, 540 + w / 2, y + i * sz))
    credits = [x.get('title') for x in sb['scenes'] if x['type'] in ('chapter', 'features', 'bullets') and x.get('title')]
    credits += [it.get('title') for x in sb['scenes'] for it in (x.get('items') or []) if isinstance(it, dict) and it.get('title')]
    cr = '  ·  '.join(c_ for c_ in credits if c_)[:110] or (sb.get('topic') or '')
    yy = 1560
    for ln in wrap(cr.upper(), M(500, 22), 900, 3, 3):
        text(c, ln, 540, yy, M(500, 22), TH.muted, 1, 'c', track=3); yy += 36
    f = _foot(sb)
    if f: text(c, f.upper(), 540, 1720, M(800, 26), TH.acc, 1, 'c', track=5)


def _cover_breaking(c, sb, tl):
    txt, acc = _hook(sb); page, focus = _page(sb)
    fb = None if page else _cards(sb)[0]
    rrect(c, 0, 210, W, 96, 0, TH.acc)
    text(c, 'NEW', 70, 280, I(900, 56), (255, 255, 255), 1, track=4)
    nm = (sb.get('name') or '').upper()
    text(c, nm[:22], 1010, 278, I(800, fit_size(nm[:22], 'inter', 800, 700, 44, 22)), (255, 255, 255), 0.9, 'r')
    sz, lines = fit_block(txt, 'inter', 900, 900, 104, 4, 50, -0.01)
    y = 380
    for ln in lines:
        w = tw(ln, I(900, sz))
        rrect(c, 60, y, w + 50, sz * 1.18, 4, (255, 255, 255))
        text(c, ln, 85, y + sz * 0.92, I(900, sz), TH.bg)
        y += sz * 1.18 + 12
    _screen(c, page, focus, 100, max(y + 40, 900), 880, 760, 10, 'browser', fallback=fb)
    c.drawRect(skia.Rect.MakeXYWH(0, 1780, W, 76), paint((255, 255, 255)))
    rrect(c, 0, 1780, 210, 76, 0, TH.acc); text(c, 'LATEST', 105, 1830, I(900, 28), (255, 255, 255), 1, 'c', track=2)
    f = _foot(sb) or sb.get('url', '')
    text(c, f, 240, 1830, I(700, 30), TH.bg)


def _cover_terminal(c, sb, tl):
    txt, acc = _hook(sb)
    x0, y0, w0 = 60, 420, 960
    sz, lines = fit_block(txt, 'mono', 800, 840, 84, 6, 40)
    h0 = 220 + len(lines) * sz * 1.3 + 160
    window(c, x0, y0, w0, h0, '~/' + re.sub(r'[^a-z0-9-]+', '-', (sb.get('name') or '').lower()).strip('-')[:20])
    y = y0 + 64 + 80
    text(c, '$ ', x0 + 40, y, M(700, 34), TH.acc); text(c, 'cat hook.txt', x0 + 40 + tw('$ ', M(700, 34)), y, M(500, 34), TH.muted)
    y += 70
    for ln in lines:
        text(c, ln, x0 + 40, y + sz * 0.85, M(800, sz), TH.text); y += sz * 1.3
    y += 40
    text(c, '$ ', x0 + 40, y, M(700, 34), TH.acc)
    rrect(c, x0 + 40 + tw('$ ', M(700, 34)) + 4, y - 30, 20, 38, 2, TH.acc)
    _brand(c, sb, y0 + h0 + 200, size=48)
    f = _foot(sb)
    if f: text(c, f, 540, y0 + h0 + 300, M(600, 30), TH.muted, 1, 'c')


def _cover_sticker(c, sb, tl):
    txt, acc = _hook(sb)
    sz, lines = fit_block(txt, 'inter', 900, 900, 170, 5, 70, -0.03)
    hh = sz * 1.02 * len(lines)
    top = 900 - hh / 2
    _big(c, txt, acc or txt.split()[-1], 540, top, 900, 170, 5, marker=True, min_size=70)
    ranks = [x for x in sb['scenes'] if x['type'] == 'rank']
    badge = str(len(ranks)) if ranks else (sb.get('cover') or {}).get('badge') or 'NEW'
    with xf(c, 0, 0, 1, 12, 880, top - 60):
        c.drawCircle(880 + 8, top - 52, 120, paint(TH.border)); c.drawCircle(880, top - 60, 120, paint(TH.acc))
        c.drawCircle(880, top - 60, 120, paint(TH.border, 1, stroke=6))
        bf = I(900, fit_size(badge, 'inter', 900, 170, 120 if len(badge) <= 2 else 64, 30))
        text(c, badge, 880, top - 60 + bf.getSize() * 0.36, bf, TH.ink, 1, 'c')
    f = _foot(sb) or sb.get('name', '')
    fn = I(900, 40); w = tw(f, fn) + 70
    with xf(c, 0, 0, 1, -4, 540, top + hh + 160):
        rrect(c, 540 - w / 2 + 8, top + hh + 128, w, 78, 39, TH.border)
        rrect(c, 540 - w / 2, top + hh + 120, w, 78, 39, (255, 255, 255))
        rrect(c, 540 - w / 2, top + hh + 120, w, 78, 39, TH.border, stroke=5)
        text(c, f, 540, top + hh + 172, fn, (17, 17, 17), 1, 'c')


def _cover_minimal(c, sb, tl):
    txt, acc = _hook(sb)
    sz, lines = fit_block(txt, 'inter', 700, 820, 96, 4, 48, -0.02)
    hh = sz * 1.1 * len(lines)
    _big(c, txt, acc, 540, 900 - hh / 2, 820, 96, 4, weight=700, track_em=-0.02, lh=1.1)
    rrect(c, 510, 900 + hh / 2 + 60, 60, 4, 2, TH.acc)
    _brand(c, sb, 1600, size=38)
    f = _foot(sb)
    if f: text(c, f, 540, 1690, I(500, 28), TH.muted, 1, 'c')


def render_cover(sb, path, scale=1.0, style=None):
    """Draw the cover in `style` (default: the template's own layout). `scale` > 1 draws natively at a higher
    resolution. Headline text is the video's cold-open hook, so cover and first frame tell the same story."""
    style = style if style in STYLES else default_style(sb)
    tl = Timeline(sb)
    surf = skia.Surface(int(round(W * scale)), int(round(H * scale))); c = surf.getCanvas()
    c.scale(scale, scale)
    tl.background(c, 3.0, 1.5)
    globals()['_cover_' + style](c, sb, tl)
    tl.post_fx(c, 0)
    surf.makeImageSnapshot().save(path, skia.kPNG)
    return style
