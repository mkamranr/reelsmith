"""Procedural audio: every sound effect is synthesized, then placed at the times the scenes registered.
A 120 BPM music bed is arranged around the scene plan (intro, groove, breakdown before the CTA, final hit)."""
import math

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 48000
rng = np.random.default_rng(1234)


def tvec(d): return np.arange(int(SR * d)) / SR
def env_ad(n, a, d, curve=4.0):
    t = np.arange(n) / SR
    e = np.where(t < a, t / max(a, 1e-4), np.exp(-(t - a) * curve / max(d, 1e-4)))
    return e
def bp(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], 'band', fs=SR, output='sos'); return signal.sosfilt(sos, x)
def lp(x, f, order=2):
    sos = signal.butter(order, f, 'low', fs=SR, output='sos'); return signal.sosfilt(sos, x)
def hp(x, f, order=2):
    sos = signal.butter(order, f, 'high', fs=SR, output='sos'); return signal.sosfilt(sos, x)


def sweep_noise(d, f0, f1, q=0.6, chunk=256):
    n = int(SR * d); x = rng.standard_normal(n); out = np.zeros(n)
    zi = None
    for i in range(0, n, chunk):
        fr = i / n
        fc = f0 * (f1 / f0) ** fr
        lo, hi = max(40, fc * (1 - q)), min(SR / 2 - 100, fc * (1 + q))
        b, a = signal.butter(1, [lo, hi], 'band', fs=SR)
        if zi is None: zi = signal.lfilter_zi(b, a) * 0
        out[i:i + chunk], zi = signal.lfilter(b, a, x[i:i + chunk], zi=zi)
    return out


def chirp(d, f0, f1, kind='exp'):
    t = tvec(d)
    if kind == 'exp':
        k = (f1 / f0) ** (1 / d)
        ph = 2 * np.pi * f0 * (k ** t - 1) / np.log(k) if f0 != f1 else 2 * np.pi * f0 * t
    else:
        ph = 2 * np.pi * (f0 * t + (f1 - f0) * t * t / (2 * d))
    return np.sin(ph)


def stereo(m, pan=0.0):
    l = math.cos((pan + 1) * math.pi / 4); r = math.sin((pan + 1) * math.pi / 4)
    return np.stack([m * l, m * r], 1)


# ---------------- SFX ----------------
def s_whoosh(dur=0.7, up=False, **k):
    f0, f1 = (350, 4200) if up else (3800, 300)
    x = sweep_noise(dur, f0, f1, 0.7)
    t = np.linspace(0, 1, len(x))
    e = (np.sin(np.pi * t ** 0.75) ** 2)
    x = x * e
    x /= np.abs(x).max() + 1e-9
    # pan sweep
    pan = np.linspace(-0.6, 0.6, len(x))
    l = np.cos((pan + 1) * np.pi / 4); r = np.sin((pan + 1) * np.pi / 4)
    return np.stack([x * l, x * r], 1) * 0.55


def s_swish(**k):
    x = sweep_noise(0.28, 5200, 1400, 0.5)
    t = np.linspace(0, 1, len(x)); x *= np.sin(np.pi * t ** 0.6) ** 2
    x /= np.abs(x).max() + 1e-9
    return stereo(x * 0.35, rng.uniform(-.4, .4))


def s_key(seed=0, **k):
    r = np.random.default_rng(seed)
    n = int(SR * 0.05)
    nz = hp(r.standard_normal(n), 1800) * env_ad(n, 0.0005, 0.006, 5)
    f = r.uniform(170, 260)
    body = np.sin(2 * np.pi * f * np.arange(n) / SR) * env_ad(n, 0.0008, 0.02, 5) * 0.5
    click2 = np.zeros(n); off = int(SR * r.uniform(0.012, 0.022))
    click2[off:off + 200] = hp(r.standard_normal(200), 3000) * np.exp(-np.arange(200) / 30) * 0.35
    x = nz * 0.8 + body + click2
    return stereo(x * r.uniform(0.6, 1.0) * 0.5, r.uniform(-.25, .25))


def s_click(**k):
    n = int(SR * 0.06)
    x = hp(rng.standard_normal(n), 2500) * env_ad(n, 0.0003, 0.004, 5)
    x += np.sin(2 * np.pi * 1800 * np.arange(n) / SR) * env_ad(n, 0.0005, 0.01, 6) * 0.4
    x2 = np.zeros(n); x2[int(SR * .035):] = x[:n - int(SR * .035)] * 0.6
    return stereo((x + x2) * 0.6)


