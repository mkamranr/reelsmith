"""Turns a storyboard into a timed list of scenes and draws any frame of it."""
import math

import numpy as np
import skia

from .lib import *
from .scenes import Ctx, REGISTRY

TR = 0.42      # transition overlap, seconds
BEAT = 0.5     # 120 BPM — cuts land on beats so the music bed lines up


def allocate(scene_dicts, total, beat=BEAT):
    """Fit scenes into `total` seconds. Drops low-priority middle scenes if even the minimums can't fit,
    then distributes time proportionally to each scene's ideal length and snaps cuts to the beat grid."""
    scenes = [s for s in scene_dicts if s.get('type') in REGISTRY]
    if not scenes: raise ValueError('storyboard has no usable scenes')
    budgets = [REGISTRY[s['type']].budget(s) for s in scenes]

    # drop from the middle (keep first + last) until minimums fit
    drop_order = ['statement', 'terminal', 'stats', 'title', 'bullets', 'steps', 'features', 'code']
    while sum(b[0] for b in budgets) > total and len(scenes) > 2:
        idx = None
        for kind in drop_order:
            cand = [i for i, s in enumerate(scenes[1:-1], 1) if s['type'] == kind]
            if cand: idx = cand[-1]; break
        if idx is None: idx = len(scenes) // 2
        scenes.pop(idx); budgets.pop(idx)

    mins = np.array([b[0] for b in budgets]); ideals = np.array([b[1] for b in budgets])
    if mins.sum() >= total:
        d = mins * total / mins.sum()
    else:
        d = mins.copy(); spare = total - mins.sum()
        want = np.maximum(ideals - mins, 0.01)
        d += spare * want / want.sum()
    # snap boundaries to the beat grid
    bounds = np.concatenate([[0], np.cumsum(d)])
    bounds = np.round(bounds / beat) * beat
    bounds[-1] = total
    for i in range(1, len(bounds)):
        if bounds[i] - bounds[i - 1] < 1.5: bounds[i] = min(total, bounds[i - 1] + 1.5)
    return [(s, float(bounds[i]), float(bounds[i + 1] - bounds[i])) for i, s in enumerate(scenes)]


