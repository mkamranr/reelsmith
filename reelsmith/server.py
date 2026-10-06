"""Local web app. Standard library only.

The server has no authentication and fetches URLs on request, so it binds to 127.0.0.1 by default.
Jobs run one at a time (rendering already uses every core).
"""
import json
import os
import queue
import threading
import time
import traceback
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

from . import pipeline, storyboard as sbm, llm, config as cfgmod, tts as ttsmod
from .jobs import JobStore
from . import __version__
from .sources import fetch_source, SourceError

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
MIME = {'.mp4': 'video/mp4', '.png': 'image/png', '.json': 'application/json', '.md': 'text/markdown; charset=utf-8',
        '.html': 'text/html; charset=utf-8', '.txt': 'text/plain; charset=utf-8'}


def make_runner(out_root):
    def run(job, hooks):
        p = job['payload']
        inputs = {k: p.get(k, '') for k in ('topic', 'description', 'url', 'accent', 'handle', 'template', 'audience', 'engage', 'keyword', 'cover_style')}
        inputs['retention_hook'] = p.get('retention_hook', True) is not False
        inputs['loop'] = p.get('loop', True) is not False
        inputs['restructure'] = bool(p.get('restructure'))
        inputs['screens'] = p.get('screens', True) is not False
        inputs['burn_captions'] = p.get('burn_captions', True) is not False
        inputs['duration'] = float(p.get('duration') or (p.get('storyboard') or {}).get('duration') or 45)
        return pipeline.generate(
            inputs, out_root, 'draft' if p.get('quality') == 'draft' else 'final', storyboard=p.get('storyboard'),
            use_llm=not p.get('no_llm'), upscale=p.get('upscale') or None, upscale_method=p.get('upscale_method') or 'ffmpeg',
            voiceover=bool(p.get('voiceover')), voice=p.get('voice') or None,
            log=hooks['log'], progress=hooks['progress'], cancel=hooks['cancelled'], on_dir=hooks['dir'])
    return run


