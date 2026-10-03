"""Scene types. Each one is driven entirely by a dict from the storyboard.

Contract for every scene:
  * `budget(data) -> (min_s, ideal_s)` — how long it wants, given its content.
  * `__init__` precomputes layout and registers its sound effects on the shared Ctx,
    using the same time constants the drawing uses, so picture and sound cannot drift.
  * `draw(c, t)` draws at local time t (t may run past `dur` during the outgoing transition).
"""
import functools
import math
import re
import string

import numpy as np
import skia

from .lib import *
from .highlight import highlight


# ============================== shared context ==============================
class Ctx:
    def __init__(self, brand_name):
        self.events, self.shakes = [], []
        self.brand = brand_name

    def sfx(self, t, kind, gain=1.0, **kw):
        if t >= 0: self.events.append((float(t), kind, float(gain), kw))

    def shake(self, t, amp, dur=0.35):
        self.shakes.append((t, amp, dur))

    def shake_offset(self, t):
        dx = dy = 0.0
        for t0, a, d in self.shakes:
            if t0 <= t < t0 + d:
                k = (1 - (t - t0) / d) ** 2
                dx += a * k * math.sin((t - t0) * 83.0 + t0 * 7)
                dy += a * k * math.cos((t - t0) * 71.0 + t0 * 3)
        return dx, dy

    def camera(self, c, t, cx=540, cy=960, z=1.0, rot=0.0, handheld=1.0):
        sx, sy = self.shake_offset(t)
        hx = handheld * (2.5 * math.sin(t * 0.9) + 1.5 * math.sin(t * 2.3 + 1))
        hy = handheld * (2.5 * math.cos(t * 0.7) + 1.5 * math.sin(t * 1.9 + 2))
        c.translate(540 + sx, 960 + sy)
        c.rotate(rot + handheld * 0.12 * math.sin(t * 0.6))
        c.scale(z, z)
        c.translate(-cx + hx, -cy + hy)


def S(d, k, default=''):
    v = d.get(k, default)
    return default if v is None else (str(v).strip() if not isinstance(v, (list, dict)) else v)


# ============================== headline typography ==============================
def _norm(w): return w.lower().strip(string.punctuation + '“”‘’')


def _layout(s, size, weight, max_w, max_lines, track_em):
    return _layout_t(TH.id, s, size, weight, max_w, max_lines, track_em)


@functools.lru_cache(maxsize=1024)
def _layout_t(tid, s, size, weight, max_w, max_lines, track_em):
    return fit_block(s, 'inter', weight, max_w, size, max_lines, min_size=max(22, int(size * 0.45)), track_em=track_em)


def headline(c, s, accent, cx, y, size, p, weight=800, max_w=960, max_lines=2, track_em=-0.025, lh=1.12,
             rgb=None, align=None):
    """Wrapped, auto-shrunk headline; words that appear in `accent` get the accent gradient.
    Returns (font_size, n_lines) so callers can stack things below it."""
    if not s: return size, 0
    align = align or TH.align
    if align == 'l' and cx == 540: cx = TH.margin               # left-aligned templates start at the margin
    size, lines = _layout(s, size, weight, max_w, max_lines, track_em)
    f = I(weight, size); tr = track_em * size * TH.track
    acc = {_norm(w) for w in (accent or '').split() if _norm(w)}
    n = len(lines); sp = tw(' ', f)
    for li, ln in enumerate(lines):
        yy = y + li * size * lh
        pl = clamp(p * (1 + 0.25 * (n - 1)) - 0.25 * li)
        if pl <= 0: continue
        lw = tw(ln, f, tr)
        x = cx - lw / 2 if align == 'c' else cx
        for word in ln.split(' '):
            ww = tw(word, f, tr)
            sh = acc_grad(x, yy - size, x + ww, yy) if _norm(word) in acc else None
            rise_text(c, word, x, yy, f, pl, rgb, shader=sh, track=tr)
            x += ww + sp + tr
    return size, n


def headline_height(s, size, weight=800, max_w=960, max_lines=2, track_em=-0.025, lh=1.12):
    if not s: return 0
    sz, lines = _layout(s, size, weight, max_w, max_lines, track_em)
    return sz * lh * len(lines)


def para(c, s, cx, y, size, p, rgb=None, weight=500, max_w=940, max_lines=2, align=None, lh=1.3):
    if not s: return 0
    align = align or TH.align
    if align == 'l' and cx == 540: cx = TH.margin
    rgb = TH.muted if rgb is None else rgb
    sz, lines = fit_block(s, 'inter', weight, max_w, size, max_lines, min_size=20)
    f = I(weight, sz)
    for i, ln in enumerate(lines):
        rise_text(c, ln, cx, y + i * sz * lh, f, clamp(p * 1.3 - 0.3 * i), rgb, align=align)
    return sz * lh * len(lines)


# ============================== shared pieces ==============================
def split_name(name):
    name = name.strip()
    if '-' in name.strip('-'):
        k = name.rindex('-'); return name[:k], name[k:]
    if ' ' in name:
        k = name.rindex(' '); return name[:k + 1], name[k + 1:]
    caps = [i for i, ch in enumerate(name) if ch.isupper()]
    if len(caps) >= 2 and caps[-1] > 0: return name[:caps[-1]], name[caps[-1]:]
    return name, ''


def initials(name):
    a, b = split_name(name)
    if b: return (a.strip(' -')[:1] + b.strip(' -')[:1]).upper()
    letters = [ch for ch in name if ch.isalnum()]
    return ''.join(letters[:2]).upper() or 'R'


def mark(c, cx, cy, size, tl, label):
    """App-icon style mark: accent tile with initials, two dim tiles fanning out behind it."""
    s = size
    for k, (rot, dx, op, st) in enumerate(((10, 0.26, .35, .42), (-9, -0.24, .55, .5))):
        p = e_out5(prog(tl, st, st + .55))
        if p <= 0: continue
        with xf(c, dx * s * p, 0.03 * s * p, lerp(.85, .92, p), rot * p, cx, cy):
            sh = skia.GradientShader.MakeLinear([skia.Point(0, cy - s / 2), skia.Point(0, cy + s / 2)], [col(mix(TH.bg, TH.text, 0.13)), col(mix(TH.bg, TH.text, 0.06))])
            rrect(c, cx - s / 2, cy - s / 2, s, s, s * .24, a=op * clamp(p * 3), shader=sh)
    ps = prog(tl, 0.0, 0.5)
    if ps <= 0: return
    with xf(c, 0, 0, max(0.001, lerp(0.5, 1, e_back(ps))), 0, cx, cy), layer(c, clamp(ps * 3)):
        shadow(c, cx - s / 2, cy - s / 2, s, s, s * .24, .5, s * .08, s * .06)
        rrect(c, cx - s / 2, cy - s / 2, s, s, s * .24, shader=acc_grad(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2))
        rrect(c, cx - s / 2, cy - s / 2, s, s, s * .24, (255, 255, 255), .18, stroke=max(2, s * .012))
        fs = fit_size(label, 'inter', 900, s * .78, s * .46)
        f = I(900, fs); m = f.getMetrics()
        text(c, label, cx, cy - (m.fAscent + m.fDescent) / 2, f, TH.ink, 1, 'c', track=-fs * .04)


