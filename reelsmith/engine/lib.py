"""Vector drawing + animation primitives on top of skia.

Everything is drawn as vectors in a fixed 1080x1920 design space; the renderer scales the canvas
for draft output, so a 540x960 preview and a 1080x1920 final are the same picture.
"""
import functools
import math
import os

import skia

W, H, FPS = 1080, 1920, 30
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fonts')

from . import templates as T


class Theme:
    """The active template's values (palette, fonts, shape, motion). Filled by apply_template()."""


TH = Theme()


def hex_to_rgb(h, default=(240, 180, 41)):
    try:
        h = h.strip().lstrip('#')
        if len(h) == 3: h = ''.join(ch * 2 for ch in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _lum(c): return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def set_accent(hex_color, acc2_hex=None):
    a = hex_to_rgb(hex_color)
    lum = _lum(a)
    if TH.light and lum > 150:            # keep it dark enough to read on a light page
        a = tuple(c * 150 / lum for c in a)
    elif not TH.light and lum < 110:      # and bright enough on a dark one
        a = tuple(min(255, c * 110 / max(lum, 1)) for c in a)
    TH.acc = a
    TH.acc2 = hex_to_rgb(acc2_hex) if acc2_hex else tuple(c * 0.86 for c in a)
    TH.acc_bg = mix(TH.bg, a, 0.12 if TH.light else 0.16)
    TH.acc_border = mix(TH.bg, a, 0.4)
    TH.ink = (15, 17, 21) if _lum(a) > 140 else (255, 255, 255)     # text drawn on the accent


THEME_KEYS = ('light', 'bg', 'surf', 'text', 'muted', 'border', 'codebg', 'panel', 'red', 'green', 'fonts',
              'display_from', 'display_weight', 'track', 'radius', 'border_w', 'shadow', 'shadow_alpha', 'glow',
              'bg_style', 'bg_colors', 'vignette', 'grain', 'scanlines', 'transition', 'music', 'sfx',
              'align', 'margin', 'pace')


def apply_template(tid=None, accent=None):
    """Activate a template. `accent` (hex) overrides the template's accent; its second colour is then derived."""
    t = T.get(tid)
    TH.id, TH.name = T.resolve_id(tid), t['name']
    for k in THEME_KEYS: setattr(TH, k, t[k])
    for k, v in t['syntax'].items(): setattr(TH, k, v)
    if accent: set_accent(accent)
    else: set_accent(t['accent'], t['acc2'])


def col(rgb, a=1.0):
    if len(rgb) == 4: a = a * rgb[3]          # colours may carry their own alpha (glass surfaces)
    a = max(0.0, min(1.0, a))
    return skia.Color(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(round(a * 255)))


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


# ---- easing ----
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def prog(t, a, b): return clamp((t - a) / (b - a)) if b != a else float(t >= a)
def lerp(a, b, t): return a + (b - a) * t
def e_out3(x): return 1 - (1 - x) ** 3
def e_out5(x): return 1 - (1 - x) ** 5
def e_in3(x): return x ** 3
def e_io3(x): return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2
def e_io5(x): return 16 * x ** 5 if x < .5 else 1 - (-2 * x + 2) ** 5 / 2
def e_back(x, s=1.7):
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


# ---- fonts ----
@functools.lru_cache(None)
def _tf(path): return skia.Typeface.MakeFromFile(path)

_MONO = {400: 'JBM-Regular', 500: 'JBM-Medium', 600: 'JBM-Bold', 700: 'JBM-Bold', 800: 'JBM-ExtraBold', 900: 'JBM-ExtraBold'}

def _nearest(fam, w):
    return fam[min(fam, key=lambda k: (abs(k - w), -k))]


@functools.lru_cache(None)
def _font(tid, kind, weight, size):
    f = TH.fonts
    if kind == 'mono':
        name = _nearest(f['mono'], weight)
    elif f.get('display') and weight >= TH.display_from:
        name = _nearest(f['display'], TH.display_weight.get(weight, weight))
    else:
        name = _nearest(f['sans'], weight)
    ft = skia.Font(_tf(os.path.join(FONT_DIR, name)), size)
    ft.setSubpixel(True); ft.setEdging(skia.Font.Edging.kAntiAlias); ft.setHinting(skia.FontHinting.kNone)
    return ft


def font(kind, weight, size):
    """kind 'inter' = the template's text face (its display face at heavy weights), 'mono' = its code face."""
    return _font(TH.id, kind, int(round(weight / 100)) * 100, max(8, int(round(size))))


@functools.lru_cache(None)
def _fallback(weight, size):
    """Inter (wide symbol coverage) at the same weight and size, for glyphs a template's face lacks."""
    ft = skia.Font(_tf(os.path.join(FONT_DIR, T.INTER[min(T.INTER, key=lambda k: abs(k - weight))])), size)
    ft.setSubpixel(True); ft.setEdging(skia.Font.Edging.kAntiAlias); ft.setHinting(skia.FontHinting.kNone)
    return ft


@functools.lru_cache(maxsize=4096)
def _runs(tf_id, s, weight, size, f_key):
    """Split `s` into (text, use_fallback) runs by whether the font has each glyph. Cached per font and string."""
    f = _RUNS_FONT[f_key]
    glyphs = f.textToGlyphs(s)
    out = []
    for ch, g in zip(s, glyphs):
        fb = g == 0 and not ch.isspace()
        if out and out[-1][1] == fb: out[-1] = (out[-1][0] + ch, fb)
        else: out.append((ch, fb))
    return tuple(out)


_RUNS_FONT = {}


def runs(s, f):
    key = id(f); _RUNS_FONT[key] = f
    return _runs(id(f.getTypeface()), s, 0, f.getSize(), key)


def I(w, s): return font('inter', w, s)
def M(w, s): return font('mono', w, s)


def paint(rgb=None, a=1.0, stroke=None, shader=None, blur=None, cap_round=False):
    p = skia.Paint(AntiAlias=True, Color=col(TH.text if rgb is None else rgb, a))
    if stroke is not None:
        p.setStyle(skia.Paint.kStroke_Style); p.setStrokeWidth(stroke)
        if cap_round: p.setStrokeCap(skia.Paint.kRound_Cap)
    if shader is not None:
        p.setShader(shader); p.setAlphaf(clamp(a))
    if blur:
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    return p


def tw(s, f, track=0.0):
    if not s: return 0.0
    rs = runs(s, f)
    if len(rs) == 1 and not rs[0][1]:
        return f.measureText(s) + track * (len(s) - 1)
    fb = _fallback(f.getTypeface().fontStyle().weight(), f.getSize())
    return sum((fb if b else f).measureText(t) for t, b in rs) + track * (len(s) - 1)


def text(c, s, x, y, f, rgb=None, a=1.0, align='l', track=0.0, shader=None):
    if a <= 0.003 or not s: return tw(s, f, track) if s else 0
    w = tw(s, f, track)
    if align == 'c': x -= w / 2
    elif align == 'r': x -= w
    rgb = TH.text if rgb is None else rgb
    if TH.glow and f.getSize() >= 30 and a > 0.05:           # phosphor glow for big type
        g = paint(TH.acc if shader is not None else rgb, a * 0.45, blur=f.getSize() * 0.12)
        _draw_str(c, s, x, y, f, g, track)
    p = paint(rgb, a, shader=shader)
    return _draw_str(c, s, x, y, f, p, track, w)


def _draw_str(c, s, x, y, f, p, track, w=None):
    rs = runs(s, f)
    if len(rs) > 1 or rs[0][1]:                            # some glyphs missing: draw those with the fallback face
        fb = _fallback(f.getTypeface().fontStyle().weight(), f.getSize())
        for t, b in rs:
            ft = fb if b else f
            for ch in (t if track else [t]):
                c.drawString(ch, x, y, ft, p)
                x += ft.measureText(ch) + (track if track else 0)
        return w
    if track == 0:
        c.drawString(s, x, y, f, p)
    else:
        for ch in s:
            c.drawString(ch, x, y, f, p)
            x += f.measureText(ch) + track
    return w


# ---- text fitting: content comes from an LLM, so nothing may assume a length ----
def fit_size(s, kind, weight, max_w, size, min_size=18, track_em=0.0):
    track_em *= TH.track
    """Largest size <= `size` at which `s` fits in `max_w` on one line."""
    f = font(kind, weight, size)
    w = tw(s, f, track_em * size)
    if w <= max_w or size <= min_size: return size
    return max(min_size, int(size * max_w / w))


def wrap(s, f, max_w, track=0.0, max_lines=None):
    words = (s or '').split()
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if tw(trial, f, track) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur: lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and tw(last + '…', f, track) > max_w: last = last[:-1]
        lines[-1] = last.rstrip() + '…'
    return lines


def fit_block(s, kind, weight, max_w, size, max_lines, min_size=18, track_em=0.0):
    track_em *= TH.track
    """Wrap `s` into at most `max_lines`, shrinking the type until it fits. Returns (size, lines)."""
    while True:
        f = font(kind, weight, size)
        lines = wrap(s, f, max_w, track_em * size)
        if len(lines) <= max_lines or size <= min_size:
            return size, wrap(s, f, max_w, track_em * size, max_lines)
        size = int(size * 0.92)


def rrect(c, x, y, w, h, r, rgb=None, a=1.0, stroke=None, shader=None, blur=None):
    if a <= 0.003 or w <= 0 or h <= 0: return
    rgb = TH.surf if rgb is None else rgb
    r = min(r * TH.radius, w / 2, h / 2)
    if stroke is not None and rgb == TH.border: stroke *= TH.border_w
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r), paint(rgb, a, stroke, shader, blur))


