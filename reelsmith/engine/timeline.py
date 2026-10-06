"""Turns a storyboard into a timed list of scenes and draws any frame of it."""
import math
import re

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
    pace = getattr(TH, 'pace', 1.0)                      # Pop cuts faster, Minimal holds longer
    budgets = [tuple(v * pace for v in REGISTRY[s['type']].budget(s)) for s in scenes]

    # drop from the middle (keep first + last) until minimums fit
    drop_order = ['statement', 'quote', 'terminal', 'stats', 'title', 'bullets', 'steps', 'features', 'chapter', 'rank', 'code', 'teaser']
    order = list(range(len(scenes)))                     # original positions, to put scenes back in place
    dropped = []
    while sum(b[0] for b in budgets) > total and len(scenes) > 2:
        idx = None
        for kind in drop_order:
            cand = [i for i, s in enumerate(scenes[1:-1], 1) if s['type'] == kind]
            if cand: idx = cand[-1]; break
        if idx is None:
            mids = [i for i in range(1, len(scenes) - 1) if scenes[i]['type'] != 'scroll']
            if not mids: break
            idx = min(mids, key=lambda i: abs(i - len(scenes) // 2))
        dropped.append((order.pop(idx), scenes.pop(idx), budgets.pop(idx)))
    # dropping overshoots: put back the most important dropped scenes that now fit
    for pos, sc, bud in reversed(dropped):
        if sum(b[0] for b in budgets) + bud[0] <= total:
            k = next((i for i, o in enumerate(order) if o > pos), len(order))
            order.insert(k, pos); scenes.insert(k, sc); budgets.insert(k, bud)

    mins = np.array([b[0] for b in budgets]); ideals = np.array([b[1] for b in budgets])
    if mins.sum() >= total:
        d = mins * total / mins.sum()
    else:
        d = mins.copy(); spare = total - mins.sum()
        want = np.maximum(ideals - mins, 0.01)
        d += spare * want / want.sum()
    # the page tour may be long (a long README read slowly) but never more than 45% of the video
    for i, sc in enumerate(scenes):
        if sc['type'] == 'scroll' and d[i] > 0.45 * total and len(scenes) > 1:
            extra = d[i] - 0.45 * total; d[i] = 0.45 * total
            others = [j for j in range(len(scenes)) if j != i]
            w = np.array([max(ideals[j] - d[j], 0.05) for j in others]); w = w / w.sum()
            for j, k in zip(others, w): d[j] += extra * k
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
        self.ctx.asset_dir = sb.get('asset_dir') or ''
        self.loop = bool(sb.get('loop', False))
        self.ctx.handle = bool((sb.get('handle') or '').strip())
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
        h = (sb.get('handle') or '').strip()
        self.handle = ('@' + h if h and not h.startswith('@') and ' ' not in h and '.' not in h and '/' not in h else h)[:40]
        self.captions = self._caption_groups(sb.get('spoken') or []) if sb.get('burn_captions', True) else []
        self.ticker = '   •   '.join(x for x in (self._headline(sc.d) for sc in self.scenes) if x) or self.name
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

    def _bg_cinema(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        warm = [(255, 140, 60), (210, 70, 40), (255, 200, 120)]
        for k, (x, y, sp) in enumerate(((180, 500, 0.11), (920, 1300, 0.08), (600, 260, 0.06))):
            self._wash(c, x + 220 * math.sin(t * sp + k * 2.1), y + 160 * math.cos(t * sp * 1.4 + k), 820, warm[k], (0.16, 0.11, 0.08)[k] * inten)
        yy = 760 + 120 * math.sin(t * 0.13)                        # anamorphic streak
        a = 0.10 + 0.06 * math.sin(t * 0.7)
        g = skia.GradientShader.MakeLinear([skia.Point(0, yy), skia.Point(W, yy)], [col((255, 190, 120), 0), col((255, 190, 120), a), col((255, 190, 120), 0)])
        c.drawRect(skia.Rect.MakeXYWH(0, yy - 2, W, 4), skia.Paint(Shader=g))
        self._wash(c, 540 + 300 * math.sin(t * 0.13), yy, 260, (255, 210, 150), a * 0.8)

    def _bg_studio(self, c, t, inten, si):
        g = skia.GradientShader.MakeLinear([skia.Point(0, 0), skia.Point(0, H)], [col(mix(TH.bg, (255, 255, 255), 0.07)), col(TH.bg)])
        c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=g))
        self._wash(c, 540 + 60 * math.sin(t * 0.2), -120, 1250, (255, 255, 255), 0.10)       # key light
        self._wash(c, 180, 1300, 900, TH.acc, 0.10 * inten); self._wash(c, 980, 600, 800, TH.acc2, 0.08 * inten)
        hz = 1560                                                                      # floor
        fl = skia.GradientShader.MakeLinear([skia.Point(0, hz), skia.Point(0, H)], [col((0, 0, 0), 0), col((0, 0, 0), 0.45)])
        c.drawRect(skia.Rect.MakeXYWH(0, hz, W, H - hz), skia.Paint(Shader=fl))
        c.drawLine(0, hz, W, hz, paint((255, 255, 255), 0.06, stroke=2))

    def _bg_broadcast(self, c, t, inten, si):
        c.drawColor(col(TH.bg))
        self._wash(c, 900, 300, 1000, (40, 110, 255), 0.30 * inten); self._wash(c, 120, 1500, 800, TH.acc, 0.10 * inten)
        c.save(); c.rotate(-24, 540, 960)
        off = (t * 60) % 120
        p = paint((255, 255, 255), 0.035)
        for k in range(-20, 30):
            c.drawRect(skia.Rect.MakeXYWH(-600 + k * 120 + off, -600, 46, 3200), p)
        c.restore()
        pts = [skia.Point(x, y) for x in range(40, W, 48) for y in range(40, H, 48) if (x * 7 + y * 3) % 5 == 0]
        c.drawPoints(skia.Canvas.kPoints_PointMode, pts, paint((120, 160, 255), 0.18, stroke=3, cap_round=True))

    def post_fx(self, c, f):
        if TH.vignette > 0:
            v = skia.GradientShader.MakeRadial(skia.Point(540, 960), 1250, [col((0, 0, 0), 0), col((0, 0, 0), 0), col((0, 0, 0), TH.vignette)], [0, 0.55, 1])
            c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=v))
        if TH.scanlines:
            c.drawRect(skia.Rect.MakeWH(W, H), skia.Paint(Shader=self.scan, Alphaf=0.9))
        if TH.grain > 0:
            c.drawImageRect(self.grain[f % len(self.grain)], skia.Rect.MakeWH(W, H), skia.SamplingOptions(skia.FilterMode.kNearest),
                            skia.Paint(Alphaf=TH.grain, BlendMode=skia.BlendMode.kOverlay))

    # ---------- overlays ----------
    @staticmethod
    def _headline(d):
        for k in ('title', 'caption', 'text', 'line', 'tagline', 'punch'):
            v = d.get(k)
            if isinstance(v, str) and 3 < len(v) <= 70: return v.rstrip('.')
        return ''

    def hud(self, c, t):
        style = TH.hud
        a = prog(t, self.hud_from + 0.2, self.hud_from + 0.8) * (1 - prog(t, self.hud_to - 0.3, self.hud_to + 0.2))
        if style in ('progress', 'deck'):
            rrect(c, 0, 0, W * (t / self.duration), 7, 0, shader=acc_grad(0, 0, W, 0))
        if style == 'deck' and a > 0:
            idx = next((i for i, s in enumerate(self.scenes) if s.t0 <= t < s.t0 + s.dur), len(self.scenes) - 1) + 1
            rrect(c, 70, 128, 22, 4, 2, TH.acc, a)
            label = self.name.upper()
            fs = fit_size(label, 'mono', 800, 640, 22, 14, track_em=0.14)
            text(c, label, 104, 140, M(800, fs), TH.muted, a, track=fs * 0.14)
            text(c, f"{idx:02d} / {len(self.scenes):02d}", 1010, 140, M(700, 22), TH.muted, a, 'r', track=2)
        elif style == 'terminal':
            al = prog(t, 0.3, 0.9) * (1 - prog(t, self.duration - 0.8, self.duration))
            if al > 0:
                path = '~/' + re.sub(r'[^a-z0-9-]+', '-', self.name.lower()).strip('-')[:24]
                x = 64 + text(c, path, 64, 128, M(700, 24), TH.acc, al)
                x += text(c, '  main', x, 128, M(500, 24), TH.muted, al)
                text(c, f'{int(t // 60):02d}:{int(t % 60):02d}', 1016, 128, M(500, 24), TH.muted, al, 'r')
                line(c, 64, 150, 1016, 150, TH.border, al, 2, False)
        elif style == 'broadcast':
            ab = prog(t, 0.2, 0.7) * (1 - prog(t, self.duration - 0.6, self.duration))
            if ab > 0:
                with xf(c, -260 * (1 - e_out5(ab)), 0):
                    rrect(c, 56, 110, 92, 52, 4, TH.acc)
                    text(c, 'NEW', 102, 147, I(900, 26), (255, 255, 255), 1, 'c', track=2)
                    nm = self.name.upper()[:26]; fs = fit_size(nm, 'inter', 800, 560, 26, 16)
                    w = tw(nm, I(800, fs), 1) + 40
                    rrect(c, 148, 110, w, 52, 4, (255, 255, 255))
                    text(c, nm, 168, 146, I(800, fs), TH.bg, 1, track=1)
                circle(c, 990, 136, 7 + 2 * math.sin(t * 5), TH.acc, ab)
                y0 = 1792                                      # ticker
                c.drawRect(skia.Rect.MakeXYWH(0, y0, W, 76), paint((255, 255, 255), ab))
                rrect(c, 0, y0, 210, 76, 0, TH.acc, ab)
                text(c, 'LATEST', 105, y0 + 50, I(900, 28), (255, 255, 255), ab, 'c', track=2)
                c.save(); c.clipRect(skia.Rect.MakeXYWH(210, y0, W - 210, 76))
                ft = I(700, 30); tick = self.ticker + '   •   '; tw_ = tw(tick, ft)
                x = 230 - (t * 120) % max(tw_, 1)
                while x < W:
                    text(c, tick, x, y0 + 50, ft, TH.bg, ab); x += tw_
                c.restore()
        elif style == 'cinema':
            bar = 150 * e_out5(prog(t, 0, 0.8))
            c.drawRect(skia.Rect.MakeXYWH(0, 0, W, bar), paint((0, 0, 0), 1))
            c.drawRect(skia.Rect.MakeXYWH(0, H - bar, W, bar), paint((0, 0, 0), 1))
            af = prog(t, 0.6, 1.2) * (1 - prog(t, self.duration - 0.8, self.duration))
            if af > 0:
                fr = int(round(t * FPS)) % FPS
                text(c, f'{int(t // 3600):02d}:{int(t // 60) % 60:02d}:{int(t) % 60:02d}:{fr:02d}', 1010, H - 62, M(500, 22), TH.muted, af * 0.8, 'r', track=2)
                text(c, (self.handle or self.name.upper())[:30], 70, H - 62, M(700, 24 if self.handle else 22), TH.text if self.handle else TH.muted, af * (0.95 if self.handle else 0.8), track=2 if self.handle else 4)

    def draw_handle(self, c, t):
        """Your handle, visible near the bottom for the whole video, in the template's style."""
        if not self.handle or TH.hud == 'cinema': return          # Cinema shows it in the letterbox (hud)
        a = prog(t, 0.6, 1.2) * (1 - prog(t, self.duration - 0.7, self.duration))
        if a <= 0: return
        h = self.handle
        if TH.hud == 'broadcast':
            f = I(800, 26); w = tw(h, f) + 40
            rrect(c, W - 60 - w, 1736, w, 46, 3, TH.acc, a)
            text(c, h, W - 60 - w / 2, 1767, f, (255, 255, 255), a, 'c')
        elif TH.hud == 'terminal':
            f = M(700, 28)
            x = 64 + text(c, '$ ', 64, 1790, f, TH.acc, a)
            text(c, h, x, 1790, f, TH.text, a * 0.9)
        elif TH.caption_style == 'bold':                            # Pop: a sticker
            f = I(900, 32); w = tw(h, f) + 52
            with xf(c, 0, 0, 1, -3, 540, 1745):
                rrect(c, 540 - w / 2 + 6, 1716 + 6, w, 60, 30, TH.border, a)
                rrect(c, 540 - w / 2, 1716, w, 60, 30, (255, 255, 255), a)
                rrect(c, 540 - w / 2, 1716, w, 60, 30, TH.border, a, stroke=4)
                text(c, h, 540, 1757, f, (17, 17, 17), a, 'c')
        else:
            f = I(600, 28); w = tw(h, f) + 70
            rrect(c, 540 - w / 2, 1712, w, 56, 28, TH.surf, a * 0.82)
            circle(c, 540 - w / 2 + 26, 1740, 6, TH.acc, a)
            text(c, h, 540 - w / 2 + 44, 1750, f, TH.text, a)

    # spoken-word captions, burned in (Reels/Shorts are mostly watched muted)
    @staticmethod
    def _caption_groups(segs):
        groups = []
        for sg in segs:
            words = sg.get('text', '').split()
            if not words: continue
            weights = [len(w) + 1.5 for w in words]; total = sum(weights)
            t, timed = sg['start'], []
            for w, k in zip(words, weights):
                d = (sg['end'] - sg['start']) * k / total; timed.append((w, t, t + d)); t += d
            cur = []
            for item in timed:
                cur.append(item)
                chars = sum(len(x[0]) + 1 for x in cur)
                if len(cur) >= 4 or chars >= 22 or item[0][-1:] in '.!?,;:':
                    groups.append(cur); cur = []
            if cur: groups.append(cur)
        return [(g[0][1], g[-1][2], g) for g in groups]

    def draw_captions(self, c, t):
        g = next((x for x in self.captions if x[0] - 0.05 <= t < x[1] + 0.12), None)
        if not g: return
        start, end, words = g
        style = TH.caption_style
        size = {'bold': 70, 'strap': 46, 'film': 44, 'mono': 44, 'serif': 52, 'clean': 50}.get(style, 54)
        weight = 900 if style == 'bold' else 600 if style in ('clean', 'film') else 800
        f = M(700, size) if style == 'mono' else I(weight, size)
        a = clamp((t - start + 0.05) / 0.12) * clamp((end + 0.12 - t) / 0.12)
        sp = tw(' ', f); widths = [tw(w, f) for w, _, _ in words]
        total = sum(widths) + sp * (len(words) - 1)
        y = {'film': H - 230, 'strap': 1640, 'bold': 1420}.get(style, 1560)
        if TH.hud == 'cinema': y = H - 196
        left = style == 'strap'
        x = 80 if left else 540 - total / 2
        if style == 'strap':
            rrect(c, 60, y - size - 22, total + 60, size + 52, 4, TH.panel, a * 0.95)
            rrect(c, 60, y - size - 22, 10, size + 52, 2, TH.acc, a)
            x = 100
        elif style in ('pill', 'clean', 'serif', 'mono'):
            bgc = TH.surf if style != 'mono' else TH.panel
            rrect(c, x - 30, y - size - 14, total + 60, size + 42, (size + 42) / 2, bgc, a * 0.92)
        for (w, ws, we), ww in zip(words, widths):
            on = ws <= t < we + 0.05
            past = t >= we
            rgb = TH.acc if on else TH.text
            if style == 'bold':
                k = 1.12 if on else 1.0
                c.save(); c.translate(x + ww / 2, y - size * 0.35); c.scale(k, k); c.translate(-(x + ww / 2), -(y - size * 0.35))
                c.drawString(w, x, y, f, paint((0, 0, 0), a, stroke=size * 0.16, cap_round=True))
                text(c, w, x, y, f, TH.acc if on else (255, 255, 255), a)
                c.restore()
            else:
                text(c, w, x, y, f, rgb if (on or past or style != 'clean') else TH.muted, a)
            x += ww + sp

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
        """Frame 0 is a full, readable frame (no fade-in: muted viewers decide in the first second). With `loop`, the
        last 0.45 s blends into an exact redraw of frame 0 so a replay is seamless; otherwise it fades out."""
        t = f / FPS
        self._draw(c, f)
        if self.loop:
            pl = prog(t, self.duration - 0.45, self.duration)
            if pl > 0:
                c.saveLayer(None, skia.Paint(Alphaf=e_io3(pl)))
                self._draw(c, 0)
                c.restore()
        else:
            fo = prog(t, self.duration - 0.7, self.duration)
            if fo > 0: c.drawRect(skia.Rect.MakeWH(W, H), paint(TH.bg, fo))

    def _draw(self, c, f):
        t = f / FPS
        title_like = [s for s in self.scenes if s.kind == 'title']
        inten = 1.0
        for s in title_like: inten += 0.6 * prog(t, s.t0 + 1.0, s.t0 + 2.0) * (1 - prog(t, s.t0 + s.dur - 0.4, s.t0 + s.dur + 0.2))
        last = self.scenes[-1]; inten += 0.5 * prog(t, last.t0 + 0.3, last.t0 + 1.3)
        self.background(c, t, inten, self._scene_index(t))
        for i, sc in enumerate(self.scenes):
            s, e = sc.t0, sc.t0 + sc.dur
            has_out = i < len(self.scenes) - 1
            if not (s <= t < e + (TH.tr if has_out else 0)): continue
            tl = t - s
            a, z, dx, dy, glitch = 1.0, 1.0, 0.0, 0.0, 0.0
            if t >= e:                                              # outgoing
                style = TH.transition or sc.out
                p = prog(t, e, e + TH.tr); pe = e_in3(p)
                if style == 'zoom': a, z = 1 - pe, 1 + 0.35 * pe
                elif style == 'up': a, dy = 1 - pe, -700 * pe
                elif style == 'left': a, dx = 1 - pe, -760 * e_in3(p)
                elif style == 'pop': a, z = 1 - pe, 1 - 0.12 * pe
                elif style == 'dissolve': a, z = 1 - e_io3(p), 1 + 0.06 * p
                elif style == 'glitch': a, glitch = (1.0 if p < 0.5 else 0.0), p * 2
                else: a = 1 - e_io3(p)                              # fade
            if i > 0 and tl < TH.tr:                                # incoming
                style = TH.transition or self.scenes[i - 1].out
                p = prog(tl, 0, TH.tr); po = e_out3(p)
                if style == 'zoom': a, z = a * po, z * lerp(0.82, 1, po)
                elif style == 'up': a, dy = a * po, dy + 600 * (1 - po)
                elif style == 'left': a, dx = a * po, dx + 760 * (1 - e_out5(p))
                elif style == 'pop': a, z = a * min(1, p * 3), z * lerp(1.18, 1, e_back(p, 2.2))
                elif style == 'dissolve': a, z = a * e_io3(p), z * lerp(0.97, 1, po)
                elif style == 'glitch': a, glitch = (a if p >= 0.5 else 0.0), max(glitch, (1 - p) * 2 if p >= 0.5 else 0)
                else: a = a * e_io3(p)
            if a <= 0.003: continue
            # motion blur along the direction of travel while a transition moves the scene
            st_now = TH.transition or (sc.out if t >= e else (self.scenes[i - 1].out if i > 0 else None))
            mv = 0.0
            if t >= e: mv = math.sin(math.pi * prog(t, e, e + TH.tr))
            elif i > 0 and tl < TH.tr: mv = math.sin(math.pi * prog(tl, 0, TH.tr))
            bx, by = {'left': (24, 0), 'up': (0, 24), 'zoom': (9, 9), 'pop': (7, 7)}.get(st_now, (0, 0))
            TH.entrance_now = TH.entrances[sc.index % len(TH.entrances)]
            c.save()
            c.translate(540 + dx, 960 + dy); c.scale(z, z); c.translate(-540, -960)
            if mv * max(bx, by) > 0.8:
                c.saveLayer(None, skia.Paint(Alphaf=clamp(a), ImageFilter=skia.ImageFilters.Blur(bx * mv, by * mv)))
                if glitch > 0.02: self._draw_glitched(c, sc, tl, min(1.0, glitch), t)
                else: sc.draw(c, tl)
                c.restore()
            else:
                with layer(c, a):
                    if glitch > 0.02: self._draw_glitched(c, sc, tl, min(1.0, glitch), t)
                    else: sc.draw(c, tl)
            c.restore()
        if TH.transition == 'glitch':                               # flash of scanline noise on the cut
            for sc in self.scenes[:-1]:
                g = 1 - abs(t - (sc.t0 + sc.dur + TH.tr / 2)) / (TH.tr / 2)
                if g > 0:
                    for k in range(6):
                        y = (k * 347 + int(t * 30) * 211) % H
                        c.drawRect(skia.Rect.MakeXYWH(0, y, W, 6 + k * 3), paint(TH.acc, 0.35 * g))
        self.draw_captions(c, t)
        self.hud(c, t)
        self.draw_handle(c, t)
        self.post_fx(c, f)