def wordmark(c, name, cx, y, size, t0, t, max_w=980):
    a, b = split_name(name)
    size = fit_size(name, 'inter', 700, max_w, size, track_em=-0.028)
    f = I(700, size); tr = -size * 0.028 * TH.track
    wa, wb = tw(a, f, tr), tw(b, f, tr)
    x = cx - (wa + wb + (tr if b else 0)) / 2
    grad = acc_grad(x + wa, y - size, x + wa + wb, y) if b else None
    for i, ch in enumerate(a + b):
        p = prog(t, t0 + i * 0.035, t0 + i * 0.035 + 0.55)
        if i < len(a): rise_text(c, ch, x, y, f, p, TH.text)
        else: rise_text(c, ch, x, y, f, p, shader=grad)
        x += f.measureText(ch) + tr


def window(c, x, y, w, h, title, a=1.0):
    shadow(c, x, y, w, h, 26, 0.55 * a, 50, 30)
    rrect(c, x, y, w, h, 26, TH.panel, a)
    rrect(c, x, y, w, h, 26, TH.border, a, stroke=2)
    line(c, x, y + 64, x + w, y + 64, TH.border, a, 2, False)
    for i, rgb in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        circle(c, x + 34 + i * 26, y + 32, 8, rgb, a)
    if title:
        fs = fit_size(title, 'mono', 500, w - 280, 24)
        text(c, title, x + w / 2, y + 41, M(500, fs), TH.muted, a, 'c')


def draw_tokens(c, toks, x, y, size, limit=None):
    """Draw highlighted tokens; `limit` = number of characters to reveal. Returns end x."""
    rem = 10 ** 9 if limit is None else limit
    for s, rgb, wgt in toks:
        if rem <= 0: break
        part = s[:rem]; rem -= len(s)
        x += text(c, part, x, y, M(wgt, size), rgb)
    return x


# ============================== base ==============================
class Scene:
    kind = 'base'
    out = 'zoom'

    @staticmethod
    def budget(d): return 3.0, 5.0

    def __init__(self, data, t0, dur, ctx, index, first=False, last=False):
        self.d, self.t0, self.dur, self.ctx, self.index = data, t0, dur, ctx, index
        self.first, self.last = first, last
        self.setup()
        self.sounds()

    def setup(self): pass
    def sounds(self): pass
    def at(self, lt, kind, gain=1.0, **kw): self.ctx.sfx(self.t0 + lt, kind, gain, **kw)
    def shake(self, lt, amp, dur=0.35): self.ctx.shake(self.t0 + lt, amp, dur)
    def cam(self, c, t, cx=540, cy=960, z=1.0): self.ctx.camera(c, self.t0 + t, cx, cy, z)
    def draw(self, c, t): pass

    def header(self, c, t, y=250, size=78, t0=0.0):
        """Common caption + subtitle at the top of a scene. Returns y below it."""
        cap = S(self.d, 'caption') or S(self.d, 'title')
        _, n = headline(c, cap, S(self.d, 'accent'), 540, y, size, prog(t, t0, t0 + 0.6), max_lines=2)
        hh = headline_height(cap, size)
        sub = S(self.d, 'subtitle')
        y2 = y + hh - size * 0.25 + 12
        if sub: y2 += para(c, sub, 540, y2 + 30, 36, prog(t, t0 + 0.3, t0 + 0.8), max_lines=2)
        return y2 + 40


