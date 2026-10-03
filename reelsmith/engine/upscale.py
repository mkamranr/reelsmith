"""Resolution targets and ffmpeg upscaling.

Two ways to get a 2K/4K file:
  ffmpeg  — upscale the finished 1080x1920 video (Lanczos + a light unsharp mask). Fast; the 1080p file is kept.
  native  — render every frame at the target size. The engine draws vectors, so this is real detail rather than
            interpolation, but it costs roughly (target/1080)^2 more render time. See render.render_video(scale=…).
"""
import subprocess

from .lib import W, H

# 9:16 sizes. "2K" here is QHD (1440p); "4K" is UHD (2160p).
TARGETS = {
    '2k': {'size': (1440, 2560), 'label': '2K (1440 × 2560)', 'sharpen': 0.25},
    '4k': {'size': (2160, 3840), 'label': '4K (2160 × 3840)', 'sharpen': 0.40},
}


def scale_for(target):
    return TARGETS[target]['size'][0] / W


def upscale(src, dst, target, duration=None, progress=None, crf=18, preset='medium'):
    """Upscale `src` to the target size into `dst`. Audio is copied untouched.
    `progress(fraction)` is called as ffmpeg reports its position."""
    if target not in TARGETS:
        raise ValueError(f'unknown upscale target "{target}"; choose one of {", ".join(TARGETS)}')
    w, h = TARGETS[target]['size']
    amt = TARGETS[target]['sharpen']
    # Lanczos with accurate rounding and full chroma interpolation keeps thin text edges clean; the unsharp mask
    # touches luma only (chroma amount 0) to restore some crispness lost to interpolation without colour halos.
    vf = f'scale={w}:{h}:flags=lanczos+accurate_rnd+full_chroma_int,unsharp=5:5:{amt}:5:5:0.0,setsar=1'
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-nostats', '-progress', 'pipe:1', '-i', src, '-vf', vf,
           '-c:v', 'libx264', '-preset', preset, '-crf', str(crf), '-pix_fmt', 'yuv420p', '-profile:v', 'high',
           '-c:a', 'copy', '-movflags', '+faststart', dst]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for ln in proc.stdout:
            if progress and duration and ln.startswith('out_time_us='):
                try:
                    progress(max(0.0, min(1.0, int(ln.split('=', 1)[1]) / 1e6 / duration)))   # may raise to cancel
                except ValueError:
                    pass
    except BaseException:
        proc.kill(); proc.wait()
        raise
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(f'ffmpeg upscale failed: {err.strip()[-400:]}')
    if progress: progress(1.0)
    return dst