def s_enter(**k):
    a = s_key(seed=99)[:, 0] * 1.4
    n = int(SR * 0.25)
    th = np.sin(2 * np.pi * chirp(0.25, 140, 60) * 0 + 2 * np.pi * 90 * np.arange(n) / SR) * env_ad(n, 0.001, 0.08, 5)
    out = np.zeros(n); out[:len(a)] += a; out += th * 0.6
    return stereo(out * 0.7)


def s_pop(f=600, **k):
    d = 0.16; n = int(SR * d)
    x = chirp(d, f * 1.6, f * 0.7) * env_ad(n, 0.002, 0.06, 5)
    x += chirp(d, f * 3.2, f * 1.4) * env_ad(n, 0.001, 0.03, 5) * 0.25
    return stereo(x * 0.55, rng.uniform(-.2, .2))


def s_tick(**k):
    n = int(SR * 0.03)
    f = rng.uniform(2600, 3600)
    x = np.sin(2 * np.pi * f * np.arange(n) / SR) * env_ad(n, 0.0005, 0.008, 5)
    x += hp(rng.standard_normal(n), 5000) * env_ad(n, 0.0002, 0.003, 5) * 0.4
    return stereo(x * 0.4, rng.uniform(-.3, .3))


def s_impact(big=False, **k):
    d = 1.6 if big else 0.9; n = int(SR * d)
    sub = chirp(d, 95 if big else 110, 34) * env_ad(n, 0.002, 0.55 if big else 0.32, 4)
    nz = lp(rng.standard_normal(n), 900) * env_ad(n, 0.001, 0.12 if big else 0.07, 4) * 0.9
    tr = hp(rng.standard_normal(n), 3000) * env_ad(n, 0.0002, 0.01, 5) * 0.5
    x = np.tanh((sub * 1.2 + nz + tr) * 1.6)
    if big:
        tail = bp(rng.standard_normal(n), 200, 2400) * env_ad(n, 0.02, 1.2, 4) * 0.25
        x = x + tail
    return stereo(x * (0.85 if big else 0.7))


def s_boom(**k): return s_impact(big=True)


def s_snap(**k):
    n = int(SR * 0.2)
    x = bp(rng.standard_normal(n), 1200, 7000) * env_ad(n, 0.0005, 0.02, 5)
    x += chirp(0.2, 1400, 500) * env_ad(n, 0.001, 0.05, 5) * 0.6
    x += chirp(0.2, 160, 60) * env_ad(n, 0.001, 0.07, 5) * 0.8
    return stereo(np.tanh(x * 1.5) * 0.6)


def bell(f, d, bright=1.0):
    n = int(SR * d); t = np.arange(n) / SR
    x = np.zeros(n)
    for m, a, dec in ((1, 1, 1.0), (2.0, .35 * bright, .5), (3.01, .18 * bright, .35), (4.2, .08 * bright, .2)):
        x += a * np.sin(2 * np.pi * f * m * t) * np.exp(-t * 3.2 / (d * dec))
    x *= np.minimum(1, t / 0.004)
    return x


def s_chime(notes=(0, 7, 12), **k):
    d = 1.6; n = int(SR * (d + 0.4)); out = np.zeros((n, 2))
    for i, nn in enumerate(notes):
        f = 880 * 2 ** (nn / 12)
        b = bell(f, d) * 0.25
        o = int(SR * 0.045 * i)
        out[o:o + len(b)] += stereo(b, -0.4 + 0.8 * i / max(1, len(notes) - 1))
    return out


def s_logo(**k):
    d = 2.6; n = int(SR * d); t = np.arange(n) / SR
    out = np.zeros((n, 2))
    chord = [57, 64, 69, 73, 76, 81]  # A major-ish voicing (midi)
    for i, m in enumerate(chord):
        f = 440 * 2 ** ((m - 69) / 12)
        for det, pan in ((-0.004, -0.5), (0.004, 0.5)):
            x = np.sin(2 * np.pi * f * (1 + det) * t + 0.3 * np.sin(2 * np.pi * f * 2 * t))
            e = np.minimum(1, t / 0.06) * np.exp(-t * 1.6)
            out += stereo(x * e * 0.07, pan)
    for i, m in enumerate([81, 85, 88, 93]):
        b = bell(440 * 2 ** ((m - 69) / 12), 1.4, 0.7) * 0.12
        o = int(SR * (0.03 + 0.06 * i)); out[o:o + len(b)] += stereo(b, -0.5 + i / 3)
    sub = np.sin(2 * np.pi * 55 * t) * np.minimum(1, t / 0.01) * np.exp(-t * 3) * 0.45
    out += stereo(sub)
    return out


