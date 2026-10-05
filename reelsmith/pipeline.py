"""inputs -> source -> storyboard -> video + cover + captions, all written into one job folder."""
import json

import numpy as np
import os
import re
import time

from . import captions as cap
from . import storyboard as sbmod
from .sources import fetch_source, SourceError
from .engine.render import render_video
from .engine.upscale import TARGETS, scale_for, upscale as ff_upscale
from .engine.timeline import Timeline
from . import narration as narr, tts as ttsmod


class Cancelled(Exception):
    """Raised inside a job when the user cancels it."""
from .engine.cover import render_cover


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', (s or 'video').lower()).strip('-')[:40] or 'video'


def generate(inputs, out_root='output', quality='final', workers=None, storyboard=None, use_llm=True, log=print, progress=None,
             upscale=None, upscale_method='ffmpeg', voiceover=False, voice=None, cancel=None):
    """
    inputs: {topic, description, url, duration, accent, handle}
    storyboard: optional pre-made storyboard dict (skips planning, e.g. after editing).
    Returns a manifest dict with paths of everything produced.
    """
    t0 = time.time()
    from .engine import templates as _tpl
    if inputs.get('template') and inputs['template'].strip().lower() not in _tpl.TEMPLATES:
        raise ValueError(f"Unknown template \"{inputs['template']}\". Choose one of: {', '.join(_tpl.TEMPLATES)}.")
    upscale = (upscale or '').lower() or None
    if upscale in ('none', '1080', '1080p'): upscale = None
    if upscale and upscale not in TARGETS:
        raise ValueError(f'upscale must be one of: {", ".join(TARGETS)}')
    if upscale_method not in ('ffmpeg', 'native'):
        raise ValueError('upscale_method must be "ffmpeg" or "native"')
    if upscale and quality == 'draft':
        log('  note: drafts are 540p previews, so the 2K/4K option is skipped. Use final quality for an upscale.')
        upscale = None
    native = upscale and upscale_method == 'native'
    def check():
        if cancel and cancel(): raise Cancelled('Cancelled.')
    def stage(name, frac=0.0):
        check()
        if progress: progress(name, frac)
    s_tts = None
    if voiceover:
        s_tts = ttsmod.settings()
        if not s_tts:
            raise ValueError('Voice-over needs text-to-speech. Set it up in Settings → Voice first.')

    source = None
    if inputs.get('url') and storyboard is None:
        stage('reading', 0)
        log(f"Reading {inputs['url']} …")
        source = fetch_source(inputs['url'])
        if source.get('note'): log('  note: ' + source['note'])
        log(f"  {source['kind']}: {source['title']} ({len(source['text'])} chars, facts: {', '.join(source['facts']) or 'none'})")

    if storyboard is None:
        stage('planning', 0)
        log('Planning storyboard …')
        sb, how = sbmod.plan(inputs, source, use_llm=use_llm, log=log)
        log(f"  planned by {how}: {' → '.join(s['type'] for s in sb['scenes'])}")
    else:
        sb = sbmod.sanitize(storyboard, inputs, {'url': storyboard.get('url', '')} if storyboard.get('url') else None)
        if inputs.get('restructure'):
            sb = sbmod.restructure(sb, inputs)
            log(f"Restructured for the {sb['template']} template: {' → '.join(x['type'] for x in sb['scenes'])}")
        how = 'provided'

    job = os.path.join(out_root, f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(sb['name'])}")
    os.makedirs(job, exist_ok=True)
    if source:
        with open(os.path.join(job, 'source.json'), 'w') as f: json.dump(source, f, indent=2, ensure_ascii=False)

    # page scroll-through: a screenshot of the link (or the README drawn as a page), placed where the template wants it
    from . import blueprints as bpm
    from .engine import templates as tplmod
    old_assets = sb.get('asset_dir')
    if storyboard is not None and old_assets and any(x['type'] == 'scroll' for x in sb['scenes']):
        import shutil
        for x in sb['scenes']:
            if x['type'] == 'scroll' and not os.path.isabs(x['image']) and os.path.exists(os.path.join(old_assets, x['image'])):
                shutil.copy2(os.path.join(old_assets, x['image']), os.path.join(job, x['image']))
    sb['asset_dir'] = job
    page_url = inputs.get('url') or (sb.get('url') if storyboard is not None else None)
    if page_url and inputs.get('screens', True) and not any(x['type'] == 'scroll' for x in sb['scenes']):
        stage('capture', 0)
        log('Capturing the page …')
        info = None
        try:
            from .capture import page_image
            info = page_image(page_url, source, os.path.join(job, 'page.png'),
                              dark=not tplmod.get(sb['template'])['light'], log=log)
        except Exception as e:
            log(f'  note: no page scroll-through ({e}).')
        if info:
            host = (source or {}).get('kind')
            cap_text = {'github': 'See it on GitHub', 'huggingface': 'On Hugging Face'}.get(host, 'Take a look')
            sb['scenes'] = bpm.add_scroll(sb['scenes'], sb['template'], 'page.png', info['kind'], sb.get('url', ''), cap_text, info)
            ix = next(i for i, x in enumerate(sb['scenes']) if x['type'] == 'scroll')
            log(f"  {'screenshot' if info['kind'] == 'screenshot' else 'README page'} {info['width']}×{info['height']}, "
                f"shown after the {sb['scenes'][ix - 1]['type'] if ix else 'start'}")
    sb['burn_captions'] = bool(inputs.get('burn_captions', True))
    sb.pop('spoken', None)

    res = TARGETS[upscale]['label'] if native else ('540 × 960' if quality == 'draft' else '1080 × 1920')
    voice_track = None
    if voiceover:
        stage('narration', 0)
        plan0 = Timeline(sb).plan_summary()
        voice_track, segs = narr.build(sb, plan0, sb['duration'], s_tts, voice=voice, source=source, use_llm=use_llm,
                                       log=log, check=check)
        if sb['burn_captions']:
            sb['spoken'] = [{'start': x['start'], 'end': x['end'], 'text': x['text']} for x in segs]
        with open(os.path.join(job, 'narration.json'), 'w') as f:
            json.dump({'voice': voice or s_tts.get('voice'), 'model': s_tts.get('model'), 'segments': segs}, f, indent=2, ensure_ascii=False)
        with open(os.path.join(job, 'narration.srt'), 'w') as f: f.write(narr.srt(segs))
        from scipy.io import wavfile
        wavfile.write(os.path.join(job, 'voiceover.wav'), narr.SR, (np.clip(voice_track, -1, 1) * 32767).astype(np.int16))
        log(f'  narration: {len(segs)} lines, {sum(x["end"] - x["start"] for x in segs):.1f}s of speech')
    log(f"Rendering {sb['duration']:.0f}s video at {res} …" + (' (native: slower, sharpest)' if native else ''))
    def vp(st, frac):
        check()
        if progress: progress('rendering' if st == 'frames' else st, frac)
    plan = render_video(sb, os.path.join(job, 'video.mp4'), quality=quality, workers=workers, progress=vp,
                        scale=scale_for(upscale) if native else None, voice=voice_track)
    files = {'video': 'video.mp4', 'cover': 'cover.png', 'captions': 'captions.md', 'storyboard': 'storyboard.json'}
    if upscale and not native:
        hd = f'video-{upscale}.mp4'
        log(f"Upscaling to {TARGETS[upscale]['label']} with ffmpeg …")
        stage('upscale', 0)
        ff_upscale(os.path.join(job, 'video.mp4'), os.path.join(job, hd), upscale, sb['duration'],
                   progress=(lambda fr: (check(), progress and progress('upscale', fr))))
        files['video_hd'] = hd
    if voiceover:
        files.update({'narration': 'narration.srt', 'voiceover': 'voiceover.wav'})
    sb['plan'] = plan
    with open(os.path.join(job, 'storyboard.json'), 'w') as f: json.dump(sb, f, indent=2, ensure_ascii=False)

    stage('cover', 0)
    log('Rendering cover …')
    render_cover(sb, os.path.join(job, 'cover.png'), scale=scale_for(upscale) if upscale else 1.0)

    stage('captions', 0)
    log('Writing captions …')
    c = cap.generate(sb, source, inputs.get('handle', ''), use_llm=use_llm)
    with open(os.path.join(job, 'captions.json'), 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
    with open(os.path.join(job, 'captions.md'), 'w') as f: f.write(cap.to_markdown(c))

    first = sb['scenes'][0] if sb['scenes'] else {}
    cta = next((x for x in sb['scenes'] if x['type'] == 'cta'), {})
    tags = len(re.findall(r'(?:^|\s)#\w+', c.get('instagram', '')))
    checks = [
        {'label': 'Hook on screen from the first frame', 'ok': first.get('type') == 'coldopen', 'detail': first.get('text', '')},
        {'label': 'Short enough to be finished', 'ok': sb['duration'] <= 15 if sb['duration'] <= 30 else False,
         'detail': f"{sb['duration']:.0f}s" + ('' if sb['duration'] <= 15 else ': 7-15 s gets the highest completion while an account is new')},
        {'label': 'Readable with the sound off', 'ok': (not voiceover) or bool(sb.get('spoken')),
         'detail': 'spoken words on screen' if sb.get('spoken') else ('on-screen text only' if not voiceover else 'turn on "Show the spoken words"')},
        {'label': 'Asks for a save, comment or share', 'ok': bool(cta.get('engage')), 'detail': cta.get('engage', '')},
        {'label': 'Niche stated', 'ok': bool(sb.get('audience')), 'detail': sb.get('audience') or 'set "Who is it for" so hook, captions and hashtags target one audience'},
        {'label': '3-5 specific hashtags', 'ok': 3 <= tags <= 5, 'detail': f'{tags} in the Instagram caption'},
        {'label': 'Loops back to the start', 'ok': bool(sb.get('loop')), 'detail': ''},
    ]
    manifest = {'job': os.path.basename(job), 'dir': job, 'name': sb['name'], 'duration': sb['duration'], 'quality': quality,
                'resolution': (TARGETS[upscale]['size'] if upscale else ((540, 960) if quality == 'draft' else (1080, 1920))),
                'upscale': upscale, 'upscale_method': upscale_method if upscale else None,
                'template': sb.get('template'),
                'voiceover': bool(voiceover), 'voice': (voice or (s_tts or {}).get('voice')) if voiceover else None,
                'planned_by': how, 'captions_by': c.get('source'), 'seconds': round(time.time() - t0, 1),
                'files': files, 'checks': checks, 'hook': sb.get('hook_line'), 'hook_alternatives': sb.get('hook_alternatives') or []}
    with open(os.path.join(job, 'manifest.json'), 'w') as f: json.dump(manifest, f, indent=2)
    stage('done', 1)
    log(f"Done in {manifest['seconds']}s → {job}")
    return manifest, sb, c