# ============================== 1. HOOK ==============================
class Hook(Scene):
    kind = 'hook'

    @staticmethod
    def budget(d):
        n = len(d.get('pains') or [])
        return (3.0 + 0.5 * n, 4.0 + 0.7 * n + (0.6 if d.get('answer') else 0))

    def setup(self):
        d = self.d
        self.kicker, self.big, self.punch = S(d, 'kicker'), S(d, 'big') or S(d, 'title'), S(d, 'punch')
        self.pains = [str(p) for p in (d.get('pains') or [])][:3]
        self.answer = S(d, 'answer')
        self.big_size = fit_size(self.big, 'inter', 900, 960, 200, 60, track_em=-0.03)
        self.k_size, self.k_lines = fit_block(self.kicker, 'inter', 600, 940, 64, 2, 30)
        self.p_size, self.p_lines = fit_block(self.punch, 'inter', 800, 960, 120, 2, 48)
        self.has_pains = bool(self.pains) and self.dur >= 3.4
        self.up_t = 1.45
        span = max(0.6, self.dur - 1.9 - (0.9 if self.answer else 0) - 0.4)
        self.pain_t = [1.85 + i * span / max(1, len(self.pains)) for i in range(len(self.pains))]
        self.answer_t = (self.pain_t[-1] + 0.8) if self.has_pains else 1.6
        self.answer_t = min(self.answer_t, self.dur - 0.9)

    def sounds(self):
        if self.first: self.at(0.0, 'riser', 0.5, dur=0.45)
        self.at(0.45, 'impact', 1.0); self.shake(0.47, 14, 0.4)
        if self.punch: self.at(0.95, 'swish', 0.6)
        if self.has_pains:
            self.at(self.up_t, 'whoosh', 0.45, dur=0.45)
            for tt in self.pain_t:
                self.at(tt, 'pop', 0.5, f=520); self.at(tt + 0.35, 'strike', 0.7)
        if self.answer:
            self.at(self.answer_t, 'snap', 0.9); self.at(self.answer_t + 0.05, 'chime', 0.5, notes=(0, 7, 12))
            self.shake(self.answer_t, 5, 0.25)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.02 * t)
        up = e_io5(prog(t, self.up_t, self.up_t + 0.55)) if self.has_pains else 0
        with xf(c, 0, -330 * up, lerp(1, 0.78, up), 0, 540, 880):
            p0 = prog(t, 0.1, 0.6)
            fk = I(600, self.k_size); nk = len(self.k_lines)
            for i, ln in enumerate(self.k_lines):
                text(c, ln, 540, 715 - (nk - 1 - i) * self.k_size * 1.2 - 20 * e_out5(p0), fk, TH.muted, p0, 'c')
            p1 = prog(t, 0.45, 0.85)
            if p1 > 0:
                with xf(c, 0, 0, lerp(1.7, 1, e_out5(p1)), 0, 540, 840):
                    text(c, self.big, 540, 900, I(900, self.big_size), TH.text, clamp(p1 * 4), 'c', track=-self.big_size * 0.03 * TH.track)
            f2 = I(800, self.p_size)
            for i, ln in enumerate(self.p_lines):
                w = tw(ln, f2); y = 1050 + i * self.p_size * 1.1
                rise_text(c, ln, 540, y, f2, prog(t, 0.95 + 0.1 * i, 1.5 + 0.1 * i), align='c', shader=acc_grad(540 - w / 2, y - self.p_size, 540 + w / 2, y))
        if self.has_pains:
            py0 = 800 + max(0, len(self.p_lines) - 1) * self.p_size * 0.86
            for i, (pain, tt) in enumerate(zip(self.pains, self.pain_t)):
                p = prog(t, tt, tt + 0.35)
                if p <= 0: continue
                y = py0 + i * 150
                sp = e_out3(prog(t, tt + 0.35, tt + 0.6))
                with xf(c, 0, 40 * (1 - e_out5(p)), lerp(.94, 1, e_out5(p)), 0, 540, y + 55), layer(c, clamp(p * 2)):
                    rrect(c, 90, y, 900, 112, 24, TH.surf); rrect(c, 90, y, 900, 112, 24, TH.border, stroke=2)
                    circle(c, 150, y + 56, 26, TH.red, 0.18)
                    line(c, 140, y + 46, 160, y + 66, TH.red, 1, 4); line(c, 160, y + 46, 140, y + 66, TH.red, 1, 4)
                    fs = fit_size(pain, 'inter', 600, 760, 40, 22)
                    f = I(600, fs); pain = wrap(pain, f, 760, max_lines=1)[0] if pain else pain
                    text(c, pain, 200, y + 56 + fs * 0.36, f, mix(TH.text, TH.muted, sp), 1)
                    if sp > 0: line(c, 196, y + 56, 196 + tw(pain, f) * sp + 8, y + 56, TH.red, 0.9, 4)
        if self.answer:
            ya = 800 + max(0, len(self.p_lines) - 1) * self.p_size * 0.86 + len(self.pains) * 150 + 140 if self.has_pains else 1250 + (len(self.p_lines) - 1) * self.p_size
            size, _ = _layout(self.answer, 54, 700, 940, 2, 0.0)
            headline(c, self.answer, S(self.d, 'accent'), 540, min(ya, 1660), 54, prog(t, self.answer_t, self.answer_t + 0.5), 700, track_em=0)


# ============================== 2. TITLE ==============================
class Title(Scene):
    kind = 'title'

    @staticmethod
    def budget(d): return 3.0, 4.5

    def setup(self):
        self.name = S(self.d, 'name') or S(self.d, 'title') or self.ctx.brand
        self.label = S(self.d, 'initials')[:3] or initials(self.name)

    def sounds(self):
        self.at(0.08, 'pop', 0.8, f=520)
        self.at(0.42, 'swish', 0.5); self.at(0.52, 'swish', 0.45)
        self.at(1.1, 'logo', 1.0)
        self.at(1.9, 'tick', 0.4)

    def draw(self, c, t):
        self.cam(c, t, 540, 940, 1.0 + 0.05 * e_io3(prog(t, 0, self.dur)))
        glow = e_out3(prog(t, 0.9, 1.9))
        sh = skia.GradientShader.MakeRadial(skia.Point(540, 760), 520, [col(TH.acc, 0.22 * glow), col(TH.acc, 0)])
        c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=sh))
        mark(c, 540, 760, 300, t, self.label)
        wordmark(c, self.name, 540, 1135, 118, 1.1, t)
        para(c, S(self.d, 'tagline'), 540, 1222, 40, prog(t, 1.9, 2.5), max_lines=2)


# ============================== 3. CODE / EDITOR ==============================
class Code(Scene):
    kind = 'code'
    out = 'up'

    @staticmethod
    def budget(d):
        n = sum(len(str(l)) for l in (d.get('lines') or []))
        return 5.0, clamp(3.0 + n / 45.0, 6.0, 11.0)

    def setup(self):
        d = self.d
        self.lines = [(lambda x: x if len(x) <= 64 else x[:63] + '…')(str(l).replace('\t', '  ')) for l in (d.get('lines') or [])][:22] or ['# hello']
        self.lang = S(d, 'language', 'code')
        self.toks = [highlight(l, self.lang) for l in self.lines]
        L = max(len(l) for l in self.lines)
        self.size = int(min(30, 0.95 * 880 / (0.6 * max(L, 1))))
        n = len(self.lines)
        self.top = 395 + 0
        avail = 1290 - 64 - 80
        self.lh = min(self.size * 1.66, avail / max(n, 1))
        if self.lh < self.size * 1.25:
            self.size = int(self.lh / 1.3); self.lh = self.size * 1.3
        self.eh = int(64 + 70 + n * self.lh + 30)
        self.y0 = self.top + 64 + 56
        # typing schedule over the scene
        total = sum(len(l) for l in self.lines)
        start, end = 0.75, max(1.5, self.dur - 1.0)
        pauses = 0.06 * n
        cps = total / max(0.3, end - start - pauses)
        self.chars = []; self.line_done = []
        tcur = start
        for li, l in enumerate(self.lines):
            for ci in range(len(l)):
                self.chars.append((tcur, li, ci + 1))
                tcur += (1 / cps) * (0.7 + 0.6 * ((ci * 7919 + li * 31) % 13) / 13)
            self.line_done.append(tcur); tcur += 0.06
        self.callouts = []
        for co in (d.get('callouts') or [])[:4]:
            try:
                li = int(co.get('line', 0)); lab = str(co.get('label', ''))[:22].upper()
                if 0 <= li < n and lab: self.callouts.append((li, lab))
            except Exception: pass

    def sounds(self):
        self.at(0.15, 'swish', 0.5)
        last = -1
        for i, (tt, li, ci) in enumerate(self.chars):
            if tt - last >= 0.045:
                self.at(tt, 'key', 0.45, seed=i); last = tt
        for li, _ in self.callouts:
            self.at(self.line_done[li] + 0.04, 'pop', 0.8, f=760); self.at(self.line_done[li] + 0.06, 'tick', 0.5)

    def state(self, t):
        li, ci = -1, 0
        for tt, l, cc in self.chars:
            if tt <= t: li, ci = l, cc
            else: break
        return li, ci

    def draw(self, c, t):
        li, ci = self.state(t)
        self.cam(c, t, 540, 960, 1.0 + 0.025 * e_io3(prog(t, 0, self.dur)))
        cap_h = headline_height(S(self.d, 'caption'), 78) + (70 if S(self.d, 'subtitle') else 0)
        top = max(self.top, min(1720 - self.eh, 1000 - self.eh / 2 + (cap_h + 60) / 2))
        self.header(c, t, max(250, top - cap_h - 30), 78)
        po = e_out5(prog(t, 0.1, 0.6))
        if po <= 0: return
        EX, EW = 40, 1000
        with layer(c, po), xf(c, 0, 40 * (1 - po), lerp(.95, 1, po), 0, 540, top + self.eh / 2):
            window(c, EX, top, EW, self.eh, S(self.d, 'filename'))
            c.save(); c.clipRect(skia.Rect.MakeXYWH(EX, top + 66, EW, self.eh - 70))
            y0 = top + 64 + 56
            fn = M(500, max(14, self.size * 0.75))
            for i, toks in enumerate(self.toks):
                if i > li: break
                y = y0 + i * self.lh
                text(c, str(i + 1), EX + 62, y, fn, TH.muted, 0.45, 'r')
                x = draw_tokens(c, toks, EX + 92, y, self.size, ci if i == li else None)
                if i == li: caret(c, x + 2, y + 4, self.size * 1.1, t)
            c.restore()
            for l, lab in self.callouts:
                pp = prog(t, self.line_done[l] + 0.02, self.line_done[l] + 0.35)
                if pp <= 0: continue
                y = y0 + l * self.lh
                g = 1 - 0.7 * prog(t, self.line_done[l] + 0.3, self.line_done[l] + 1.2)
                rrect(c, EX + 8, y - self.size * 1.1, EW - 16, self.size * 1.5, 8, TH.acc, 0.14 * g)
                f = M(800, 22); w = pill_w(lab, f, 18)
                with xf(c, 0, 0, e_back(pp), 0, EX + EW - 40 - w / 2, y - self.size * 0.35):
                    pill(c, EX + EW - 40 - w, y - self.size * 0.35 - 22, lab, f, TH.ink, TH.acc, 1, pad=18, h=44)


