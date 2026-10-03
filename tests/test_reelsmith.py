"""Run with:  python -m unittest discover -s tests -v
No network needed except the GitHub test, which is skipped offline."""
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['REELSMITH_CONFIG'] = os.path.join(tempfile.mkdtemp(), 'config.json')

from reelsmith import config, llm, storyboard as sbm, sources            # noqa: E402
from reelsmith.engine.timeline import allocate, Timeline                 # noqa: E402
from reelsmith.engine.highlight import highlight                          # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'examples', 'carousel-crafter.json')


def _example():
    with open(EXAMPLE) as f: return json.load(f)


class Storyboard(unittest.TestCase):
    def test_sanitize_repairs_bad_llm_output(self):
        raw = {'name': 'X', 'accent': 'notacolour', 'scenes': [
            {'type': 'code', 'lines': 'a\nb', 'callouts': [{'line': 1, 'label': 'hi'}, {'line': 'zz'}]},
            {'type': 'stats', 'items': [{'value': 'lots', 'label': 'no digits'}]},
            {'type': 'sparkles'},
            {'type': 'statement', 'text': 'x' * 300}]}
        sb = sbm.sanitize(raw, {'duration': 30}, {'url': 'example.com'})
        kinds = [s['type'] for s in sb['scenes']]
        self.assertEqual(kinds[0], 'hook'); self.assertEqual(kinds[-1], 'cta')
        self.assertNotIn('stats', kinds); self.assertNotIn('sparkles', kinds)
        self.assertEqual(sb['accent'], '#F0B429')
        code = next(s for s in sb['scenes'] if s['type'] == 'code')
        self.assertEqual(code['lines'], ['a', 'b']); self.assertEqual(len(code['callouts']), 1)
        self.assertLessEqual(len(next(s for s in sb['scenes'] if s['type'] == 'statement')['text']), 70)
        self.assertEqual(sb['scenes'][-1]['url'], 'example.com')

    def test_allocation_fits_duration_on_beat_grid(self):
        sb = _example()
        for total in (15, 30, 45, 60, 90):
            plan = allocate(sb['scenes'], total)
            self.assertAlmostEqual(sum(d for _, _, d in plan), total, places=5)
            self.assertEqual(plan[0][0]['type'], 'hook'); self.assertEqual(plan[-1][0]['type'], 'cta')
            for _, t0, _ in plan: self.assertAlmostEqual((t0 * 2) % 1, 0, places=5)

    def test_heuristic_without_source(self):
        sb = sbm.plan_heuristic({'description': 'Tiny habits compound. Two minutes a day beats an hour once a month.', 'duration': 20}, None)
        self.assertEqual(sb['name'], 'Tiny habits compound')
        self.assertEqual(sb['scenes'][0]['type'], 'hook')

    def test_timeline_builds_and_registers_sound(self):
        tl = Timeline(_example())
        self.assertGreater(len(tl.events), 50)
        self.assertTrue(all(0 <= t <= tl.duration + 3 for t, *_ in tl.events))


class JSONExtraction(unittest.TestCase):
    def test_messy_replies(self):
        self.assertEqual(llm.extract_json('Sure!\n```json\n{"a": [1, 2,],}\n```\nbye')['a'], [1, 2])
        self.assertEqual(llm.extract_json('<think>{"wrong": 1}</think>{"ok": true}'), {'ok': True})
        self.assertEqual(llm.extract_json('{"s": "brace } inside"}')['s'], 'brace } inside')
        with self.assertRaises(llm.LLMError): llm.extract_json('no json here')