def shadow(c, x, y, w, h, r, a=0.5, blur=40, dy=24):
    st = TH.shadow
    if st == 'none' or a <= 0.003: return
    if st == 'hard':                                   # neo-brutalist offset block, no blur
        rrect(c, x + 12, y + 12, w, h, r, TH.border, min(1.0, a * 2.2)); return
    if st == 'glow':
        rrect(c, x, y, w, h, r, TH.acc, a * 0.22 * TH.shadow_alpha, blur=blur * 0.6); return
    rrect(c, x, y + dy, w, h, r, (0, 0, 0), a * TH.shadow_alpha, blur=blur)


def circle(c, x, y, r, rgb=None, a=1.0, stroke=None, blur=None):
    if a <= 0.003 or r <= 0: return
    c.drawCircle(x, y, r, paint(rgb or TH.acc, a, stroke, blur=blur))


def line(c, x1, y1, x2, y2, rgb=None, a=1.0, w=2, round_cap=True):
    if a <= 0.003: return
    rgb = TH.muted if rgb is None else rgb
    c.drawLine(x1, y1, x2, y2, paint(rgb, a, stroke=w, cap_round=round_cap))


def acc_grad(x0, y0, x1, y1, c0=None, c1=None):
    return skia.GradientShader.MakeLinear([skia.Point(x0, y0), skia.Point(x1, y1)], [col(c0 or TH.acc), col(c1 or TH.acc2)])