def make_handler(jobs, port):
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
    extra = os.environ.get('REELSMITH_ALLOWED_HOSTS', '')
    allowed_hosts |= {h.strip() for h in extra.split(',') if h.strip()}
    # Optional login. The app has none by default (it listens on 127.0.0.1); set REELSMITH_PASSWORD whenever it is
    # reachable from other machines, e.g. after binding to 0.0.0.0.
    password = os.environ.get('REELSMITH_PASSWORD', '')
    user = os.environ.get('REELSMITH_USER', 'reelsmith')
    import base64, hmac
    expected = ('Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()) if password else None

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _trusted(self):
            """Blocks DNS-rebinding (Host) and cross-site requests (Origin). Other websites open in the same
            browser must not be able to change the LLM endpoint or start jobs."""
            if self.headers.get('Host', '') not in allowed_hosts:
                self._send(403, {'error': 'Host not allowed. Set REELSMITH_ALLOWED_HOSTS to serve under another name.'}); return False
            origin = self.headers.get('Origin')
            if origin and origin.split('://', 1)[-1] not in allowed_hosts:
                self._send(403, {'error': 'Cross-origin request refused.'}); return False
            if expected and urlparse(self.path).path != '/healthz':
                got = self.headers.get('Authorization', '')
                if not hmac.compare_digest(got.encode(), expected.encode()):
                    body = b'{"error": "Sign in required."}'
                    self.send_response(401); self.send_header('WWW-Authenticate', 'Basic realm="Reelsmith", charset="UTF-8"')
                    self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body); return False
            return True

        def _send(self, code, body, ctype='application/json'):
            data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == 'application/json' else body).encode()
            self.send_response(code); self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0)
            if n > 2_000_000: raise ValueError('request too large')
            return json.loads(self.rfile.read(n) or b'{}')

        def do_GET(self):
            if not self._trusted(): return
            path = urlparse(self.path).path
            if path == '/healthz':
                return self._send(200, {'ok': True})
            if path == '/api/config':
                return self._send(200, {'config': cfgmod.public(cfgmod.load()), 'presets': cfgmod.PRESETS, 'active': llm.provider()})
            if path in ('/', '/index.html'):
                return self._send(200, open(os.path.join(WEB, 'index.html'), 'rb').read(), MIME['.html'])
            if path == '/api/status':
                return self._send(200, {'llm': llm.provider(), 'cpus': os.cpu_count(), 'out': jobs.out, 'in_docker': cfgmod.in_docker(), 'version': __version__})
            if path == '/api/tts':
                return self._send(200, {'config': ttsmod.public(ttsmod.load()), 'presets': ttsmod.PRESETS,
                                        'ready': bool(ttsmod.settings())})
            if path == '/api/covers':
                from .engine.cover import STYLES, STYLE_NAMES
                return self._send(200, [{'id': k, 'name': STYLE_NAMES[k]} for k in STYLES])
            if path == '/api/templates':
                from .engine import templates as tpl
                return self._send(200, tpl.listing())
            if path.startswith('/api/templates/') and path.endswith('/preview.png'):
                from .previews import preview_path
                tid = path.split('/')[3]
                with open(preview_path(jobs.out, tid), 'rb') as fh: data = fh.read()
                self.send_response(200); self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'max-age=86400'); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data); return
            if path == '/api/jobs':
                return self._send(200, jobs.list())
            if path == '/api/storage':
                return self._send(200, {'bytes': jobs.disk_usage()})
            if path == '/api/history':
                return self._send(200, [j for j in jobs.list() if j['status'] == 'done'])
            if path.startswith('/api/jobs/'):
                j = jobs.get(path.rsplit('/', 1)[-1])
                return self._send(200 if j else 404, j or {'error': 'No such job.'})
            if path.startswith('/files/'):
                return self._file(unquote(path[len('/files/'):]))
            self._send(404, {'error': 'not found'})

        def _file(self, rel):
            full = os.path.realpath(os.path.join(jobs.out, rel))
            if not full.startswith(jobs.out + os.sep) or not os.path.isfile(full):
                return self._send(404, {'error': 'not found'})
            ext = os.path.splitext(full)[1]; size = os.path.getsize(full)
            rng = self.headers.get('Range')
            with open(full, 'rb') as fh:
                if rng and rng.startswith('bytes='):      # range requests so <video> can seek
                    a, _, b = rng[6:].partition('-')
                    a = int(a or 0); b = int(b) if b else size - 1; b = min(b, size - 1)
                    fh.seek(a); data = fh.read(b - a + 1)
                    self.send_response(206); self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
                else:
                    data = fh.read(); self.send_response(200)
            self.send_header('Content-Type', MIME.get(ext, 'application/octet-stream'))
            self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', str(len(data)))
            if self.path.endswith('?dl=1') or 'dl=1' in self.path:
                self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(full)}"')
            self.end_headers(); self.wfile.write(data)

        def do_POST(self):
            if not self._trusted(): return
            if 'application/json' not in (self.headers.get('Content-Type') or ''):
                return self._send(415, {'error': 'Send JSON.'})
            path = urlparse(self.path).path
            try:
                p = self._body()
                if path == '/api/config':
                    saved = cfgmod.save(cfgmod.normalize(p))
                    return self._send(200, {'config': cfgmod.public(saved), 'active': llm.provider()})
                if path == '/api/config/clear':
                    cfgmod.save(dict(cfgmod.DEFAULTS))
                    return self._send(200, {'config': cfgmod.public(cfgmod.load()), 'active': llm.provider()})
                if path in ('/api/config/test', '/api/config/models'):
                    trial = llm.resolve(cfgmod.normalize(p))     # unsaved form values; masked key = saved key
                    if path.endswith('test'): return self._send(200, llm.test(trial))
                    return self._send(200, {'models': llm.list_models(trial)})
                if path == '/api/tts':
                    saved = ttsmod.save(ttsmod.normalize(p))
                    return self._send(200, {'config': ttsmod.public(saved), 'ready': bool(ttsmod.settings())})
                if path in ('/api/tts/test', '/api/tts/voices'):
                    trial = ttsmod.normalize(p)                     # unsaved form values; masked key = saved key
                    if trial['provider'] not in ttsmod.PRESETS: return self._send(400, {'error': 'Choose a voice provider first.'})
                    if path.endswith('test'): return self._send(200, ttsmod.test(trial, p.get('voice') or None))
                    return self._send(200, ttsmod.list_voices(trial))
                if path in ('/api/generate', '/api/render'):
                    if path == '/api/generate' and not (p.get('topic') or p.get('description') or p.get('url')):
                        return self._send(400, {'error': 'Give a topic, a description or a URL.'})
                    if path == '/api/render' and not isinstance(p.get('storyboard'), dict):
                        return self._send(400, {'error': 'storyboard required'})
                    from .engine import templates as tpl
                    if p.get('template') and str(p['template']).lower() not in tpl.TEMPLATES:
                        return self._send(400, {'error': f"Unknown template \"{p['template']}\". Choose one of: {', '.join(tpl.TEMPLATES)}."})
                    if p.get('voiceover') and not ttsmod.settings():
                        return self._send(400, {'error': 'Voice-over needs text-to-speech. Set it up in Settings → Voice first.'})
                    jid = jobs.submit('generate' if path == '/api/generate' else 'render', p)
                    return self._send(200, {'id': jid, 'position': jobs.position(jid)})
                if path.startswith('/api/jobs/') and path.count('/') == 4:
                    _, _, _, jid, action = path.split('/')
                    try:
                        if action == 'cancel': return self._send(200, jobs.cancel(jid))
                        if action == 'retry': return self._send(200, {'id': jobs.retry(jid)})
                        if action == 'delete':
                            return self._send(200, jobs.delete(jid, files=p.get('files', True) is not False))
                    except KeyError:
                        return self._send(404, {'error': 'No such job.'})
                if path == '/api/plan':
                    inputs = {k: p.get(k, '') for k in ('topic', 'description', 'url', 'accent', 'handle', 'template', 'audience', 'engage', 'keyword')}
                    inputs['duration'] = float(p.get('duration') or 45)
                    src = fetch_source(p['url']) if p.get('url') else None
                    sb, how = sbm.plan(inputs, src, use_llm=not p.get('no_llm'))
                    return self._send(200, {'storyboard': sb, 'planned_by': how, 'source_note': (src or {}).get('note')})
                self._send(404, {'error': 'not found'})
            except (SourceError, llm.LLMError, ttsmod.TTSError, ValueError) as e:
                self._send(400, {'error': str(e)})
            except Exception as e:
                self._send(500, {'error': f'{type(e).__name__}: {e}'})
    return H