class Config(unittest.TestCase):
    def setUp(self):
        if os.path.exists(config.path()): os.remove(config.path())

    def test_presets_and_key_handling(self):
        c = config.save(config.normalize({'provider': 'vllm', 'model': 'm', 'api_key': 'sk-secret-123456'}))
        self.assertEqual(c['base_url'], 'http://localhost:8000/v1')
        self.assertEqual(oct(os.stat(config.path()).st_mode & 0o777), '0o600')
        pub = config.public(c)
        self.assertNotIn('secret', json.dumps(pub))
        self.assertEqual(config.normalize({'provider': 'vllm', 'api_key': pub['api_key']})['api_key'], 'sk-secret-123456')
        switched = config.normalize({'provider': 'ollama'})
        self.assertEqual((switched['api_key'], switched['base_url']), ('', 'http://localhost:11434'))

    def test_rejects_bad_values(self):
        for bad in ({'provider': 'nope'}, {'provider': 'custom', 'base_url': 'ftp://x'}, {'provider': 'ollama', 'timeout': 'abc'}):
            with self.assertRaises(ValueError): config.normalize(bad)

    def test_extra_headers_are_sent(self):
        s = llm.resolve(config.normalize({'provider': 'custom', 'model': 'm', 'api_key': 'k', 'headers': {'X-Team': 'video'}}))
        h = llm._auth(s)
        self.assertEqual(h['X-Team'], 'video'); self.assertEqual(h['Authorization'], 'Bearer k')


def _free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class MockLLM(BaseHTTPRequestHandler):
    """Speaks Ollama-native, and OpenAI-compatible that rejects response_format (like several local servers)."""
    seen = []
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == '/api/tags': return self._send(200, {'models': [{'name': 'llama3.1:8b'}]})
        if self.path == '/v1/models': return self._send(200, {'data': [{'id': 'local-model'}]})
        self._send(404, {})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        MockLLM.seen.append((self.path, body))
        if self.path == '/api/chat':
            return self._send(200, {'message': {'content': '<think>hmm</think>{"ok": true}'}})
        if self.path == '/v1/chat/completions':
            if 'response_format' in body: return self._send(400, {'error': 'response_format unsupported'})
            return self._send(200, {'choices': [{'message': {'content': '```json\n{"ok": true}\n```'}}]})
        self._send(404, {})


class Providers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.srv = ThreadingHTTPServer(('127.0.0.1', cls.port), MockLLM)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def test_ollama_native(self):
        s = llm.resolve(config.normalize({'provider': 'ollama', 'base_url': f'http://127.0.0.1:{self.port}', 'model': 'llama3.1:8b', 'num_ctx': 32768}))
        r = llm.test(s)
        self.assertTrue(r['ok'], r); self.assertTrue(r['model_found'])
        path, body = MockLLM.seen[-1]
        self.assertEqual(path, '/api/chat'); self.assertEqual(body['options']['num_ctx'], 32768); self.assertEqual(body['format'], 'json')

    def test_openai_compatible_retries_without_response_format(self):
        s = llm.resolve(config.normalize({'provider': 'custom', 'base_url': f'http://127.0.0.1:{self.port}/v1', 'model': 'local-model'}))
        r = llm.test(s)
        self.assertTrue(r['ok'], r)
        self.assertIn('response_format', MockLLM.seen[-2][1]); self.assertNotIn('response_format', MockLLM.seen[-1][1])

    def test_unreachable_endpoint_reports_clearly(self):
        s = llm.resolve(config.normalize({'provider': 'custom', 'base_url': f'http://127.0.0.1:{_free_port()}/v1', 'model': 'x'}))
        r = llm.test(s)
        self.assertFalse(r['ok']); self.assertIn('Is the server running', r['error'])


class Sources(unittest.TestCase):
    def test_private_addresses_refused(self):
        for url in ('http://127.0.0.1:1/x', 'http://localhost/', 'http://169.254.169.254/latest/'):
            with self.assertRaises(sources.SourceError): sources.fetch_source(url)


