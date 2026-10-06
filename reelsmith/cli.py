import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog='reelsmith', description='Topic / description / URL → 9:16 promo video, captions and cover.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    g = sub.add_parser('generate', help='plan + render a new video')
    g.add_argument('--topic', default='', help='topic or angle, e.g. "why this beats doing it by hand"')
    g.add_argument('--description', default='', help='free-text description of the product/idea')
    g.add_argument('--url', default='', help='GitHub repo, Hugging Face model/dataset, or any web page')
    g.add_argument('--duration', type=float, default=15, help='seconds (6-120, default 15; 7-15 s gets finished most often)')
    g.add_argument('--template', default='', help='visual template: midnight, editorial, terminal, pop, minimal, aurora (see `reelsmith templates`)')
    g.add_argument('--accent', default='', help='hex accent colour, e.g. "#F0B429" (default: chosen by the planner)')
    g.add_argument('--handle', default='', help='your @handle, used in captions and cover')
    g.add_argument('--draft', action='store_true', help='540x960 fast preview instead of 1080x1920')
    g.add_argument('--upscale', choices=['2k', '4k'], help='also produce a 1440x2560 (2k) or 2160x3840 (4k) file')
    g.add_argument('--voiceover', action='store_true', help='narrate the video (needs a voice set up: Settings → Voice)')
    g.add_argument('--avatar', default='', help='image URL for your avatar (Spotlight end card and handle pill)')
    g.add_argument('--audience', default='', help='who it is for, e.g. "indie developers" (sharpens hook, script and hashtags)')
    g.add_argument('--engage', default='auto', choices=['auto', 'save', 'comment', 'share', 'follow', 'none'], help='what the closing card asks viewers to do')
    g.add_argument('--keyword', default='', help='keyword for --engage comment ("Comment LINK for the link"); only if you will reply')
    g.add_argument('--cover', default='auto', choices=['auto', 'stack', 'headline', 'device', 'split', 'magazine', 'poster', 'breaking', 'terminal', 'sticker', 'minimal'],
                   help="cover layout (auto = the template's own); two alternatives are always saved too")
    g.add_argument('--no-hook', action='store_true', help='skip the cold-open hook (not recommended)')
    g.add_argument('--no-loop', action='store_true', help='fade out instead of looping back to the first frame')
    g.add_argument('--no-screens', action='store_true', help='skip the page scroll-through screenshot')
    g.add_argument('--no-captions', action='store_true', help="don't put the spoken words on screen (voice-over only)")
    g.add_argument('--voice', default=None, help='voice name for this video (default: the one in your voice settings)')
    g.add_argument('--upscale-method', choices=['ffmpeg', 'native'], default='ffmpeg',
                   help='ffmpeg: upscale the 1080p render (fast). native: render at that size (sharpest, ~2-4x slower)')
    g.add_argument('--no-llm', action='store_true', help='plan and caption without an LLM (heuristic)')
    g.add_argument('--workers', type=int, default=None, help='render processes (default: all cores)')
    g.add_argument('-o', '--out', default='output', help='output folder (default ./output)')

    r = sub.add_parser('render', help='render an existing storyboard.json (e.g. after editing it)')
    r.add_argument('storyboard')
    r.add_argument('--duration', type=float, default=None)
    r.add_argument('--template', default='', help='render in a different template than the storyboard says')
    r.add_argument('--restructure', action='store_true', help="also rebuild the story in the template's structure (e.g. a countdown for pop)")
    r.add_argument('--draft', action='store_true')
    r.add_argument('--upscale', choices=['2k', '4k'])
    r.add_argument('--voiceover', action='store_true')
    r.add_argument('--voice', default=None)
    r.add_argument('--upscale-method', choices=['ffmpeg', 'native'], default='ffmpeg')
    r.add_argument('--no-llm', action='store_true', help='template captions instead of LLM captions')
    r.add_argument('--workers', type=int, default=None)
    r.add_argument('-o', '--out', default='output')

    p = sub.add_parser('plan', help='only write the storyboard JSON (no rendering) — edit it, then `render` it')
    for a in ('--topic', '--description', '--url', '--accent', '--handle', '--template'): p.add_argument(a, default='')
    p.add_argument('--duration', type=float, default=45)
    p.add_argument('--no-llm', action='store_true')
    p.add_argument('-o', '--out', default='storyboard.json')

    s = sub.add_parser('serve', help='start the local web app')
    s.add_argument('--port', type=int, default=5179)
    s.add_argument('--host', default='127.0.0.1')
    s.add_argument('--out', default='output')

    sub.add_parser('templates', help='list the visual templates')
    vf = sub.add_parser('voice', help='show, set or test the text-to-speech settings used for voice-overs')
    vfs = vf.add_subparsers(dest='vcmd', required=True)
    vfs.add_parser('show', help='print current voice settings (key masked)')
    vs = vfs.add_parser('set', help='save settings, e.g. `voice set --provider kokoro --base-url http://localhost:8880/v1 --voice af_heart`')
    vs.add_argument('--provider', choices=['none', 'kokoro', 'openai', 'custom'])
    vs.add_argument('--base-url'); vs.add_argument('--api-key'); vs.add_argument('--model'); vs.add_argument('--voice')
    vs.add_argument('--speed', type=float); vs.add_argument('--format', dest='response_format', choices=['wav', 'mp3', 'flac', 'opus', 'aac', 'pcm'])
    vs.add_argument('--timeout', type=int)
    vt = vfs.add_parser('test', help='speak a short sample and report how long it took')
    vt.add_argument('--voice', default=None); vt.add_argument('--save-to', default=None, help='write the sample audio to this file')
    vfs.add_parser('voices', help='list voices the server offers (or the standard Kokoro set if it lists none)')

    cf = sub.add_parser('config', help='show, set or test the language-model settings')
    cfs = cf.add_subparsers(dest='action', required=True)
    cfs.add_parser('show', help='print current settings (key masked)')
    st = cfs.add_parser('set', help='save settings, e.g. `config set --provider ollama --model llama3.1:8b`')
    st.add_argument('--provider', required=True, choices=['none', 'ollama', 'vllm', 'lmstudio', 'openai', 'openrouter', 'anthropic', 'custom'])
    st.add_argument('--base-url'); st.add_argument('--model'); st.add_argument('--api-key')
    st.add_argument('--temperature', type=float); st.add_argument('--max-tokens', type=int); st.add_argument('--timeout', type=int)
    st.add_argument('--num-ctx', type=int, help='Ollama context window'); st.add_argument('--max-source-chars', type=int)
    st.add_argument('--no-json-mode', action='store_true', help="don't ask the server for JSON output")
    st.add_argument('--header', action='append', default=[], help='extra HTTP header "Name: value" (repeatable)')
    cfs.add_parser('test', help='check the saved endpoint answers with JSON')
    cfs.add_parser('models', help='list models the saved endpoint offers')

    a = ap.parse_args(argv)

    if a.cmd == 'config':
        return _config(a)
    if a.cmd == 'voice':
        return _voice(a)
    if a.cmd == 'templates':
        from .engine import templates as tpl
        for t in tpl.listing():
            print(f"{t['id']:10} {t['name']:10} {t['description']}")
        return 0

    if a.cmd == 'serve':
        from .server import serve
        return serve(a.host, a.port, a.out)

    from . import pipeline, storyboard as sbm
    from .sources import fetch_source, SourceError
    from .llm import LLMError

    try:
        if a.cmd == 'plan':
            inputs = {k: getattr(a, k) for k in ('topic', 'description', 'url', 'accent', 'handle', 'duration', 'template')}
            inputs['screens'] = not getattr(a, 'no_screens', False); inputs['burn_captions'] = not getattr(a, 'no_captions', False)
            inputs.update(avatar=getattr(a, 'avatar', ''), cover_style=getattr(a, 'cover', 'auto'), audience=getattr(a, 'audience', ''), engage=getattr(a, 'engage', 'auto'), keyword=getattr(a, 'keyword', ''),
                          retention_hook=not getattr(a, 'no_hook', False), loop=not getattr(a, 'no_loop', False))
            src = fetch_source(a.url) if a.url else None
            sb, how = sbm.plan(inputs, src, use_llm=not a.no_llm)
            with open(a.out, 'w') as fh: json.dump(sb, fh, indent=2, ensure_ascii=False)
            print(f"storyboard ({how}) → {a.out}: {' → '.join(x['type'] for x in sb['scenes'])}")
            return 0
        if a.cmd == 'generate':
            if not (a.topic or a.description or a.url):
                ap.error('give at least one of --topic, --description, --url')
            inputs = {k: getattr(a, k) for k in ('topic', 'description', 'url', 'accent', 'handle', 'duration', 'template')}
            inputs['screens'] = not getattr(a, 'no_screens', False); inputs['burn_captions'] = not getattr(a, 'no_captions', False)
            inputs.update(cover_style=getattr(a, 'cover', 'auto'), audience=getattr(a, 'audience', ''), engage=getattr(a, 'engage', 'auto'), keyword=getattr(a, 'keyword', ''),
                          retention_hook=not getattr(a, 'no_hook', False), loop=not getattr(a, 'no_loop', False))
            pipeline.generate(inputs, a.out, 'draft' if a.draft else 'final', a.workers, use_llm=not a.no_llm, progress=_bar(),
                              upscale=a.upscale, upscale_method=a.upscale_method,
                              voiceover=a.voiceover, voice=a.voice)
            return 0
        if a.cmd == 'render':
            with open(a.storyboard) as fh: sb = json.load(fh)
            inputs = {'duration': a.duration or sb.get('duration', 45), 'handle': sb.get('handle', ''), 'template': a.template, 'restructure': a.restructure}
            pipeline.generate(inputs, a.out, 'draft' if a.draft else 'final', a.workers, storyboard=sb, use_llm=not a.no_llm, progress=_bar(),
                              upscale=a.upscale, upscale_method=a.upscale_method,
                              voiceover=a.voiceover, voice=a.voice)
            return 0
    except (SourceError, LLMError, RuntimeError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2


def _voice(a):
    from . import tts as T
    try:
        if a.vcmd == 'show':
            print(json.dumps({**T.public(T.load()), 'path': T.path(), 'ready': bool(T.settings())}, indent=2)); return 0
        if a.vcmd == 'set':
            new = {k: v for k, v in vars(a).items() if k in ('provider', 'base_url', 'api_key', 'model', 'voice', 'speed',
                                                              'response_format', 'timeout') and v is not None}
            saved = T.save(T.normalize(new))
            print(json.dumps(T.public(saved), indent=2)); print(f'saved to {T.path()}'); return 0
        s = T.settings()
        if not s:
            print('error: no voice configured. Run `reelsmith voice set --provider kokoro --base-url ...` first.', file=sys.stderr); return 2
        if a.vcmd == 'voices':
            r = T.list_voices(s)
            note = {'server': f"from {r['url']}", 'kokoro-standard': "server lists none; standard Kokoro voices (check with `voice test --voice NAME`)",
                    'openai-standard': 'OpenAI voices', 'none': 'server lists none; use the name your server accepts'}[r['source']]
            print(f"{len(r['voices'])} voices ({note})"); print('\n'.join(r['voices'])); return 0
        if a.vcmd == 'test':
            r = T.test(s, a.voice)
            if not r['ok']: print(f"error: {r['error']}", file=sys.stderr); return 2
            if a.save_to:
                import base64
                with open(a.save_to, 'wb') as fh: fh.write(base64.b64decode(r['audio'].split(',', 1)[1]))
            print(f"ok: {r['duration']}s of speech in {r['seconds']}s with voice {a.voice or s['voice']}" + (f" → {a.save_to}" if a.save_to else '')); return 0
    except (ValueError, T.TTSError) as e:
        print(f'error: {e}', file=sys.stderr); return 2


def _config(a):
    from . import config as C, llm
    try:
        if a.action == 'set':
            new = {'provider': a.provider}
            for k in ('base_url', 'model', 'api_key', 'temperature', 'max_tokens', 'timeout', 'num_ctx', 'max_source_chars'):
                v = getattr(a, k)
                if v is not None: new[k] = v
            if a.no_json_mode: new['json_mode'] = False
            if a.header: new['headers'] = dict((h.split(':', 1)[0].strip(), h.split(':', 1)[1].strip()) for h in a.header if ':' in h)
            C.save(C.normalize(new) if a.provider != 'none' else dict(C.DEFAULTS))
            print(f'saved → {C.path()}')
        if a.action in ('show', 'set'):
            pub = C.public(C.load()); act = llm.provider()
            for k in ('provider', 'base_url', 'model', 'api_key', 'temperature', 'max_tokens', 'timeout', 'num_ctx', 'max_source_chars', 'json_mode', 'headers'):
                print(f'  {k:17} {pub.get(k)}')
            print(f"  active: {act['label'] + ' / ' + (act['model'] or '?') + ' (' + act['source'] + ')' if act else 'none (built-in planner)'}")
            return 0
        s = llm.settings()
        if not s: print('No language model configured.'); return 1
        if a.action == 'models':
            for m in llm.list_models(s): print(m)
            return 0
        r = llm.test(s)
        if r.get('models') is not None:
            print(f"models: {len(r['models'])} available" + ('' if r['model_found'] is not False else f"; '{s['model']}' is NOT among them"))
        elif r.get('models_error'): print('models: ' + r['models_error'])
        print(('ok' if r['ok'] else 'failed') + f" in {r['seconds']}s" + ('' if r['ok'] else f": {r['error']}"))
        return 0 if r['ok'] else 1
    except (ValueError, llm.LLMError) as e:
        print(f'error: {e}', file=sys.stderr); return 2


def _bar():
    last = {'s': None}
    def cb(stage, frac):
        if stage in ('rendering', 'upscale'):
            n = int(frac * 30)
            label = 'frames ' if stage == 'rendering' else 'upscale'
            sys.stdout.write(f"\r  {label} [{'#' * n}{'.' * (30 - n)}] {frac * 100:5.1f}%")
            sys.stdout.flush()
            if frac >= 1: sys.stdout.write('\n')
        last['s'] = stage
    return cb


if __name__ == '__main__':
    sys.exit(main())