def serve(host='127.0.0.1', port=5179, out='output'):
    if host not in ('127.0.0.1', 'localhost', '::1') and not os.environ.get('REELSMITH_PASSWORD'):
        print('  WARNING: reachable from other machines with no login. Set REELSMITH_PASSWORD (and optionally REELSMITH_USER).')
    jobs = JobStore(out, make_runner(os.path.abspath(out)))
    srv = ThreadingHTTPServer((host, port), make_handler(jobs, port))
    p = llm.provider()
    print(f"Reelsmith {__version__} → http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
    print(f"  LLM: {p['label'] + ' / ' + (p['model'] or '?') + ' @ ' + p['base_url'] if p else 'none (built-in planner). Open Settings to add one.'}")
    print(f"  output: {jobs.out}   settings: {cfgmod.path()}")
    t = ttsmod.settings()
    print(f"  voice: {t['provider'] + ' / ' + t['model'] + ' (' + t['voice'] + ') @ ' + t['base_url'] if t else 'not set up (Settings → Voice)'}")
    q = [j for j in jobs.list() if j['status'] == 'queued']
    if q: print(f"  resuming {len(q)} queued job(s)")
    if host not in ('127.0.0.1', 'localhost'):
        if os.path.exists('/.dockerenv') or os.environ.get('REELSMITH_IN_DOCKER'):
            print('  running in a container: whoever can reach the published port can use this app (no login).')
        else:
            print('warning: listening beyond localhost. The server has no authentication.')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