class Highlight(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(highlight('# Title', 'markdown')[0][0], '# ')
        toks = highlight("const x = load('a') // note", 'typescript')
        self.assertTrue(any(t[0].strip() == '// note' for t in toks))
        self.assertEqual(highlight('$ npm i', 'shell')[0][0], '$ ')



class TestUpscale(unittest.TestCase):
    def test_targets_are_9x16_and_even(self):
        from reelsmith.engine.upscale import TARGETS, scale_for
        for k, t in TARGETS.items():
            w, h = t['size']
            self.assertEqual((w % 2, h % 2), (0, 0))
            self.assertAlmostEqual(w / h, 9 / 16, places=3)
        self.assertEqual(scale_for('4k'), 2.0)

    def test_ffmpeg_upscale_keeps_audio_and_reports_progress(self):
        import shutil, subprocess
        if not shutil.which('ffmpeg'): self.skipTest('ffmpeg not installed')
        from reelsmith.engine.upscale import upscale
        d = tempfile.mkdtemp(); src, dst = os.path.join(d, 'in.mp4'), os.path.join(d, 'out.mp4')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=108x192:rate=30:duration=1',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-shortest', src], check=True)
        seen = []
        upscale(src, dst, '2k', 1.0, progress=seen.append, preset='ultrafast')
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height', '-of', 'csv=p=0', dst],
                             capture_output=True, text=True).stdout
        self.assertIn('video,1440,2560', out); self.assertIn('audio', out)
        self.assertTrue(seen and seen[-1] == 1.0 and min(seen) >= 0.0)

    def test_bad_target_rejected(self):
        from reelsmith.engine.upscale import upscale
        with self.assertRaises(ValueError): upscale('a.mp4', 'b.mp4', '8k')


class TestJobStore(unittest.TestCase):
    def _store(self, out, runner):
        from reelsmith.jobs import JobStore
        return JobStore(out, runner)

    def _wait(self, st, jid, states=('done', 'error', 'cancelled'), t=10):
        import time
        end = time.time() + t
        while time.time() < end:
            j = st.get(jid)
            if j and j['status'] in states: return j
            time.sleep(0.05)
        self.fail(f'job {jid} did not reach {states}')

    def test_sequential_cancel_retry_delete_and_restart(self):
        import time, threading
        out = tempfile.mkdtemp(); gate = threading.Event(); order = []
        def runner(job, hooks):
            order.append(job['title']); hooks['log']('working'); hooks['progress']('rendering', 0.5)
            if job['payload'].get('block'):
                while not gate.is_set():
                    if hooks['cancelled']():
                        from reelsmith.pipeline import Cancelled; raise Cancelled()
                    time.sleep(0.02)
            if job['payload'].get('fail'): raise RuntimeError('boom')
            d = os.path.join(out, 'job-' + job['id']); os.makedirs(d)
            return {'job': os.path.basename(d), 'dir': d, 'files': {'video': 'video.mp4'}, 'resolution': [540, 960]}, {'name': 'x'}, {}
        st = self._store(out, runner)
        a = st.submit('generate', {'topic': 'A', 'block': True})
        b = st.submit('generate', {'topic': 'B'})
        c = st.submit('generate', {'topic': 'C', 'fail': True})
        time.sleep(0.2)
        self.assertEqual(st.get(a)['status'], 'running')
        self.assertEqual((st.get(b)['status'], st.get(b)['position']), ('queued', 1))
        st.cancel(a)
        self.assertEqual(self._wait(st, a)['status'], 'cancelled')
        self.assertEqual(self._wait(st, b)['status'], 'done')
        self.assertEqual(self._wait(st, c)['status'], 'error')
        self.assertEqual(order, ['A', 'B', 'C'])                     # one at a time, in submission order
        r = st.retry(c); self.assertEqual(st.get(r)['retry_of'], c)
        self._wait(st, r)
        with self.assertRaises(ValueError): st.cancel(b)              # finished jobs can't be cancelled
        bdir = os.path.join(out, st.get(b)['result']['manifest']['job'])
        st.delete(b, files=True); self.assertIsNone(st.get(b)); self.assertFalse(os.path.exists(bdir))
        # restart: a job left "running" on disk becomes interrupted; queued ones resume
        import json
        j = st.get(c); j.update(status='running'); json.dump(j, open(os.path.join(out, '_jobs', c + '.json'), 'w'))
        q = {**st.get(r), 'id': 'queued0001', 'status': 'queued', 'created': time.time(), 'payload': {'topic': 'Q'}}
        json.dump(q, open(os.path.join(out, '_jobs', 'queued0001.json'), 'w'))
        st2 = self._store(out, runner)
        self.assertEqual(st2.get(c)['status'], 'interrupted')
        self.assertEqual(self._wait(st2, 'queued0001')['status'], 'done')