# ============================== 4. STATEMENT ==============================
class Statement(Scene):
    kind = 'statement'

    @staticmethod
    def budget(d):
        n = len(S(d, 'text').split())
        return 2.8, clamp(2.2 + n * 0.22, 3.5, 6.0)

    def setup(self):
        self.text = S(self.d, 'text') or S(self.d, 'caption')
        self.size, self.lines = fit_block(self.text, 'inter', 800, 940, 104, 5, 40, -0.025)
        self.words = sum(len(l.split()) for l in self.lines)
        self.reveal = clamp(0.12 * self.words, 0.6, 1.6)
        self.block_h = self.size * 1.12 * len(self.lines)

    def sounds(self):
        self.at(0.0, 'swish', 0.45)
        for k in range(self.words):
            self.at(0.1 + k * self.reveal / max(1, self.words), 'tick', 0.25)
        self.at(0.1 + self.reveal + 0.1, 'impact', 0.55); self.shake(0.2 + self.reveal, 5, 0.25)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.04 * prog(t, 0, self.dur))
        f = I(800, self.size); tr = -0.025 * self.size * TH.track
        acc = {_norm(w) for w in S(self.d, 'accent').split() if _norm(w)}
        y0 = 960 - self.block_h / 2 + self.size * 0.8 - 60
        k = 0; sp = tw(' ', f)
        for li, ln in enumerate(self.lines):
            y = y0 + li * self.size * 1.12
            x = TH.margin if TH.align == 'l' else 540 - tw(ln, f, tr) / 2
            for w in ln.split(' '):
                ww = tw(w, f, tr)
                tt = 0.1 + k * self.reveal / max(1, self.words)
                is_acc = _norm(w) in acc
                rise_text(c, w, x, y, f, prog(t, tt, tt + 0.45), TH.text, shader=acc_grad(x, y - self.size, x + ww, y) if is_acc else None, track=tr)
                if is_acc:
                    ul = e_out5(prog(t, 0.2 + self.reveal, 0.6 + self.reveal))
                    if ul > 0: rrect(c, x, y + self.size * 0.16, ww * ul, max(5, self.size * 0.07), 3, shader=acc_grad(x, 0, x + ww, 0))
                x += ww + sp + tr; k += 1
        para(c, S(self.d, 'sub'), 540, y0 + self.block_h + 40, 40, prog(t, self.reveal + 0.3, self.reveal + 0.8), max_lines=3)


# ============================== 5. BULLETS ==============================
class Bullets(Scene):
    kind = 'bullets'
    out = 'up'

    @staticmethod
    def budget(d):
        n = len(d.get('items') or [])
        return 2.5 + 0.5 * n, 2.6 + 0.85 * n

    def setup(self):
        items = []
        for it in (self.d.get('items') or [])[:5]:
            if isinstance(it, str): items.append((it, ''))
            else: items.append((S(it, 'title'), S(it, 'sub')))
        self.items = items or [('', '')]
        n = len(self.items)
        self.has_sub = any(s for _, s in self.items)
        self.ch = 160 if self.has_sub else 116
        self.gap = 26
        span = max(0.4, self.dur - 1.3)
        self.ts = [0.55 + i * min(0.75, span / n) for i in range(n)]

    def sounds(self):
        for tt in self.ts: self.at(tt, 'pop', 0.55, f=600); self.at(tt + 0.03, 'tick', 0.4)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.03 * prog(t, 0, self.dur))
        y = max(430, self.header(c, t, 250, 76))
        n = len(self.items)
        total = n * self.ch + (n - 1) * self.gap
        y = max(y, 1010 - total / 2) if y + total < 1700 else y
        check = bool(self.d.get('checks'))
        for i, (ti, sub) in enumerate(self.items):
            p = prog(t, self.ts[i], self.ts[i] + 0.4)
            if p <= 0: continue
            yy = y + i * (self.ch + self.gap)
            with xf(c, 60 * (1 - e_out5(p)), 0), layer(c, clamp(p * 2)):
                shadow(c, 70, yy, 940, self.ch, 26, .4, 26, 14)
                rrect(c, 70, yy, 940, self.ch, 26, TH.surf); rrect(c, 70, yy, 940, self.ch, 26, TH.border, stroke=2)
                rrect(c, 70, yy + 22, 6, self.ch - 44, 3, TH.acc)
                tx = 104
                with xf(c, 0, 0, e_back(p), 0, 150, yy + self.ch / 2):
                    rrect(c, 110, yy + self.ch / 2 - 38, 76, 76, 20, TH.acc_bg)
                    lab = '✓' if check else str(i + 1)
                    text(c, lab, 148, yy + self.ch / 2 + 13, I(800, 36), TH.acc, 1, 'c')
                tx = 214
                fs = fit_size(ti, 'inter', 700, 760, 40, 24)
                if sub:
                    text(c, ti, tx, yy + 70, I(700, fs), TH.text)
                    ss = fit_size(sub, 'inter', 500, 760, 29, 18)
                    text(c, sub, tx, yy + 116, I(500, ss), TH.muted)
                else:
                    text(c, ti, tx, yy + self.ch / 2 + fs * 0.36, I(700, fs), TH.text)


