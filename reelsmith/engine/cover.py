"""9:16 cover image. Headline lives inside the 3:4 centre crop Instagram uses for the profile grid."""
import math

import skia

from .lib import *
from .highlight import highlight
from .scenes import mark, initials, split_name, draw_tokens, S
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


def render_cover(sb, path, scale=1.0):
    """`scale` > 1 draws the cover natively at a higher resolution (it's vectors, so no upscaling needed)."""
    tl = Timeline(sb)            # sets the accent, gives us background + grain
    name = sb.get('name', '')
    cv = sb.get('cover') or {}
    footer = sb.get('handle') or sb.get('url') or name
    surf = skia.Surface(int(round(W * scale)), int(round(H * scale))); c = surf.getCanvas()
    c.scale(scale, scale)
    tl.background(c, 3.0, 1.5)
    g = skia.GradientShader.MakeRadial(skia.Point(540, 1060), 620, [col(TH.acc, .22), col(TH.acc, 0)])
    c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=g))

    pref = ['code', 'terminal', 'bullets', 'steps', 'features', 'rank', 'chapter', 'quote', 'stats', 'statement', 'teaser', 'hook']
    picks = []
    for kind in pref:
        for s in sb['scenes']:
            if s['type'] == kind and s not in picks: picks.append(s)
    picks = picks[:3] or sb['scenes'][:1]
    imgs = [_card(s, name, footer) for s in picks]
    shot = next((x for x in sb['scenes'] if x['type'] == 'scroll' and x.get('image')), None)
    if shot:
        import os
        p = shot['image'] if os.path.isabs(shot['image']) else os.path.join(sb.get('asset_dir') or '', shot['image'])
        try:
            page = skia.Image.MakeFromEncoded(skia.Data.MakeFromFileName(p))
            k = CW / page.width(); top = max(0, (shot.get('focus_y') or 0) - 60)
            s2 = skia.Surface(CW, CH); c2 = s2.getCanvas(); c2.clear(col(TH.panel))
            c2.drawImageRect(page, skia.Rect.MakeXYWH(0, top, page.width(), min(page.height() - top, CH / k)),
                             skia.Rect.MakeXYWH(0, 0, CW, min(page.height() - top, CH / k) * k), SAMP)
            imgs.insert(0, s2.makeImageSnapshot().withDefaultMipmaps())
        except Exception:
            pass
    while len(imgs) < 3: imgs.append(imgs[len(imgs) % len(picks)])
    order = [(imgs[1], -1), (imgs[2], 1), (imgs[1], 2), (imgs[2], -2)]
    for img, d in sorted(order, key=lambda x: -abs(x[1])): _card3d(c, img, 540, 1125, d)
    _card3d(c, imgs[0], 540, 1125, 0)

    if cv.get('kicker'):
        ks = fit_size(cv['kicker'].upper(), 'mono', 800, 900, 34, 18, track_em=0.24)
        text(c, cv['kicker'].upper(), 540, 330, M(800, ks), TH.muted, 1, 'c', track=ks * 0.24)
    lines = cv.get('lines') or [name]
    al = cv.get('accent_line', 1)
    size = min(fit_size(l, 'inter', 900, 960, 128, 60, track_em=-0.03) for l in lines)
    f = I(900, size)
    y0 = 465 + (3 - len(lines)) * size * 0.5
    for i, l in enumerate(lines):
        y = y0 + i * size * 0.98
        w = tw(l, f, -size * 0.03)
        sh = acc_grad(540 - w / 2, y - size, 540 + w / 2, y) if i == al else None
        text(c, l, 540, y, f, TH.text, 1, 'c', track=-size * 0.03, shader=sh)
    if cv.get('badge'):
        last_w = tw(lines[-1], f, -size * 0.03)
        bx = min(930, 540 + last_w / 2 + 120); by = y0 + (len(lines) - 1) * size * 0.98 - size * 0.25
        fb = M(800, 26); bw = pill_w(cv['badge'].upper(), fb, 20)
        bx = min(bx, 1040 - bw / 2)
        with xf(c, 0, 0, 1, -6, bx, by):
            pill(c, bx, by - 29, cv['badge'].upper(), fb, TH.ink, TH.acc, 1, pad=20, h=58, align='c')

    a, b = split_name(name)
    ns = fit_size(name, 'inter', 700, 720, 58, 28, track_em=-0.026)
    fn = I(700, ns); tr = -ns * 0.026
    total = 100 + 24 + tw(name, fn, tr)
    x = 540 - total / 2
    with xf(c, 0, 0, 1, 0, 0, 0):
        mark(c, x + 50, 1565, 100, 10, initials(name))
    x += 124
    text(c, a, x, 1586, fn, TH.text, track=tr)
    if b:
        xa = x + tw(a, fn, tr) + tr
        text(c, b, xa, 1586, fn, shader=acc_grad(xa, 1530, xa + tw(b, fn, tr), 1586), track=tr)
    sub = sb.get('url') or ''
    if sub:
        ss = fit_size(sub, 'inter', 600, 900, 34, 18)
        text(c, sub, 540, 1675, I(600, ss), TH.muted, 1, 'c')
    tl.post_fx(c, 0)
    surf.makeImageSnapshot().save(path, skia.kPNG)