class TestNarration(unittest.TestCase):
    def test_clean_makes_lines_speakable(self):
        from reelsmith.narration import clean
        self.assertEqual(clean('Check out the link in the description at example.com #reels'), 'Check out the link in the description')
        self.assertNotIn('http', clean('Visit https://x.dev/a now'))
        self.assertEqual(clean('Follow @dev.talks for more 🚀'), 'Follow for more')

    def test_slots_and_srt(self):
        from reelsmith.narration import slots, srt
        plan = [{'type': 'hook', 'start': 0, 'duration': 4}, {'type': 'cta', 'start': 4, 'duration': 5}]
        sl = slots(plan, 9)
        self.assertAlmostEqual(sl[0][0], 0.1); self.assertLess(sl[1][1], 5 - 0.9 + 0.01)   # last scene leaves room for the fade
        out = srt([{'start': 0.1, 'end': 3.0, 'text': 'A fairly long line that has to be split across two subtitle cues.'}])
        self.assertIn('00:00:00,100 -->', out); self.assertEqual(out.count('-->'), 2)

    def test_heuristic_narration_fits_budget(self):
        from reelsmith.narration import write_heuristic, slots
        sb = {'name': 'Demo', 'scenes': [{'type': 'hook', 'kicker': 'Still', 'big': 'waiting', 'punch': 'on renders?'},
                                         {'type': 'cta', 'line': 'Try it'}]}
        plan = [{'type': 'hook', 'start': 0, 'duration': 3}, {'type': 'cta', 'start': 3, 'duration': 4}]
        sl = slots(plan, 7); lines = write_heuristic(sb, plan, sl)
        self.assertTrue(all(len(l.split()) <= w for l, (_, _, w) in zip(lines, sl)))
        self.assertIn('link in the description', lines[1].lower())


class TestTTSSettings(unittest.TestCase):
    def test_key_masked_and_kept(self):
        from reelsmith import tts
        os.environ['REELSMITH_CONFIG'] = os.path.join(tempfile.mkdtemp(), 'config.json')
        c = tts.save(tts.normalize({'provider': 'kokoro', 'api_key': 'secret-123456789'}))
        self.assertEqual(c['model'], 'kokoro'); self.assertEqual(c['voice'], 'af_heart')
        pub = tts.public(c); self.assertNotIn('secret', json.dumps(pub)); self.assertTrue(pub['has_key'])
        c2 = tts.normalize({'provider': 'kokoro', 'api_key': pub['api_key'], 'voice': 'am_michael'})
        self.assertEqual((c2['api_key'], c2['voice']), ('secret-123456789', 'am_michael'))
        self.assertEqual(oct(os.stat(tts.path()).st_mode & 0o777), '0o600')
        self.assertEqual(tts.normalize({'provider': 'openai'})['api_key'], '')       # never carried across providers