# ============================== 6. FEATURES (vertical pan) ==============================
class Features(Scene):
    kind = 'features'
    out = 'up'

    @staticmethod
    def budget(d):
        n = max(1, len(d.get('items') or []))
        return 1.9 * n, 2.3 * n

    def setup(self):
        self.items = []
        for it in (self.d.get('items') or [])[:4]:
            pts = [str(p)[:28] for p in (it.get('points') or [])][:5]
            self.items.append((S(it, 'title'), S(it, 'subtitle'), pts))
        if not self.items: self.items = [('', '', [])]
        self.seg = self.dur / len(self.items)

    def sounds(self):
        for k in range(1, len(self.items)): self.at(self.seg * k - 0.42, 'whoosh', 0.75, dur=0.55, up=True)
        for k, (_, _, pts) in enumerate(self.items):
            for j in range(len(pts)): self.at(self.seg * k + 0.75 + j * 0.13, 'pop', 0.45, f=600 + 90 * j)

    def _rows(self, pts, f):
        rows, cur, cw = [], [], 0
        for p in pts:
            w = min(940, pill_w(p, f, 30))
            if cur and cw + 18 + w > 960: rows.append(cur); cur, cw = [], 0
            cw += w + (18 if cur else 0); cur.append((p, w))
        if cur: rows.append(cur)
        return rows

    def panel(self, c, k, tl):
        ti, sub, pts = self.items[k]; n = len(self.items)
        f = I(700, 36)
        rows = self._rows(pts, f)
        th = headline_height(ti, 100)
        block = 60 + th + (110 if sub else 30) + len(rows) * 104
        y = 960 - block / 2
        text(c, f"{k + 1:02d} / {n:02d}", 540, y, M(800, 30), TH.acc, prog(tl, 0.0, 0.3), 'c', track=4)
        y += 130
        accent = self.d['items'][k].get('accent', '') if isinstance(self.d['items'][k], dict) else ''
        headline(c, ti, accent, 540, y, 100, prog(tl, 0.05, 0.5), 800, max_lines=2, track_em=-0.03)
        y += th - 30
        y += para(c, sub, 540, y + 40, 38, prog(tl, 0.15, 0.6), max_lines=2) + 70
        j = 0
        for r, row in enumerate(rows):
            rw = sum(w for _, w in row) + 18 * (len(row) - 1)
            x = 540 - rw / 2
            for p, w in row:
                pp = prog(tl, 0.5 + j * 0.13, 0.85 + j * 0.13)
                if pp > 0:
                    with xf(c, 0, 0, e_back(pp), 0, x + w / 2, y + r * 104 + 40):
                        fs = fit_size(p, 'inter', 700, w - 60, 36, 20)
                        pill(c, x, y + r * 104, p, I(700, fs), TH.acc if j == 0 else TH.text, TH.surf, 1, pad=30, h=82, border=TH.acc if j == 0 else TH.border)
                x += w + 18; j += 1

    def draw(self, c, t):
        camy = 960 + sum(e_io5(prog(t, self.seg * k - 0.42, self.seg * k)) * 1920 for k in range(1, len(self.items)))
        self.cam(c, t, 540, camy, 1.0)
        for k in range(len(self.items)):
            tl = t - self.seg * k + 0.25
            if tl < -0.3 or tl > self.seg + 0.7: continue
            with xf(c, 0, 1920 * k):
                self.panel(c, k, tl)


# ============================== 7. STATS ==============================
NUM = re.compile(r'^(\D*?)(\d[\d,]*\.?\d*)(.*)$')


class Stats(Scene):
    kind = 'stats'

    @staticmethod
    def budget(d):
        n = len(d.get('items') or [])
        return 2.4 + 0.6 * n, 3.0 + 0.8 * n

    def setup(self):
        self.items = [(S(it, 'value'), S(it, 'label')) for it in (self.d.get('items') or [])[:3]] or [('', '')]
        n = len(self.items)
        self.ts = [0.7 + i * min(0.6, (self.dur - 1.6) / n) for i in range(n)]

    def sounds(self):
        for tt in self.ts:
            self.at(tt, 'impact', 0.7); self.shake(tt, 5, 0.25)
            for k in range(6): self.at(tt + k * 0.05, 'tick', 0.2)

    @staticmethod
    def count(v, p):
        m = NUM.match(v)
        if not m or p >= 1: return v
        pre, num, suf = m.groups()
        try:
            x = float(num.replace(',', ''))
        except ValueError:
            return v
        dec = len(num.split('.')[1]) if '.' in num else 0
        cur = x * e_out3(p)
        s = f"{cur:,.{dec}f}" if ',' in num else f"{cur:.{dec}f}"
        return pre + s + suf

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.03 * prog(t, 0, self.dur))
        y = self.header(c, t, 250, 76)
        n = len(self.items)
        top = max(y + 60, 560); bot = 1680
        step = (bot - top) / n
        for i, (v, lab) in enumerate(self.items):
            tt = self.ts[i]; p = prog(t, tt, tt + 0.4)
            if p <= 0: continue
            cy = top + step * (i + 0.5)
            vs = fit_size(v, 'inter', 900, 940, min(190, step * 0.62), 50, track_em=-0.03)
            with xf(c, 0, 0, lerp(1.5, 1, e_out5(p)), 0, 540, cy - vs * 0.3):
                text(c, self.count(v, prog(t, tt, tt + 0.5)), 540, cy + vs * 0.08, I(900, vs), TH.acc, clamp(p * 3), 'c', track=-vs * 0.03 * TH.track)
            ls = fit_size(lab, 'inter', 600, 920, 40, 22)
            text(c, lab, 540, cy + vs * 0.08 + ls * 1.6, I(600, ls), TH.text, clamp(p * 2), 'c')