class layer:
    def __init__(self, c, a): self.c, self.a = c, clamp(a)
    def __enter__(self):
        if self.a < 0.999: self.c.saveLayer(None, skia.Paint(Alphaf=self.a))
        else: self.c.save()
        return self
    def __exit__(self, *e): self.c.restore()


class xf:
    """Transform scope: scale/rotate around (ox, oy), then translate by (tx, ty)."""
    def __init__(self, c, tx=0, ty=0, s=1.0, rot=0.0, ox=0, oy=0):
        self.c, self.args = c, (tx, ty, s, rot, ox, oy)
    def __enter__(self):
        tx, ty, s, rot, ox, oy = self.args
        c = self.c; c.save(); c.translate(tx + ox, ty + oy)
        if rot: c.rotate(rot)
        c.scale(s, s); c.translate(-ox, -oy)
        return self
    def __exit__(self, *e): self.c.restore()


def rise_text(c, s, x, y, f, p, rgb=None, a=1.0, align='l', track=0.0, shader=None):
    """Text revealed by rising out of a clip line."""
    if p <= 0 or not s: return
    m = f.getMetrics(); asc, desc = -m.fAscent, m.fDescent
    w = tw(s, f, track)
    x0 = x - (w / 2 if align == 'c' else w if align == 'r' else 0)
    c.save()
    c.clipRect(skia.Rect.MakeLTRB(x0 - 60, y - asc * 1.3, x0 + w + 60, y + desc * 1.7))
    text(c, s, x, y + (1 - e_out5(p)) * asc * 1.1, f, rgb, a * clamp(p * 2), align, track, shader)
    c.restore()


def typed(s, p):
    return s[:int(round(len(s) * clamp(p)))]


def caret(c, x, y, h, t, rgb=None, a=1.0, w=4):
    if (t * 2.2) % 1 < 0.6:
        rrect(c, x, y - h, w, h * 1.15, 1.5, rgb or TH.acc, a)


def pill(c, x, y, label, f, fg=None, bg=None, a=1.0, pad=22, h=None, border=None, align='l', track=0.0):
    fg = TH.text if fg is None else fg; bg = TH.surf if bg is None else bg
    w = tw(label, f, track) + pad * 2
    hh = h or (f.getSize() * 1.9)
    if align == 'c': x -= w / 2
    elif align == 'r': x -= w
    rrect(c, x, y, w, hh, hh / 2, bg, a)
    if border: rrect(c, x, y, w, hh, hh / 2, border, a, stroke=2)
    m = f.getMetrics()
    text(c, label, x + pad, y + hh / 2 - (m.fAscent + m.fDescent) / 2, f, fg, a, track=track)
    return w


def pill_w(label, f, pad=22, track=0.0):
    return tw(label, f, track) + pad * 2


def project_quad(corners3, cx, cy, f=1600):
    return [skia.Point(cx + X * f / (f + Z), cy + Y * f / (f + Z)) for X, Y, Z in corners3]


def roty(pts, deg):
    r = math.radians(deg); cs, sn = math.cos(r), math.sin(r)
    return [(x * cs + z * sn, y, -x * sn + z * cs) for x, y, z in pts]


def draw_cursor(c, x, y, s=1.0, a=1.0):
    pth = skia.Path()
    pts = [(0, 0), (0, 34), (9, 26), (15, 40), (21, 37), (15, 24), (27, 24)]
    pth.moveTo(*pts[0])
    for p in pts[1:]: pth.lineTo(*p)
    pth.close()
    with xf(c, x, y, s):
        c.drawPath(pth, paint((0, 0, 0), .35 * a, blur=3))
        c.drawPath(pth, paint((255, 255, 255), a))
        c.drawPath(pth, paint((0, 0, 0), a, stroke=2))


apply_template(T.DEFAULT)