def s_error(**k):
    d = 0.32; n = int(SR * d); t = np.arange(n) / SR
    sq = signal.square(2 * np.pi * 165 * t) * 0.5 + signal.square(2 * np.pi * 172 * t) * 0.5
    gate = ((t < 0.11) | ((t > 0.15) & (t < 0.27))).astype(float)
    gate = lp(gate, 200, 1)
    x = lp(sq, 1600) * gate
    return stereo(x * 0.32)


def s_scan(dur=0.65, **k):
    n = int(SR * dur); t = np.arange(n) / SR
    x = chirp(dur, 500, 1900) * (0.5 + 0.5 * np.sin(2 * np.pi * 28 * t)) * 0.25
    x += sweep_noise(dur, 800, 5000, 0.3) * 0.6
    x *= np.sin(np.pi * t / dur) ** 1.2
    return stereo(x * 0.45)


def s_riser(dur=1.2, **k):
    n = int(SR * dur); t = np.arange(n) / SR
    nz = sweep_noise(dur, 300, 7000, 0.5); nz /= np.abs(nz).max() + 1e-9
    tone = chirp(dur, 110, 880) * 0.3
    e = (t / dur) ** 2.2
    x = (nz * 0.6 + tone) * e
    x[-int(SR * 0.01):] *= np.linspace(1, 0, int(SR * 0.01))
    return stereo(x * 0.6)


def s_shimmer(dur=1.8, **k):
    n = int(SR * (dur + 0.8)); out = np.zeros((n, 2))
    sc = [0, 2, 4, 7, 9, 12, 14, 16, 19]
    for i in range(14):
        nn = sc[(i * 4) % len(sc)]
        b = bell(1320 * 2 ** (nn / 12), 0.7, 0.5) * 0.07
        o = int(SR * i * dur / 14); out[o:o + len(b)] += stereo(b, math.sin(i * 1.3) * 0.7)
    return out


def s_strike(**k):
    x = sweep_noise(0.22, 4200, 900, 0.4)
    t = np.linspace(0, 1, len(x)); x *= np.sin(np.pi * t ** 0.5) ** 2
    x /= np.abs(x).max() + 1e-9
    x += chirp(0.22, 900, 300) * np.exp(-t * 6) * 0.3
    return stereo(x * 0.4, 0.1)


SFX = dict(strike=s_strike, whoosh=s_whoosh, swish=s_swish, key=s_key, click=s_click, enter=s_enter, pop=s_pop, tick=s_tick,
           impact=s_impact, boom=s_boom, snap=s_snap, chime=s_chime, logo=s_logo, error=s_error, scan=s_scan,
           riser=s_riser, shimmer=s_shimmer)


def place(bus, x, t, g):
    i = int(round(t * SR))
    if i >= len(bus): return
    j = min(len(bus), i + len(x))
    bus[i:j] += x[:j - i] * g



# ---------------- music bed (120 BPM) ----------------
BEAT = 0.5
def midi(m): return 440 * 2 ** ((m - 69) / 12)
def saw(f, t, det=0.0): return 2 * ((f * (1 + det) * t) % 1) - 1


PROGS = {'minor': [[45, 57, 60, 64], [41, 57, 60, 65], [48, 55, 60, 64], [43, 55, 59, 62]],    # Am F C G
         'major': [[48, 55, 60, 64], [43, 55, 59, 62], [45, 57, 60, 64], [41, 57, 60, 65]]}    # C G Am F
DEFAULT_STYLE = dict(bpm=120, prog='minor', pad='saw', pad_gain=0.08, pad_lp=1400, arp=None, arp_gain=0.0,
                     bass=0.3, kick=0.42, hats=0.07, clap=0.0)


def _voice(kind, f, tt):
    if kind == 'sine': return np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt)
    if kind == 'square': return np.sign(np.sin(2 * np.pi * f * tt)) * 0.6
    if kind == 'lush':
        return sum(saw(f, tt, d) for d in (-0.009, -0.003, 0.003, 0.009)) / 2 + 0.4 * np.sin(np.pi * f * tt)
    return saw(f, tt, -0.004) + saw(f, tt, 0.004)