class Timeline:
    def __init__(self, sb):
        self.sb = sb
        self.duration = float(sb.get('duration', 45))
        from . import templates as _T
        src = sb.get('accent_source')
        if src is None and sb.get('accent'):                  # storyboards made before templates existed
            src = 'planner' if _T.get(sb.get('template'))['accent_free'] else 'template'
        use = src == 'user' or (src == 'planner' and _T.get(sb.get('template'))['accent_free'])
        apply_template(sb.get('template'), sb.get('accent') if use else None)
        self.beat = 60.0 / TH.music['bpm']
        self.name = sb.get('name') or sb.get('title') or 'Reelsmith'
        self.ctx = Ctx(self.name)
        plan = allocate(sb['scenes'], self.duration, self.beat)
        self.scenes = []
        for i, (d, t0, dur) in enumerate(plan):
            cls = REGISTRY[d['type']]
            self.scenes.append(cls(d, t0, dur, self.ctx, i, first=(i == 0), last=(i == len(plan) - 1)))
        for sc in self.scenes[:-1]:
            self.ctx.sfx(sc.t0 + sc.dur - 0.22, 'whoosh', 0.9, dur=0.7, up=(sc.out == 'up'))
        rng = np.random.default_rng(7)
        sl = np.zeros((4, 4, 4), np.uint8); sl[0, :, 3] = 90; sl[1, :, 3] = 25
        self.scan = skia.Image.fromarray(sl).makeShader(skia.TileMode.kRepeat, skia.TileMode.kRepeat)
        self.grain = []
        for _ in range(6):
            n = rng.integers(0, 255, (480, 270), dtype=np.uint8)
            self.grain.append(skia.Image.fromarray(np.ascontiguousarray(np.dstack([n, n, n, np.full_like(n, 255)]))))
        self.hud_from = self.scenes[2].t0 if len(self.scenes) > 3 else 1e9
        self.hud_to = self.scenes[-1].t0

    @property
    def events(self): return self.ctx.events

    def plan_summary(self):
        return [{'type': s.kind, 'start': round(s.t0, 2), 'duration': round(s.dur, 2)} for s in self.scenes]

    # ---------- layers ----------
    # ---------- backgrounds, one per template style ----------
    def background(self, c, t, intensity=1.0, si=0.0):
        getattr(self, '_bg_' + TH.bg_style, self._bg_grid)(c, t, intensity, si)

    def _wash(self, c, x, y, r, rgb, a):
        sh = skia.GradientShader.MakeRadial(skia.Point(x, y), r, [col(rgb, a), col(rgb, 0)])
        c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=sh))

    def _bg_grid(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        self._wash(c, 120 + 60 * math.sin(t * 0.25), 260 + 80 * math.cos(t * 0.21), 900, TH.acc, 0.20 * inten)
        self._wash(c, 980 + 50 * math.cos(t * 0.3), 1700 + 70 * math.sin(t * 0.23), 800, TH.acc, 0.13 * inten)
        step = 90; off = (-t * 6) % step
        p = paint(TH.border, 0.55, stroke=1.2)
        for x in range(0, W + step, step): c.drawLine(x, 0, x, H, p)
        yy = off - step
        while yy < H + step:
            c.drawLine(0, yy, W, yy, p); yy += step
        mask = skia.GradientShader.MakeRadial(skia.Point(540, 900), 1050, [col(TH.bg, 0), col(TH.bg, 0.25), col(TH.bg, 1)], [0, 0.45, 1])
        c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=mask))

    def _bg_paper(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        self._wash(c, 540, 700, 1100, (255, 255, 255), 0.55)               # page lit from above
        p = paint(TH.border, 0.9, stroke=1.5)
        for x in (64, W - 64): c.drawLine(x, 166, x, H - 120, p)            # column rules
        c.drawLine(64, 166, W - 64, 166, paint(TH.text, 0.85, stroke=2))     # masthead rule
        c.drawLine(64, H - 120, W - 64, H - 120, p)
        self._wash(c, W - 80, 260, 520, TH.acc, 0.05 * inten)

    def _bg_crt(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        self._wash(c, 540, 900, 1100, TH.acc, (0.07 + 0.01 * math.sin(t * 9)) * inten)
        pts = [skia.Point(x, y) for x in range(30, W, 60) for y in range(30 + int(t * 8) % 60, H, 60)]
        c.drawPoints(skia.Canvas.kPoints_PointMode, pts, paint(TH.acc, 0.16, stroke=3, cap_round=True))

    def _bg_pop(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        cols, n = TH.bg_colors, len(TH.bg_colors)
        k, fr = int(si), e_io3(si - int(si))
        def pick(j): return mix(cols[(k + j) % n], cols[(k + j + 1) % n], fr)
        ow = paint(TH.border, 1, stroke=6)
        # big circle top-right, rounded square bottom-left, small circle left: colours shift scene by scene
        cx, cy, r = 975 + 20 * math.sin(t * 0.6), 190 + 18 * math.cos(t * 0.5), 250
        c.drawCircle(cx, cy, r, paint(pick(0))); c.drawCircle(cx, cy, r, ow)
        c.save(); c.translate(150, 1720); c.rotate(t * 8 % 360)
        rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-200, -200, 400, 400), 80, 80)
        c.drawRRect(rr, paint(pick(2))); c.drawRRect(rr, ow); c.restore()
        c.drawCircle(40, 980 + 30 * math.sin(t * 0.8), 90, paint(pick(3))); c.drawCircle(40, 980 + 30 * math.sin(t * 0.8), 90, ow)
        for i in range(5):                                                  # confetti dots
            x = (180 + i * 197 + t * 22 * (1 + i % 3)) % W; y = 120 + (i * 331) % 1600
            c.drawCircle(x, y, 9, paint(TH.border, 0.85))

    def _bg_minimal(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        self._wash(c, 540, 820, 1000, (255, 255, 255), 0.85)
        self._wash(c, 940 + 40 * math.sin(t * 0.2), 160, 700, TH.acc, 0.05 * inten)

    def _bg_aurora(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        cols = TH.bg_colors
        spots = [(200, 380, 0.17, 0.0), (900, 760, 0.13, 1.7), (300, 1400, 0.11, 3.1), (860, 1750, 0.15, 4.4)]
        for (x, y, sp, ph), rgb in zip(spots, cols):
            self._wash(c, x + 180 * math.sin(t * sp + ph), y + 140 * math.cos(t * sp * 1.3 + ph), 760, rgb, 0.55 * min(1.3, inten))
        self._wash(c, 540, 960, 1300, TH.bg, 0.0)

    def post_fx(self, c, f):
        if TH.vignette > 0:
            v = skia.GradientShader.MakeRadial(skia.Point(540, 960), 1250, [col((0, 0, 0), 0), col((0, 0, 0), 0), col((0, 0, 0), TH.vignette)], [0, 0.55, 1])
            c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=v))
        if TH.scanlines:
            c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=self.scan, Alphaf=0.9))
        if TH.grain > 0:
            c.drawImageRect(self.grain[f % len(self.grain)], skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kNearest),
                            skia.Paint(Alphaf=TH.grain, BlendMode=skia.BlendMode.kOverlay))

    def hud(self, c, t):
        rrect(c, 0, 0, W * (t / self.duration), 7, 0, shader=acc_grad(0, 0, W, 0))
        a = prog(t, self.hud_from + 0.2, self.hud_from + 0.8) * (1 - prog(t, self.hud_to - 0.3, self.hud_to + 0.2))
        if a <= 0: return
        idx = next((i for i, s in enumerate(self.scenes) if s.t0 <= t < s.t0 + s.dur), len(self.scenes) - 1) + 1
        rrect(c, 70, 128, 22, 4, 2, TH.acc, a)
        label = self.name.upper()
        fs = fit_size(label, 'mono', 800, 640, 22, 14, track_em=0.14)
        text(c, label, 104, 140, M(800, fs), TH.muted, a, track=fs * 0.14)
        text(c, f"{idx:02d} / {len(self.scenes):02d}", 1010, 140, M(700, 22), TH.muted, a, 'r', track=2)

    # ---------- frame ----------
    def _scene_index(self, t):
        for i, sc in enumerate(self.scenes):
            if t < sc.t0 + sc.dur:
                return i + (prog(t, sc.t0 + sc.dur - 0.15, sc.t0 + sc.dur + 0.3) if i < len(self.scenes) - 1 else 0)
        return len(self.scenes) - 1

    def _draw_glitched(self, c, sc, tl, amt, t):
        """Draw a scene in horizontal slices pushed sideways (the Terminal template's cut)."""
        bands = 9
        for b in range(bands):
            y0, y1 = H * b / bands, H * (b + 1) / bands
            dx = amt * 90 * math.sin(b * 12.9898 + int(t * 30) * 4.1414)
            c.save(); c.clipRect(skia.Rect.MakeLTRB(0, y0, W, y1)); c.translate(dx, 0)
            sc.draw(c, tl); c.restore()

    def render_frame(self, c, f):
        t = f / FPS
        title_like = [s for s in self.scenes if s.kind == 'title']
        inten = 1.0
        for s in title_like: inten += 0.6 * prog(t, s.t0 + 1.0, s.t0 + 2.0) * (1 - prog(t, s.t0 + s.dur - 0.4, s.t0 + s.dur + 0.2))
        last = self.scenes[-1]; inten += 0.5 * prog(t, last.t0 + 0.3, last.t0 + 1.3)
        self.background(c, t, inten, self._scene_index(t))
        for i, sc in enumerate(self.scenes):
            s, e = sc.t0, sc.t0 + sc.dur
            has_out = i < len(self.scenes) - 1
            if not (s <= t < e + (TR if has_out else 0)): continue
            tl = t - s
            a, z, dx, dy, glitch = 1.0, 1.0, 0.0, 0.0, 0.0
            if t >= e:                                              # outgoing
                style = TH.transition or sc.out
                p = prog(t, e, e + TR); pe = e_in3(p)
                if style == 'zoom': a, z = 1 - pe, 1 + 0.35 * pe
                elif style == 'up': a, dy = 1 - pe, -700 * pe
                elif style == 'left': a, dx = 1 - pe, -760 * e_in3(p)
                elif style == 'pop': a, z = 1 - pe, 1 - 0.12 * pe
                elif style == 'dissolve': a, z = 1 - e_io3(p), 1 + 0.06 * p
                elif style == 'glitch': a, glitch = (1.0 if p < 0.5 else 0.0), p * 2
                else: a = 1 - e_io3(p)                              # fade
            if i > 0 and tl < TR:                                   # incoming
                style = TH.transition or self.scenes[i - 1].out
                p = prog(tl, 0, TR); po = e_out3(p)
                if style == 'zoom': a, z = a * po, z * lerp(0.82, 1, po)
                elif style == 'up': a, dy = a * po, dy + 600 * (1 - po)
                elif style == 'left': a, dx = a * po, dx + 760 * (1 - e_out5(p))
                elif style == 'pop': a, z = a * min(1, p * 3), z * lerp(1.18, 1, e_back(p, 2.2))
                elif style == 'dissolve': a, z = a * e_io3(p), z * lerp(0.97, 1, po)
                elif style == 'glitch': a, glitch = (a if p >= 0.5 else 0.0), max(glitch, (1 - p) * 2 if p >= 0.5 else 0)
                else: a = a * e_io3(p)
            if a <= 0.003: continue
            c.save()
            c.translate(540 + dx, 960 + dy); c.scale(z, z); c.translate(-540, -960)
            with layer(c, a):
                if glitch > 0.02: self._draw_glitched(c, sc, tl, min(1.0, glitch), t)
                else: sc.draw(c, tl)
            c.restore()
        if TH.transition == 'glitch':                               # flash of scanline noise on the cut
            for sc in self.scenes[:-1]:
                g = 1 - abs(t - (sc.t0 + sc.dur + TR / 2)) / (TR / 2)
                if g > 0:
                    for k in range(6):
                        y = (k * 347 + int(t * 30) * 211) % H
                        c.drawRect(skia.Rect.MakeXYWH(0, y, W, 6 + k * 3), paint(TH.acc, 0.35 * g))
        self.hud(c, t)
        self.post_fx(c, f)
        fo = prog(t, self.duration - 0.7, self.duration); fi = 1 - prog(t, 0, 0.25)
        if max(fo, fi) > 0: c.drawRect(skia.Rect.MakeWH(W, H), paint(TH.bg, max(fo, fi)))