class TestNarrationParsing(unittest.TestCase):
    def test_reply_shapes(self):
        from reelsmith.narration import parse_lines
        want = ['One.', 'Two.', 'Three.']
        for reply in ('{"lines": ["One.", "Two.", "Three."]}',
                      '[{"scene": 1, "text": "One."}, {"scene": 2, "text": "Two."}, {"scene": 3, "text": "Three."}]',
                      '{"narration": [{"scene_number": 2, "voiceover": "Two."}, {"scene_number": 1, "voiceover": "One."}, {"scene_number": 3, "voiceover": "Three."}]}',
                      '{"1": "One.", "2": "Two.", "3": "Three."}', '{"line_1": "One.", "line_2": "Two.", "line_3": "Three."}',
                      'Sure!\n```json\n["One.", "Two.", "Three.",]\n```', '<think>hmm</think>{"lines": ["One.", "Two.", "Three."]}',
                      '[{"scene": 0, "line": "One."}, {"scene": 1, "line": "Two."}, {"scene": 2, "line": "Three."}]',
                      '{"script": {"1": {"text": "One."}, "2": {"text": "Two."}, "3": {"text": "Three."}}}'):
            self.assertEqual(parse_lines(reply, 3), want, reply)
        self.assertEqual(parse_lines('1. Scene one here.\n2. Scene two here.\n3. Scene three here.', 3),
                         ['Scene one here.', 'Scene two here.', 'Scene three here.'])

    def test_refusals_and_garbage_are_not_spoken(self):
        from reelsmith.narration import parse_lines
        for reply in ('{"error": "I cannot do that"}', 'I am sorry, I cannot.', '', 'Here you go:\nThis is a single sentence.'):
            self.assertIsNone(parse_lines(reply, 3), reply)

    def test_unusable_model_falls_back_to_on_screen_text(self):
        import numpy as np
        from reelsmith import narration as N, llm, tts
        sb = {'name': 'x', 'scenes': [{'type': 'hook', 'big': 'stitching', 'punch': 'by hand?'}, {'type': 'cta', 'line': 'Try it'}]}
        plan = [{'type': 'hook', 'start': 0, 'duration': 4}, {'type': 'cta', 'start': 4, 'duration': 5}]
        saved = (llm.complete, llm.provider, tts.speak)
        try:
            llm.complete = lambda *a, **k: 'I am sorry, I cannot.'
            llm.provider = lambda *a, **k: {'kind': 'mock'}
            tts.speak = lambda text, s, voice=None: np.full(4800, 0.2, np.float32)
            logs = []
            _, segs = N.build(sb, plan, 9, {'speed': 1.0}, use_llm=True, log=logs.append)
        finally:
            llm.complete, llm.provider, tts.speak = saved
        self.assertNotIn('sorry', ' '.join(s['text'] for s in segs).lower())
        self.assertTrue(any('continuing with narration read from the on-screen text' in l for l in logs))