# ============================== 8. STEPS (pipeline) ==============================
class Steps(Scene):
    kind = 'steps'

    @staticmethod
    def budget(d):
        n = len(d.get('steps') or [])
        return 3.0 + 0.45 * n, 3.4 + 0.7 * n

    def setup(self):
        self.steps = [(S(s, 'title'), S(s, 'sub')) if isinstance(s, dict) else (str(s), '') for s in (self.d.get('steps') or [])[:6]] or [('', '')]
        n = len(self.steps)
        self.gap = min(240, 1040 / max(1, n - 1)) if n > 1 else 0
        self.bh = min(150, max(96, self.gap - 64)) if n > 1 else 150
        mid = 1040
        self.ny = [mid - self.gap * (n - 1) / 2 + i * self.gap for i in range(n)]
        self.reveal_end = max(1.2, self.dur * 0.55)
        self.napp = [0.25 + i * (self.reveal_end - 0.25) / max(1, n) for i in range(n)]
        self.zoom_t = self.napp[-1] + 0.5

    def sounds(self):
        for tt in self.napp: self.at(tt, 'pop', 0.7, f=480); self.at(tt + 0.02, 'tick', 0.4)
        self.at(self.zoom_t - 0.05, 'whoosh', 0.45, dur=0.8)
        if S(self.d, 'footer'): self.at(self.zoom_t + 1.0, 'chime', 0.7, notes=(0, 7, 12, 16))

    def draw(self, c, t):
        n = len(self.steps)
        a = clamp((t - self.napp[0] - 0.2) / max(0.01, self.napp[1] - self.napp[0] if n > 1 else 1), 0, n - 1)
        cy_track = self.ny[0] + a * self.gap
        zo = e_io5(prog(t, self.zoom_t, self.zoom_t + 0.9))
        self.cam(c, t, 540, lerp(cy_track, 1010, zo), lerp(1.2, 1.0, zo))
        hy = 300
        headline(c, S(self.d, 'title'), S(self.d, 'accent'), 540, hy, 80, prog(t, self.zoom_t + 0.2, self.zoom_t + 0.7), 800, max_lines=1, track_em=-0.03)
        para(c, S(self.d, 'subtitle'), 540, hy + 70, 36, prog(t, self.zoom_t + 0.35, self.zoom_t + 0.8), max_lines=1)
        bw, bh = 800, self.bh; x0 = 540 - bw / 2
        for i in range(n - 1):
            dp = e_io3(prog(t, self.napp[i] + 0.25, self.napp[i + 1]))
            y1, y2 = self.ny[i] + bh / 2, self.ny[i + 1] - bh / 2
            if dp <= 0: continue
            line(c, 540, y1, 540, y1 + (y2 - y1) * dp, TH.border, 1, 4)
            line(c, 540, y1, 540, y1 + (y2 - y1) * dp, TH.acc, 0.5, 2)
            if dp >= 1:
                ph = (t * 1.3 + i * 0.27) % 1
                circle(c, 540, lerp(y1, y2, ph), 7, TH.acc, 1 - abs(ph - .5) * 1.2)
            else:
                circle(c, 540, y1 + (y2 - y1) * dp, 8, TH.acc)
        for i, (ti, sub) in enumerate(self.steps):
            p = prog(t, self.napp[i], self.napp[i] + 0.45)
            if p <= 0: continue
            y = self.ny[i] - bh / 2
            hot = 1 - prog(t, self.napp[i] + 0.4, self.napp[i] + 1.2)
            with xf(c, 0, 0, e_back(p), 0, 540, self.ny[i]), layer(c, clamp(p * 2)):
                shadow(c, x0, y, bw, bh, 24, .5, 30, 18)
                rrect(c, x0, y, bw, bh, 24, TH.surf)
                rrect(c, x0, y, bw, bh, 24, mix(TH.border, TH.acc, hot), stroke=2 + 2 * hot)
                ts = bh * 0.47
                rrect(c, x0 + 28, y + bh / 2 - ts / 2, ts, ts, 18, TH.acc_bg)
                text(c, str(i + 1), x0 + 28 + ts / 2, y + bh / 2 + ts * 0.17, M(800, ts * 0.48), TH.acc, 1, 'c')
                tx = x0 + 56 + ts
                fs = fit_size(ti, 'mono', 800, bw - (tx - x0) - 30, min(40, bh * 0.28), 20)
                if sub:
                    text(c, ti, tx, y + bh * 0.46, M(800, fs), TH.text)
                    ss = fit_size(sub, 'inter', 500, bw - (tx - x0) - 30, min(28, bh * 0.2), 16)
                    text(c, sub, tx, y + bh * 0.76, I(500, ss), TH.muted)
                else:
                    text(c, ti, tx, y + bh / 2 + fs * 0.36, M(800, fs), TH.text)
        foot = S(self.d, 'footer')
        pb = prog(t, self.zoom_t + 1.0, self.zoom_t + 1.4)
        if foot and pb > 0:
            fy = self.ny[-1] + bh / 2 + 120
            fs = fit_size('●  ' + foot, 'inter', 600, 900, 30, 18)
            with xf(c, 0, 0, e_back(pb), 0, 540, fy + 32):
                pill(c, 540, fy, '●  ' + foot, I(600, fs), TH.green, mix(TH.bg, TH.green, 0.16), 1, pad=28, h=64, align='c')


