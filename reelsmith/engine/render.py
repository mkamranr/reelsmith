"""Frame-by-frame rendering into ffmpeg, split across CPU cores, then muxed with the synthesized audio."""
import multiprocessing as mp
import os
import shutil
import subprocess
import tempfile
import time

import skia

from .lib import W, H, FPS, TH
from .. import __version__
from .timeline import Timeline
from .audio import render_audio

QUALITY = {'draft': (0.5, 'veryfast', 23), 'final': (1.0, 'medium', 16)}


def check_ffmpeg():
    if not shutil.which('ffmpeg'):
        raise RuntimeError('ffmpeg not found on PATH. Install it (brew install ffmpeg / apt install ffmpeg).')


def _worker(sb, f0, f1, path, scale, preset, crf, counter):
    tl = Timeline(sb)
    w, h = int(round(W * scale / 2)) * 2, int(round(H * scale / 2)) * 2   # x264 needs even sizes
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{w}x{h}',
                           '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
                           '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-g', str(FPS * 2), path], stdin=subprocess.PIPE)
    surf = skia.Surface(w, h)
    for f in range(f0, f1):
        c = surf.getCanvas(); c.clear(skia.ColorBLACK)
        c.save(); c.scale(scale, scale)
        tl.render_frame(c, f)
        c.restore()
        ff.stdin.write(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType).tobytes())
        with counter.get_lock(): counter.value += 1
    ff.stdin.close(); ff.wait()
    if ff.returncode != 0: raise RuntimeError('ffmpeg failed on segment ' + path)


def render_video(sb, out_path, quality='final', workers=None, progress=None, scale=None, voice=None):
    """Render storyboard `sb` to `out_path` (mp4). `progress(stage, fraction)` is called periodically.
    Returns the timeline plan (scene start/durations actually used).
    `scale` overrides the quality's render scale, e.g. 2.0 to render natively at 2160x3840."""
    check_ffmpeg()
    q_scale, preset, crf = QUALITY[quality]
    if scale and scale > 1.0:
        crf = max(crf, 18)        # at 2K/4K, crf 16 only buys file size
    scale = scale or q_scale
    tl = Timeline(sb)   # validates + gives us the sfx events and plan
    nf = int(round(tl.duration * FPS))
    workers = max(1, min(workers or os.cpu_count() or 1, 16, nf // 60 or 1))
    tmp = tempfile.mkdtemp(prefix='reelsmith-')
    try:
        if progress: progress('audio', 0.0)
        wav = os.path.join(tmp, 'audio.wav')
        groove = tl.scenes[1].t0 + tl.scenes[1].dur if len(tl.scenes) > 2 else 0.0
        render_audio(tl.events, tl.duration, groove, tl.scenes[-1].t0, wav, voice=voice, style=TH.music, sfx_gain=TH.sfx, loop=tl.loop,
                     music_gain=0.0 if (voice is not None and TH.music.get('voice_only')) else 0.5)

        # forkserver/spawn, not fork: the web app renders from a background thread, and forking a multi-threaded
        # process can deadlock the child (Python 3.12 warns about exactly this).
        ctx = mp.get_context('forkserver' if 'forkserver' in mp.get_all_start_methods() else 'spawn')
        counter = ctx.Value('i', 0)
        bounds = [round(i * nf / workers) for i in range(workers + 1)]
        segs, procs = [], []
        for i in range(workers):
            p = os.path.join(tmp, f'seg{i:02d}.mp4'); segs.append(p)
            pr = ctx.Process(target=_worker, args=(sb, bounds[i], bounds[i + 1], p, scale, preset, crf, counter))
            pr.start(); procs.append(pr)
        try:
            while any(p.is_alive() for p in procs):
                if progress: progress('frames', counter.value / nf)   # may raise to cancel the job
                time.sleep(0.5)
        except BaseException:
            for p in procs:
                if p.is_alive(): p.terminate()
            for p in procs: p.join(5)
            raise
        if any(p.exitcode != 0 for p in procs): raise RuntimeError('a render worker failed')
        if progress: progress('frames', 1.0)

        if progress: progress('encode', 0.0)
        lst = os.path.join(tmp, 'list.txt')
        with open(lst, 'w') as fh:
            for p in segs: fh.write(f"file '{p}'\n")
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', wav,
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart',
                        '-metadata', f'comment=Reelsmith {__version__} · {TH.id}', out_path], check=True)
        if progress: progress('encode', 1.0)
        return tl.plan_summary()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_still(sb, t, path, scale=1.0):
    """Single frame at time t (seconds) — used for quick previews."""
    tl = Timeline(sb)
    surf = skia.Surface(int(W * scale), int(H * scale))
    c = surf.getCanvas(); c.save(); c.scale(scale, scale)
    tl.render_frame(c, int(t * FPS)); c.restore()
    surf.makeImageSnapshot().save(path, skia.kPNG)