class TestHostedRouterQuirks(unittest.TestCase):
    """OpenRouter-style behaviour, with the HTTP layer stubbed out."""
    def _run(self, responses, **over):
        from reelsmith import llm, config
        seen, it = [], iter(responses)
        def fake_req(url, headers=None, body=None, timeout=60, method=None):
            seen.append(json.loads(json.dumps(body)))
            r = next(it)
            if isinstance(r, Exception): raise r
            return r
        saved = (llm._req, llm.time.sleep)
        llm._req, llm.time.sleep = fake_req, (lambda *_: None)
        try:
            s = {**config.DEFAULTS, 'provider': 'openrouter', 'kind': 'openai', 'label': 'OpenRouter', 'base_url': 'http://x/v1',
                 'model': 'm', 'max_tokens': 1500, 'json_mode': True, **over}
            return llm.complete('sys', 'user', want_json=True, s=s), seen
        finally:
            llm._req, llm.time.sleep = saved

    ok = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"lines": ["a b"]}'}}]}

    def test_error_inside_200_is_retried(self):
        out, seen = self._run([{'error': {'code': 502, 'message': 'Provider returned error'}}, self.ok])
        self.assertIn('lines', out); self.assertEqual(len(seen), 2)

    def test_reasoning_budget_is_raised(self):
        cut = {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning': '...'}}]}
        out, seen = self._run([cut, cut, self.ok])
        self.assertEqual([b['max_tokens'] for b in seen], [1500, 3000, 6000])

    def test_reasoning_budget_gives_up_clearly(self):
        from reelsmith import llm
        cut = {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning': '...'}}]}
        with self.assertRaisesRegex(llm.LLMError, 'ran out of output tokens.*reasoning'):
            self._run([cut] * 4)

    def test_no_endpoint_for_json_mode_retries_without_it(self):
        from reelsmith import llm
        out, seen = self._run([llm.LLMError('404 from x: No endpoints found that can handle the requested parameters.'), self.ok])
        self.assertIn('response_format', seen[0]); self.assertNotIn('response_format', seen[1])

    def test_content_parts_and_bad_model(self):
        from reelsmith import llm
        parts = {'choices': [{'finish_reason': 'stop', 'message': {'content': [{'type': 'text', 'text': '{"lines": '}, {'type': 'text', 'text': '["a b"]}'}]}}]}
        self.assertEqual(json.loads(self._run([parts])[0]), {'lines': ['a b']})
        with self.assertRaisesRegex(llm.LLMError, 'not a valid model'):
            self._run([{'error': {'code': 400, 'message': 'x is not a valid model ID'}}])


class TestVoiceDiscovery(unittest.TestCase):
    def test_voice_list_shapes(self):
        from reelsmith.tts import _voice_names
        self.assertEqual(_voice_names({'voices': ['b', 'a']}), ['a', 'b'])
        self.assertEqual(_voice_names({'data': [{'id': 'nova'}, {'name': 'alloy'}]}), ['alloy', 'nova'])
        self.assertEqual(_voice_names({'af_heart': {'lang': 'en'}, 'bm_george': {}}), ['af_heart', 'bm_george'])
        for junk in ({'detail': 'Not Found'}, {'error': {'message': 'x'}}, {'status': 'ok'}, 'html'):
            self.assertEqual(_voice_names(junk), [], junk)

    def test_kokoro_without_voice_endpoint_suggests_standard_voices(self):
        from reelsmith import tts
        s = tts.normalize({'provider': 'kokoro', 'base_url': 'http://127.0.0.1:9/v1'}, old=dict(tts.DEFAULTS))
        r = tts.list_voices(s)
        self.assertEqual(r['source'], 'kokoro-standard'); self.assertIn('af_heart', r['voices'])


class TestTemplates(unittest.TestCase):
    def test_every_template_renders_every_scene_type(self):
        import skia
        from reelsmith.engine.timeline import Timeline
        from reelsmith.engine import templates as T
        sb = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'examples', 'carousel-crafter.json')))
        sb['scenes'].insert(4, {'type': 'bullets', 'caption': 'Why', 'checks': True, 'items': [{'title': 'A'}, {'title': 'B'}]})
        surf = skia.Surface(270, 480)
        for tid in T.TEMPLATES:
            tl = Timeline({**sb, 'template': tid})
            for p in tl.plan_summary():
                for frac in (0.5, 1.05):                      # mid-scene and mid-transition
                    c = surf.getCanvas(); c.save(); c.scale(0.25, 0.25)
                    tl.render_frame(c, int((p['start'] + p['duration'] * frac) * 30)); c.restore()

    def test_missing_glyphs_fall_back(self):
        from reelsmith.engine.lib import apply_template, I, runs
        apply_template('editorial')
        self.assertTrue(any(fb for _, fb in runs('✓ Done', I(800, 36))))
        apply_template('midnight')
        self.assertFalse(any(fb for _, fb in runs('✓ Done', I(800, 36))))

    def test_accent_rules(self):
        from reelsmith.storyboard import sanitize
        raw = {'name': 'X', 'accent': '#00FF00', 'scenes': [{'type': 'hook', 'big': 'Hi'}]}
        self.assertEqual(sanitize(raw, {'template': 'midnight'})['accent_source'], 'planner')   # Midnight leaves colour open
        pop = sanitize(raw, {'template': 'pop'})
        self.assertEqual((pop['accent'], pop['accent_source']), ('#2B59FF', 'template'))        # others keep their palette
        mine = sanitize(raw, {'template': 'pop', 'accent': '#FF0000'})
        self.assertEqual(sanitize({**mine, 'template': 'aurora'}, {})['accent'], '#FF0000')     # yours sticks

    def test_unknown_template_rejected(self):
        from reelsmith import pipeline
        with self.assertRaisesRegex(ValueError, 'Unknown template'):
            pipeline.generate({'topic': 'x', 'template': 'vaporwave'}, tempfile.mkdtemp(), use_llm=False, log=lambda m: None)

    def test_music_tempo_follows_template(self):
        import numpy as np
        from reelsmith.engine import audio, templates as T
        for tid in ('editorial', 'pop'):
            st = T.TEMPLATES[tid]['music']
            x = audio.music(12, 2.0, 10.0, st)[int(3 * audio.SR):int(9 * audio.SR), 0]
            low = audio.lp(np.abs(audio.lp(x, 150)), 20)[::100]; low -= low.mean()
            ac = np.correlate(low, low, 'full')[len(low) - 1:]; lags = np.arange(len(ac)) / (audio.SR / 100)
            ok = (lags > 60 / 160) & (lags < 60 / 70)
            self.assertAlmostEqual(60 / lags[ok][np.argmax(ac[ok])], st['bpm'], delta=2)

if __name__ == '__main__':
    unittest.main()