# ============================== 9. TERMINAL ==============================
class Terminal(Scene):
    kind = 'terminal'

    @staticmethod
    def budget(d):
        return 3.2, 3.6 + 0.35 * len(d.get('outputs') or [])

    def setup(self):
        self.cmd = '$ ' + S(self.d, 'command').lstrip('$ ').strip()
        self.outs = [str(o)[:60] for o in (self.d.get('outputs') or [])][:4]
        L = max([len(self.cmd)] + [len(o) for o in self.outs])
        self.size = int(min(30, 0.95 * 900 / (0.6 * max(L, 1))))
        self.type_end = 0.4 + clamp(len(self.cmd) * 0.03, 0.6, 1.6)
        self.enter_t = self.type_end + 0.12
        self.out_t = [self.enter_t + 0.25 + 0.25 * i for i in range(len(self.outs))]

    def sounds(self):
        n = len(self.cmd)
        for k in range(0, n, 2): self.at(0.4 + k * (self.type_end - 0.4) / n, 'key', 0.4, seed=70 + k)
        self.at(self.enter_t, 'enter', 0.9)
        for k, tt in enumerate(self.out_t): self.at(tt, 'tick', 0.5); self.at(tt, 'pop', 0.3 + 0.1 * k, f=700 + 150 * k)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.03 * prog(t, 0, self.dur))
        h = 150 + (len(self.outs) + 1) * self.size * 1.7
        cap_h = headline_height(S(self.d, 'caption'), 76) + (60 if S(self.d, 'subtitle') else 0)
        top = 1000 - h / 2 + (cap_h + 60) / 2
        self.header(c, t, top - cap_h - 40, 76)
        po = e_out5(prog(t, 0.0, 0.35))
        with layer(c, po), xf(c, 0, 30 * (1 - po)):
            window(c, 50, top, 980, h, S(self.d, 'title_bar') or 'terminal')
            s = typed(self.cmd, prog(t, 0.4, self.type_end))
            x = 90
            yy = top + 64 + 60
            if s:
                x += text(c, s[:1], x, yy, M(800, self.size), TH.acc)
                x += draw_tokens(c, highlight(s[1:], 'sh'), x, yy, self.size) - x
            if t < self.enter_t + 0.1: caret(c, x + 3, yy + 5, self.size * 1.1, t)
            for k, (o, tt) in enumerate(zip(self.outs, self.out_t)):
                rgb = TH.green if o.lstrip().startswith(('✓', '✔', 'done', 'ok', 'OK')) else TH.red if o.lstrip().startswith(('✗', 'x ', 'error', 'ERR')) else TH.muted
                text(c, o, 90, yy + (k + 1) * self.size * 1.7, M(500, self.size), rgb, prog(t, tt, tt + 0.12))


# ============================== 10. CTA ==============================
class CTA(Scene):
    kind = 'cta'

    @staticmethod
    def budget(d): return 4.0, 5.5

    def setup(self):
        self.name = S(self.d, 'name') or self.ctx.brand
        self.label = S(self.d, 'initials')[:3] or initials(self.name)

    def sounds(self):
        self.at(-1.3, 'riser', 0.8, dur=1.3)
        self.at(0.0, 'boom', 1.0); self.shake(0.02, 16, 0.5)
        self.at(0.05, 'logo', 0.9)
        if S(self.d, 'url'): self.at(0.9, 'tick', 0.5)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.03 * prog(t, 0, self.dur))
        fl = 1 - prog(t, 0.02, 0.5)
        if fl > 0:
            sh = skia.GradientShader.MakeRadial(skia.Point(540, 900), 900, [col(TH.acc, 0.5 * fl), col(TH.acc, 0)])
            c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=sh))
        mark(c, 540, 700, 230, t, self.label)
        wordmark(c, self.name, 540, 1010, 108, 0.15, t)
        url = S(self.d, 'url')
        pu = prog(t, 0.8, 1.25)
        y = 1080
        if url and pu > 0:
            fs = fit_size(url, 'mono', 700, 880, 36, 18)
            with xf(c, 0, 0, e_back(pu, 1.2), 0, 540, y + 38):
                pill(c, 540, y, url, M(700, fs), TH.acc, TH.acc_bg, 1, pad=32, h=78, align='c', border=TH.acc_border)
        y += 160
        tag = S(self.d, 'tagline')
        if tag:
            y += para(c, tag, 540, y, 34, prog(t, 1.2, 1.7), max_lines=2) + 30
        headline(c, S(self.d, 'line'), S(self.d, 'accent'), 540, y + 50, 56, prog(t, 1.6, 2.1), 800, max_lines=2)


# ============================== 11. QUOTE ==============================
class Quote(Scene):
    """A pull-quote: giant quotation mark, the quote revealed line by line, an attribution rule."""
    kind = 'quote'

    @staticmethod
    def budget(d):
        n = len(S(d, 'text').split())
        return 3.0, clamp(2.4 + n * 0.24, 3.8, 7.5)

    def setup(self):
        self.text = S(self.d, 'text')
        self.size, self.lines = _layout(self.text, 92, 700, 900, 6, -0.02)
        self.reveal = clamp(0.35 * len(self.lines), 0.6, 1.6)

    def sounds(self):
        self.at(0.0, 'swish', 0.5)
        for i in range(len(self.lines)): self.at(0.35 + i * self.reveal / max(1, len(self.lines)), 'tick', 0.25)
        if S(self.d, 'by'): self.at(0.5 + self.reveal, 'chime', 0.45, notes=(0, 7))

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.05 * e_io3(prog(t, 0, self.dur)))
        left = TH.align == 'l'
        bh = 230 + self.size * 1.12 * len(self.lines) + (110 if S(self.d, 'by') else 0)
        top = 960 - bh / 2
        x = TH.margin if left else 540
        pm = e_out5(prog(t, 0.0, 0.5))
        qf = I(800, 420)
        with xf(c, 0, 0, lerp(0.6, 1, e_back(prog(t, 0.0, 0.5))), 0, x + (90 if left else 0), top + 120):
            text(c, '\u201c', x - (8 if left else 0), top + 300, qf, TH.acc, 0.95 * pm, 'l' if left else 'c')
        n = len(self.lines)
        p = prog(t, 0.3, 0.3 + self.reveal) * 1.0
        headline(c, self.text, S(self.d, 'accent'), 540, top + 230 + self.size * 0.8, self.size, p, 700, max_w=900, max_lines=6, track_em=-0.02)
        by = S(self.d, 'by')
        if by:
            pb = e_out5(prog(t, 0.45 + self.reveal, 0.9 + self.reveal))
            yb = top + 230 + self.size * 1.12 * n + 60
            w = 70 * pb
            if left: rrect(c, x, yb - 8, w, 4, 2, TH.acc)
            else: rrect(c, 540 - w / 2, yb - 8, w, 4, 2, TH.acc)
            fb = M(700, fit_size(by.upper(), 'mono', 700, 820, 26, 16, track_em=0.12))
            text(c, by.upper(), (x + 90) if left else 540, yb + 2, fb, TH.muted, pb, 'l' if left else 'c', track=3)