def _arp_note(kind, f, n):
    tt = np.arange(n) / SR
    if kind == 'square': x = np.sign(np.sin(2 * np.pi * f * tt)) * 0.5; dec = 14
    elif kind == 'bell': x = np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2.76 * tt); dec = 5
    else: x = np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(4 * np.pi * f * tt) + 0.1 * saw(f, tt); dec = 9   # pluck
    return x * np.exp(-tt * dec) * np.minimum(1, tt / 0.003)


def music(D, groove_start, cta_start, style=None):
    """Template-driven bed. groove_start: drums/bass come in; cta_start: breakdown, then the CTA hit restarts it."""
    st = {**DEFAULT_STYLE, **(style or {})}
    beat = 60.0 / st['bpm']
    N = int(SR * D)
    t = np.arange(N) / SR
    prog_ = PROGS.get(st['prog'], PROGS['minor'])
    pad_start = min(groove_start, 4.5) if groove_start < D else 0.5
    L = 8 * beat
    pad = np.zeros(N); bass = np.zeros(N); arp = np.zeros(N)
    k = 0; ts = pad_start
    while ts < D:
        notes = prog_[k % 4]
        i0 = int(ts * SR); i1 = min(N, int((ts + L + 0.3) * SR))
        tt = np.arange(i1 - i0) / SR
        e = np.minimum(1, tt / 0.35) * np.minimum(1, np.maximum(0, (L + 0.3 - tt)) / 0.3)
        if st['pad']:
            seg = sum(_voice(st['pad'], midi(m + 12), tt) for m in notes[1:])
            pad[i0:i1] += seg * e * st['pad_gain']
        for b in range(16):
            bt = ts + b * beat / 2
            if bt < groove_start or (cta_start - 0.01 <= bt < cta_start + 0.5): continue
            j0 = int(bt * SR); j1 = min(N, j0 + int(SR * 0.22))
            if j0 >= N: break
            tb = np.arange(j1 - j0) / SR
            f = midi(notes[0] - 12 + (12 if b % 4 == 3 else 0))
            bass[j0:j1] += (np.sin(2 * np.pi * f * tb) + 0.3 * saw(f, tb)) * np.exp(-tb * 9) * st['bass']
        if st['arp'] and st['arp_gain'] > 0:
            tones = [midi(m + 24) for m in notes[1:]] + [midi(notes[1] + 36)]
            for b in range(32):                                       # 16th notes
                bt = ts + b * beat / 4
                if bt < groove_start or bt >= D - 1.0 or (cta_start - 1.5 <= bt < cta_start + 0.5): continue
                j0 = int(bt * SR); n = min(N - j0, int(SR * beat * 0.9))
                if n <= 0: break
                arp[j0:j0 + n] += _arp_note(st['arp'], tones[(b * 3 + b // 4) % len(tones)], n) * st['arp_gain'] * (1.0 if b % 4 == 0 else 0.7)
        ts += L; k += 1
    pad = lp(pad, st['pad_lp']); bass = lp(bass, 400); arp = lp(arp, 6000)
    kick = np.zeros(N); duck = np.ones(N); hat = np.zeros(N); clap = np.zeros(N)
    kn = int(SR * 0.35); kt = np.arange(kn) / SR
    kshape = np.sin(2 * np.pi * (45 * kt + (140 - 45) * (1 - np.exp(-kt * 30)) / 30)) * np.exp(-kt * 9)
    dshape = 1 - 0.55 * np.exp(-kt * 10)
    cn = int(SR * 0.18); cshape = rng.standard_normal(cn) * (np.exp(-np.arange(cn) / SR * 28) + 0.5 * np.exp(-np.maximum(0, np.arange(cn) / SR - 0.012) * 40))
    cshape = bp(cshape, 900, 4500)
    hat_start = groove_start + 4 * beat * 4
    for b in range(int(D / beat)):
        bt = b * beat
        breakdown = cta_start - 1.5 <= bt < cta_start + 0.5
        live = bt >= groove_start and not breakdown and bt < D - 1.0
        if live and st['kick'] > 0:
            i = int(bt * SR); j = min(N, i + kn)
            kick[i:j] += kshape[:j - i]; duck[i:j] = np.minimum(duck[i:j], dshape[:j - i])
        if live and st['clap'] > 0 and b % 2 == 1:
            i = int(bt * SR); j = min(N, i + cn); clap[i:j] += cshape[:j - i]
        if st['hats'] > 0 and bt >= hat_start and not breakdown and bt < D - 1.5:
            i = int((bt + beat / 2) * SR); j = min(N, i + int(SR * 0.05))
            if i < N: hat[i:j] += rng.standard_normal(j - i) * np.exp(-np.arange(j - i) / SR * 90)
    hat = hp(hat, 7000)
    g = np.interp(t, [0, max(0.01, pad_start - 0.1), pad_start + 1.5, cta_start - 1.6, cta_start - 1.3, cta_start - 0.05, cta_start + 0.05, D - 1.2, D],
                  [0, 0, 0.85, 1.0, 0.6, 0.65, 1.0, 0.9, 0.0])
    mono = (pad + bass * 0.9 + arp) * g * duck + kick * st['kick'] * g + hat * st['hats'] * g + clap * st['clap'] * g
    out = np.zeros((N, 2))
    wide = (pad + arp * 0.6) * g * 0.15 * np.sin(t * 0.7)
    out[:, 0] = mono + wide
    out[:, 1] = mono - wide
    return out


def reverb(x, wet=0.16, d=1.1):
    n = int(SR * d); tt = np.arange(n) / SR
    out = np.zeros_like(x)
    for ch in range(2):
        ir = np.random.default_rng(ch + 5).standard_normal(n) * np.exp(-tt * 5.5)
        ir = lp(ir, 5000); ir /= np.sqrt((ir ** 2).sum())
        out[:, ch] = signal.fftconvolve(x[:, ch], ir)[:len(x)]
    return x * (1 - wet) + out * wet * 1.6


def duck_envelope(voice, depth):
    """1.0 where there is no speech, down to (1 - depth) under speech. Fast attack, slow release, so the bed dips
    as a word starts and comes back up between sentences rather than pumping on every syllable."""
    lvl = np.abs(voice)
    lvl = lp(lvl, 12, 1)
    on = np.clip(lvl / (np.percentile(lvl[lvl > 1e-4], 60) if np.any(lvl > 1e-4) else 1.0), 0, 1)
    env = np.empty_like(on); a, r, cur = 1 - np.exp(-1 / (SR * 0.03)), 1 - np.exp(-1 / (SR * 0.35)), 0.0
    for i in range(0, len(on), 64):                      # block-wise ballistics: fast enough, smooth enough
        tgt = on[i:i + 64].max()
        cur += (tgt - cur) * (a if tgt > cur else r) * 64
        cur = min(max(cur, 0.0), 1.0); env[i:i + 64] = cur
    return 1 - depth * lp(env, 20, 1)


def render_audio(events, D, groove_start, cta_start, path, music_gain=0.5, voice=None, style=None, sfx_gain=None):
    """`voice`: optional mono float array at SR (already placed in time and levelled). Music and SFX are ducked
    under it and it is mixed on top."""
    N = int(SR * D)
    bus = np.zeros((N + SR * 3, 2))
    for (t, kind, g, kw) in sorted(events, key=lambda e: e[0]):
        if kind not in SFX: continue
        g = g * (sfx_gain or {}).get(kind, 1.0) * (sfx_gain or {}).get('all', 1.0)
        x = SFX[kind](**kw)
        i = int(round(t * SR))
        if i >= len(bus): continue
        j = min(len(bus), i + len(x)); bus[i:j] += x[:j - i] * g
    bus = reverb(bus[:N])
    bed = music(D, groove_start, cta_start, style) * music_gain
    if voice is not None:
        v = np.zeros(N); v[:min(N, len(voice))] = voice[:N]
        bed *= duck_envelope(v, 0.72)[:, None]
        bus *= duck_envelope(v, 0.45)[:, None]
        # level the beds against the voice before mixing: voice peaks ~0.5, beds sit under it
        ref = np.percentile(np.abs(v[np.abs(v) > 1e-4]), 95) if np.any(np.abs(v) > 1e-4) else 1.0
        scale = 0.5 / (ref + 1e-9)
        mix = (bus + bed) / (np.abs(bus + bed).max() + 1e-9) * 0.55 + np.stack([v, v], 1) * scale
    else:
        mix = bus + bed
    mix = hp(mix.T, 25).T
    mix /= np.abs(mix).max() + 1e-9
    # ceiling ~-3 dBFS: AAC overshoots by 2-3 dB on dense, saturated material, which clipped at 0.9
    mix = np.tanh(mix * 1.6) / np.tanh(1.6) * 0.65
    fn = int(SR * 0.6); fade = np.ones(N); fade[-fn:] = np.linspace(1, 0, fn) ** 2
    mix *= fade[:, None]
    wavfile.write(path, SR, (mix * 32767).astype(np.int16))