# ============================== 12. CHAPTER ==============================
class Chapter(Scene):
    """A numbered section: huge numeral, title, body. Editorial uses roman numerals, Minimal 01/02."""
    kind = 'chapter'

    @staticmethod
    def budget(d):
        n = len(S(d, 'body').split()) + len(S(d, 'title').split())
        return 3.2, clamp(3.0 + n * 0.16, 4.2, 7.5)

    def sounds(self):
        self.at(0.05, 'swish', 0.55); self.at(0.3, 'tick', 0.5)
        self.at(0.45, 'impact', 0.35); self.shake(0.45, 3, 0.2)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.03 * prog(t, 0, self.dur))
        left = TH.align == 'l'
        x = TH.margin if left else 540
        num = S(self.d, 'number') or str(self.index)
        ns = fit_size(num, 'inter', 800, 900, 380, 120)
        pn = prog(t, 0.0, 0.55)
        f = I(800, ns)
        c.save(); c.clipRect(skia.Rect.MakeLTRB(0, 300, W, 790))
        text(c, num, x - 60 * (1 - e_out5(pn)) * (1 if left else 0), 760 + 120 * (1 - e_out5(pn)), f, TH.acc, clamp(pn * 2), 'l' if left else 'c', track=-ns * 0.02 * TH.track)
        c.restore()
        pr = e_out5(prog(t, 0.25, 0.75))
        if left: rrect(c, x, 812, 900 * pr, 3, 1.5, TH.border if TH.light else TH.muted, 0.9)
        else: rrect(c, 540 - 300 * pr, 812, 600 * pr, 3, 1.5, TH.border if TH.light else TH.muted, 0.9)
        ti = S(self.d, 'title')
        headline(c, ti, S(self.d, 'accent'), 540, 920, 84, prog(t, 0.35, 0.85), 800, max_lines=2)
        y = 920 + headline_height(ti, 84) - 20
        para(c, S(self.d, 'body'), 540, y + 30, 40, prog(t, 0.6, 1.1), max_lines=5, max_w=900)


# ============================== 13. RANK (countdown item) ==============================
class Rank(Scene):
    """One item of a countdown listicle: a big numbered sticker, the item, a line of why."""
    kind = 'rank'

    @staticmethod
    def budget(d): return 2.4, 3.4

    def sounds(self):
        self.at(0.02, 'impact', 0.75); self.shake(0.05, 9, 0.3)
        self.at(0.05, 'pop', 0.7, f=420)
        self.at(0.38, 'swish', 0.45)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.03 * prog(t, 0, self.dur))
        rank = S(self.d, 'rank') or str(self.index)
        of = self.d.get('of')
        ps = prog(t, 0.0, 0.45)
        if ps > 0:
            r = 200
            with xf(c, 0, 0, max(0.001, e_back(ps, 2.4)), -8 + 4 * math.sin(t * 2.2), 540, 700):
                shadow(c, 540 - r, 700 - r, 2 * r, 2 * r, r, 0.6, 40, 20)
                c.drawCircle(540, 700, r, paint(TH.acc))
                c.drawCircle(540, 700, r, paint(TH.border if TH.shadow == 'hard' else (255, 255, 255), 1 if TH.shadow == 'hard' else 0.25, stroke=6 * TH.border_w))
                fs = fit_size(rank, 'inter', 900, r * 1.5, 250, 80)
                f = I(900, fs); m = f.getMetrics()
                text(c, rank, 540, 700 - (m.fAscent + m.fDescent) / 2, f, TH.ink, 1, 'c', track=-fs * 0.03)
        ti = S(self.d, 'title')
        pt = prog(t, 0.3, 0.7)
        if pt > 0:
            with xf(c, 0, 0, lerp(1.25, 1, e_out5(pt)), 0, 540, 1080):
                headline(c, ti, S(self.d, 'accent'), 540, 1060, 96, min(1.0, pt * 2), 900, max_lines=2, align='c')
        y = 1060 + headline_height(ti, 96, 900) - 20
        para(c, S(self.d, 'sub'), 540, y + 30, 40, prog(t, 0.6, 1.1), max_lines=3, align='c')
        if isinstance(of, int) and 1 < of <= 10:                     # countdown dots
            try: cur = int(re.sub(r'\D', '', rank) or 0)
            except ValueError: cur = 0
            for k in range(of):
                n = of - k
                on = n == cur; done = n > cur
                cx = 540 + (k - (of - 1) / 2) * 44
                circle(c, cx, 1640, 11 if on else 8, TH.acc if on else TH.muted, 1 if on else (0.85 if done else 0.35))


# ============================== 14. TEASER (trailer lines) ==============================
class Teaser(Scene):
    """Cinematic opener: letterbox bars, one short line at a time, the last one in the accent."""
    kind = 'teaser'

    @staticmethod
    def budget(d):
        n = max(1, len(d.get('lines') or []))
        return 1.2 * n + 0.6, 1.6 * n + 0.9

    def setup(self):
        self.lines = [str(l) for l in (self.d.get('lines') or [])][:4] or [S(self.d, 'text') or '']
        n = len(self.lines)
        self.slot = (self.dur - 0.5) / n

    def sounds(self):
        n = len(self.lines)
        for i in range(n):
            t0 = 0.25 + i * self.slot
            if i == n - 1:
                if n > 1: self.at(t0 - 1.0, 'riser', 0.6, dur=1.0)
                self.at(t0, 'boom', 0.8); self.shake(t0, 8, 0.4)
            else:
                self.at(t0, 'impact', 0.5)

    def draw(self, c, t):
        self.cam(c, t, 540, 960, 1.0 + 0.04 * prog(t, 0, self.dur), )
        c.drawRect(skia.Rect.MakeWH(W, H), paint((0, 0, 0), 0.28 * prog(t, 0, 0.4)))
        n = len(self.lines)
        for i, ln in enumerate(self.lines):
            t0 = 0.25 + i * self.slot; t1 = t0 + self.slot
            last = i == n - 1
            pin = prog(t, t0, t0 + 0.45)
            pout = 0 if last else prog(t, t1 - 0.3, t1)
            a = e_out3(pin) * (1 - pout)
            if a <= 0.003: continue
            size, lines = _layout(ln, 124, 800, 960, 3, -0.03)
            with xf(c, 0, 0, lerp(1.1, 1, e_out5(pin)) * (1 + 0.04 * pout), 0, 540, 960), layer(c, a):
                hh = size * 1.1 * len(lines)
                headline(c, ln, ln if last else '', 540, 960 - hh / 2 + size * 0.8, 124, 1.0, 800, max_lines=3, track_em=-0.03, align='c')
        bar = 230 * e_out5(prog(t, 0, 0.5))                           # letterbox
        c.drawRect(skia.Rect.MakeXYWH(0, 0, W, bar), paint((0, 0, 0), 0.92))
        c.drawRect(skia.Rect.MakeXYWH(0, H - bar, W, bar), paint((0, 0, 0), 0.92))


REGISTRY = {cls.kind: cls for cls in (Hook, Title, Code, Statement, Bullets, Features, Stats, Steps, Terminal, CTA,
                                      Quote, Chapter, Rank, Teaser)}
