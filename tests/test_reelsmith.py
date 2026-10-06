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
        self.assertAlmostEqual(sl[0][0], 0.05); self.assertLess(sl[1][1], 5 - 0.9 + 0.01)  # speech starts with the cold open; room for the end
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
        sb['scenes'][5:5] = [{'type': 'quote', 'text': 'A post should never silently look wrong.', 'by': 'The README'},
                             {'type': 'chapter', 'number': 'II.', 'title': 'The editor', 'body': 'Markdown on the left, slides on the right.'},
                             {'type': 'rank', 'rank': '3', 'of': 5, 'title': 'Captions', 'sub': 'Written for you'},
                             {'type': 'teaser', 'lines': ['Every frame.', 'Drawn in code.']},
                             {'type': 'scroll', 'image': 'page.png', 'kind': 'readme', 'url': 'github.com/o/r', 'caption': 'See it'}]
        from reelsmith.capture import readme_page
        assets = tempfile.mkdtemp(); readme_page('# Tool\n\nIt turns notes into slides.\n\n- one\n- two\n', 'Tool', 'github.com/o/r', {}, os.path.join(assets, 'page.png'))
        sb['asset_dir'] = assets
        sb['spoken'] = [{'start': 1.0, 'end': 4.0, 'text': 'Write the post, skip the design.'}]
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


class TestStructures(unittest.TestCase):
    SRC = {'kind': 'github', 'url': 'github.com/o/r', 'title': 'tool', 'facts': {'stars': 120},
           'text': 'Tool turns notes into slides.\n\n## Features\n\n### Live preview\n\nSee every slide as you type it.\n\n'
                   '### Smart fitting\n\nText shrinks before it overflows.\n\n### Captions\n\nA caption is written for you.\n\n'
                   '### Backgrounds\n\nGenerated from your accent.\n\n```bash\nnpx tool init\n```\n'}
    OPENERS = {'midnight': 'hook', 'editorial': 'quote', 'terminal': 'terminal', 'pop': 'hook', 'minimal': 'title', 'aurora': 'teaser',
               'cinema': 'teaser', 'showcase': 'hook', 'broadcast': 'title'}
    SIGNATURE = {'editorial': 'chapter', 'pop': 'rank', 'aurora': 'teaser', 'terminal': 'terminal'}

    def test_builtin_plans_follow_each_template(self):
        from reelsmith.storyboard import plan_heuristic
        shapes = set()
        for tid, opener in self.OPENERS.items():
            sb = plan_heuristic({'template': tid, 'duration': 45}, self.SRC)
            types = [s['type'] for s in sb['scenes']]
            self.assertEqual(types[0], opener, tid); self.assertEqual(types[-1], 'cta', tid)
            if tid in self.SIGNATURE: self.assertIn(self.SIGNATURE[tid], types, tid)
            shapes.add(tuple(types))
        self.assertEqual(len(shapes), len(self.OPENERS))           # six different structures

    def test_numbering(self):
        from reelsmith.storyboard import plan_heuristic
        pop = plan_heuristic({'template': 'pop', 'duration': 30}, self.SRC)
        ranks = [s for s in pop['scenes'] if s['type'] == 'rank']
        self.assertEqual([r['rank'] for r in ranks], [str(n) for n in range(len(ranks), 0, -1)])
        self.assertTrue(all(r['of'] == len(ranks) for r in ranks))
        ed = plan_heuristic({'template': 'editorial', 'duration': 45}, self.SRC)
        self.assertEqual([c['number'] for c in ed['scenes'] if c['type'] == 'chapter'][:3], ['I.', 'II.', 'III.'])

    def test_structure_holds_when_the_model_ignores_it(self):
        from reelsmith import storyboard as sbm, llm
        reply = {'name': 'tool', 'scenes': [{'type': 'hook', 'kicker': 'Still', 'big': 'stuck', 'punch': 'on slides?'},
                 {'type': 'bullets', 'items': [{'title': 'A one'}, {'title': 'B two'}, {'title': 'C three'}]}, {'type': 'cta'}]}
        saved = (llm.complete_json, llm.provider)
        llm.complete_json = lambda *a, **k: json.loads(json.dumps(reply)); llm.provider = lambda *a, **k: {'kind': 'mock'}
        try:
            pop, _ = sbm.plan({'template': 'pop', 'duration': 30}, self.SRC)
            ed, _ = sbm.plan({'template': 'editorial', 'duration': 30}, self.SRC)
        finally:
            llm.complete_json, llm.provider = saved
        self.assertEqual([s['type'] for s in pop['scenes']], ['coldopen', 'rank', 'rank', 'rank', 'cta'])   # cold open replaces the hook
        self.assertEqual([s['type'] for s in ed['scenes']][:4], ['coldopen', 'quote', 'chapter', 'chapter'])

    def test_restructure_existing_storyboard(self):
        from reelsmith import storyboard as sbm
        mid = sbm.plan_heuristic({'template': 'midnight', 'duration': 30}, self.SRC)
        pop = sbm.restructure(sbm.sanitize(mid, {'template': 'pop'}), {'template': 'pop'})
        self.assertIn('rank', [s['type'] for s in pop['scenes']])


class TestPageTourAndCaptions(unittest.TestCase):
    def test_readme_page_and_scroll_placement(self):
        from reelsmith.capture import readme_page
        from reelsmith.blueprints import add_scroll
        from reelsmith.engine import templates as T
        from reelsmith.storyboard import plan_heuristic
        d = tempfile.mkdtemp()
        info = readme_page('# X\n\nPara one\ncontinues here.\n\n---\n\n## Two\n\n- item\n  more\n\n```bash\nnpx x\n```\n', 'X', 'github.com/o/x', {'stars': 3}, os.path.join(d, 'p.png'))
        self.assertEqual((info['kind'], info['width']), ('readme', 1080))
        src = TestStructures.SRC
        for tid in T.TEMPLATES:
            sc = add_scroll(plan_heuristic({'template': tid, 'duration': 40}, src)['scenes'], tid, 'p.png', 'readme', 'x', 'See it')
            types = [s['type'] for s in sc]
            self.assertEqual(types.count('scroll'), 1, tid)
            self.assertNotEqual(types[0], 'scroll', tid); self.assertEqual(types[-1], 'cta', tid)

    def test_caption_groups(self):
        from reelsmith.engine.timeline import Timeline
        g = Timeline._caption_groups([{'start': 0.0, 'end': 3.0, 'text': 'Write the post, skip the design. Ship it today.'}])
        self.assertTrue(all(len(x[2]) <= 4 for x in g))
        self.assertAlmostEqual(g[0][0], 0.0); self.assertAlmostEqual(g[-1][1], 3.0, places=5)
        self.assertEqual(' '.join(w for x in g for w, _, _ in x[2]), 'Write the post, skip the design. Ship it today.')


class TestLogin(unittest.TestCase):
    def test_password_protects_everything_but_healthz(self):
        import base64, socket, threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        os.environ['REELSMITH_PASSWORD'] = 's3cret'; os.environ['REELSMITH_CONFIG'] = os.path.join(tempfile.mkdtemp(), 'c.json')
        try:
            from reelsmith.server import make_handler
            from reelsmith.jobs import JobStore
            sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
            srv = ThreadingHTTPServer(('127.0.0.1', port), make_handler(JobStore(tempfile.mkdtemp(), lambda j, h: None), port))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            def get(path, auth=None):
                h = {'Authorization': 'Basic ' + base64.b64encode(auth.encode()).decode()} if auth else {}
                try:
                    with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers=h)) as r: return r.status
                except urllib.error.HTTPError as e: return e.code
            self.assertEqual(get('/api/status'), 401)
            self.assertEqual(get('/api/status', 'reelsmith:wrong'), 401)
            self.assertEqual(get('/api/status', 'reelsmith:s3cret'), 200)
            self.assertEqual(get('/healthz'), 200)
            srv.shutdown()
        finally:
            os.environ.pop('REELSMITH_PASSWORD', None)


class TestHandleAndLongPages(unittest.TestCase):
    INFO = {'width': 860, 'height': 14000, 'focus_y': 3290}

    def _sb(self, tid, D, handle='mkamranr'):
        from reelsmith.storyboard import sanitize
        from reelsmith.blueprints import add_scroll
        base = {'name': 'x', 'handle': handle, 'scenes': [{'type': 'hook', 'big': 'Hi'}, {'type': 'title', 'name': 'x'},
                {'type': 'statement', 'text': 'One.'}, {'type': 'bullets', 'items': [{'title': 'A'}, {'title': 'B'}]}, {'type': 'cta'}]}
        sb = sanitize({**base, 'duration': D}, {'template': tid, 'duration': D})
        sb['scenes'] = add_scroll(sb['scenes'], tid, 'p.png', 'screenshot', 'github.com/o/r', 'See it', self.INFO)
        return sb

    def test_handle_normalised_and_drawn(self):
        import skia
        from reelsmith.engine.timeline import Timeline
        self.assertEqual(Timeline(self._sb('midnight', 20)).handle, '@mkamranr')
        self.assertEqual(Timeline(self._sb('midnight', 20, 'mysite.dev')).handle, 'mysite.dev')
        self.assertEqual(Timeline(self._sb('midnight', 20, '')).handle, '')
        surf = skia.Surface(1080, 1920)
        for tid in ('midnight', 'pop', 'terminal', 'broadcast', 'cinema'):      # every handle style draws
            tl = Timeline(self._sb(tid, 20)); tl.render_frame(surf.getCanvas(), 5 * 30)

    def test_long_readme_scrolls_slowly_and_is_never_dropped(self):
        from reelsmith.engine.timeline import Timeline
        for D in (15, 30, 60):
            tl = Timeline(self._sb('showcase', D))
            sc = next((x for x in tl.scenes if x.kind == 'scroll'), None)
            self.assertIsNotNone(sc, D)                                        # survives even at 15 s
            self.assertLessEqual(sc.dur, 0.45 * D + 0.6)                         # never takes over the video
            start = 1.0 + sc.ta + sc.tdw
            offs = [sc.offset(start + f / 30) for f in range(int((sc.dur - start) * 30))]
            v = [(b - a) * 30 for a, b in zip(offs, offs[1:])]
            self.assertTrue(all(x >= -1e-6 for x in v))                          # only ever scrolls down
            self.assertLessEqual(max(v), 210)                                    # reading speed through the README
        self.assertGreater(Timeline(self._sb('showcase', 60)).scenes[2].dur, Timeline(self._sb('showcase', 30)).scenes[2].dur)


class TestRetention(unittest.TestCase):
    SRC = None

    def setUp(self):
        self.src = TestStructures.SRC

    def test_hook_ranking_penalises_filler_and_length(self):
        from reelsmith import hooks, llm
        cands = {'hooks': [{'text': 'Hey guys, check out this tool', 'clarity': 10, 'curiosity': 10, 'specificity': 10, 'fit': 10},
                           {'text': 'Still writing slides by hand?', 'accent': 'by hand', 'pattern': 'problem', 'clarity': 9, 'curiosity': 8, 'specificity': 7, 'fit': 9},
                           {'text': 'One two three four five six seven eight nine ten eleven', 'clarity': 10, 'curiosity': 10, 'specificity': 10, 'fit': 10}]}
        saved = llm.complete_json
        llm.complete_json = lambda *a, **k: json.loads(json.dumps(cands))
        try:
            ranked = hooks.write_hooks({'name': 'x', 'scenes': []}, {}, None)
        finally:
            llm.complete_json = saved
        self.assertEqual(ranked[0]['text'], 'Still writing slides by hand?')
        self.assertEqual(ranked[-1]['text'], 'Hey guys, check out this tool')

    def test_every_template_opens_on_the_hook_at_frame_0(self):
        from reelsmith import storyboard as sbm
        from reelsmith.engine import templates as T
        for tid in T.TEMPLATES:
            sb, _ = sbm.plan({'template': tid, 'duration': 15, 'topic': 'Stop writing slides by hand'}, self.src, use_llm=False, log=lambda m: None)
            self.assertEqual(sb['scenes'][0]['type'], 'coldopen', tid)
            self.assertEqual(sb['scenes'][-1]['type'], 'cta', tid)
            self.assertNotEqual(sb['scenes'][1]['type'], 'hook', tid)            # no hook said twice

    def test_micro_format_and_engagement(self):
        from reelsmith import storyboard as sbm
        sb, _ = sbm.plan({'template': 'pop', 'duration': 8, 'topic': 'x y z', 'engage': 'comment', 'keyword': 'link'}, self.src,
                         use_llm=False, log=lambda m: None)
        self.assertLessEqual(len(sb['scenes']), 3)
        self.assertEqual(sb['scenes'][0]['type'], 'coldopen')
        self.assertEqual(sb['scenes'][-1]['engage'], 'Comment \u201cLINK\u201d for the link')
        self.assertEqual(sbm.engagement({'engage': 'comment'}, {})[0], 'save')       # no keyword, no promise to reply
        self.assertIsNone(sbm.engagement({'engage': 'none'}, {}))

    def test_loop_ends_on_the_first_frame(self):
        import skia, numpy as np
        from reelsmith import storyboard as sbm
        from reelsmith.engine.timeline import Timeline
        sb, _ = sbm.plan({'template': 'midnight', 'duration': 10, 'topic': 'Stop writing slides by hand'}, self.src, use_llm=False, log=lambda m: None)
        tl = Timeline(sb); surf = skia.Surface(270, 480)
        def frame(f):
            c = surf.getCanvas(); c.clear(skia.ColorBLACK); c.save(); c.scale(.25, .25); tl.render_frame(c, f); c.restore()
            return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType).astype(int)
        self.assertLess(np.abs(frame(0) - frame(int(sb['duration'] * 30) - 1)).mean(), 2.0)

    def test_pipeline_writes_checklist(self):
        import shutil
        if not shutil.which('ffmpeg'): self.skipTest('ffmpeg not installed')
        from reelsmith import pipeline
        m, sb, caps = pipeline.generate({'topic': 'Stop writing slides by hand', 'duration': 6, 'audience': 'tech creators', 'template': 'minimal'},
                                        tempfile.mkdtemp(), 'draft', use_llm=False, log=lambda x: None)
        labels = {c['label']: c['ok'] for c in m['checks']}
        self.assertTrue(labels['Hook on screen from the first frame'])
        self.assertTrue(labels['Niche stated'])
        self.assertTrue(labels['Asks for a save, comment or share'])
        self.assertTrue(caps.get('pinned_comment'))
        self.assertEqual(len(m['covers']), 3)                                  # main cover + two alternatives
        self.assertEqual(len({c['style'] for c in m['covers']}), 3)
        for cv in m['covers']: self.assertTrue(os.path.exists(os.path.join(m['dir'], cv['file'])))


class TestCoversAndPagePacing(unittest.TestCase):
    def test_every_cover_style_renders(self):
        from reelsmith import storyboard as sbm
        from reelsmith.engine.cover import render_cover, STYLES, default_style
        from reelsmith.engine import templates as T
        from PIL import Image
        d = tempfile.mkdtemp()
        sb, _ = sbm.plan({'template': 'midnight', 'duration': 15, 'topic': 'Stop writing slides by hand', 'handle': 'me'},
                         TestStructures.SRC, use_llm=False, log=lambda m: None)
        for st in STYLES:
            self.assertEqual(render_cover(sb, os.path.join(d, st + '.png'), style=st), st)
            self.assertEqual(Image.open(os.path.join(d, st + '.png')).size, (1080, 1920))
        for tid in T.TEMPLATES:                                              # each template's own layout
            sbt = {**sb, 'template': tid}
            self.assertEqual(render_cover(sbt, os.path.join(d, tid + '.png')), default_style(sbt))
        self.assertGreaterEqual(len({default_style({'template': t}) for t in T.TEMPLATES}), 8)   # covers differ by template

    def test_short_video_keeps_its_story_around_a_long_page(self):
        from reelsmith.engine.timeline import Timeline
        from reelsmith.blueprints import add_scroll
        from reelsmith.storyboard import sanitize
        base = {'name': 'x', 'scenes': [{'type': 'coldopen', 'text': 'Your README as a Reel'}, {'type': 'title', 'name': 'x'},
                {'type': 'statement', 'text': 'One.'}, {'type': 'bullets', 'items': [{'title': 'A'}, {'title': 'B'}]}, {'type': 'cta'}]}
        sb = sanitize({**base, 'duration': 15}, {'template': 'midnight', 'duration': 15})
        sb['scenes'] = add_scroll(sb['scenes'], 'midnight', 'p.png', 'screenshot', 'x', 'See it', {'width': 860, 'height': 14000, 'focus_y': 3290})
        kinds = [s.kind for s in Timeline(sb).scenes]
        self.assertIn('scroll', kinds)
        self.assertTrue(set(kinds) - {'coldopen', 'scroll', 'cta'}, kinds)     # some of the story survives next to the page
        sc = next(s for s in Timeline(sb).scenes if s.kind == 'scroll')
        self.assertGreater(sc.offset(sc.START + 0.3), 0)                       # moving within half a second
        self.assertGreater(sc.dur - sc.START - sc.ta - sc.tdw - 0.6, 3.5)      # most of the scene is README reading

    def test_rerender_without_browser_still_shows_the_page(self):
        import shutil
        if not shutil.which('ffmpeg'): self.skipTest('ffmpeg not installed')
        from reelsmith import pipeline, capture, sources
        saved = (capture._browser_ok, sources.fetch_source, pipeline.fetch_source)
        fake = lambda url: {'kind': 'github', 'title': 'x', 'url': 'github.com/o/x', 'facts': {}, 'text': '# X\n\nA tool.\n\n- one\n- two\n'}
        capture._browser_ok = False; pipeline.fetch_source = fake
        try:
            sb0 = {'name': 'x', 'url': 'github.com/o/x', 'template': 'minimal', 'duration': 8,
                   'scenes': [{'type': 'coldopen', 'text': 'A tool for x'}, {'type': 'cta'}]}
            m, sb, _ = pipeline.generate({'duration': 8}, tempfile.mkdtemp(), 'draft', storyboard=sb0, use_llm=False, log=lambda x: None)
        finally:
            capture._browser_ok, sources.fetch_source, pipeline.fetch_source = saved
        chk = next(c for c in m['checks'] if c['label'] == 'Page scroll-through')
        self.assertTrue(chk['ok'], chk); self.assertIn('README', chk['detail'])


class TestDelete(unittest.TestCase):
    def _store(self, runner):
        from reelsmith.jobs import JobStore
        out = tempfile.mkdtemp()
        return JobStore(out, runner), out

    def _wait(self, st, jid, done, t=10):
        import time
        end = time.time() + t
        while time.time() < end:
            if done(st.get(jid)): return
            time.sleep(0.05)
        self.fail('timed out')

    def test_finished_failed_queued_and_running_jobs_delete_everything(self):
        import time, threading
        gate = threading.Event()
        def runner(job, hooks):
            d = os.path.join(st_out[0], 'job-' + job['id']); os.makedirs(d)
            hooks['dir'](d)                                   # the folder exists before anything can fail
            with open(os.path.join(d, 'video.mp4'), 'wb') as f: f.write(b'x' * 50_000)
            mode = job['payload'].get('mode')
            if mode == 'fail': raise RuntimeError('boom')
            if mode == 'block':
                while not hooks['cancelled']():
                    time.sleep(0.02)
                from reelsmith.pipeline import Cancelled; raise Cancelled()
            return {'job': os.path.basename(d), 'dir': d, 'files': {}}, {'name': 'x'}, {}
        st_out = [None]
        st, out = self._store(runner); st_out[0] = out
        ok = st.submit('generate', {'topic': 'ok'}); self._wait(st, ok, lambda j: j['status'] == 'done')
        bad = st.submit('generate', {'topic': 'bad', 'mode': 'fail'}); self._wait(st, bad, lambda j: j['status'] == 'error')
        sizes = {j['id']: j['bytes'] for j in st.list()}
        self.assertGreaterEqual(sizes[ok], 50_000); self.assertGreaterEqual(sizes[bad], 50_000)
        self.assertGreaterEqual(st.disk_usage(), 100_000)
        dirs = {jid: st.job_dir(st.get(jid)) for jid in (ok, bad)}
        r = st.delete(ok); self.assertGreaterEqual(r['bytes'], 50_000); self.assertFalse(os.path.exists(dirs[ok]))
        st.delete(bad); self.assertFalse(os.path.exists(dirs[bad]))           # failed jobs leave no partial files
        self.assertIsNone(st.get(ok)); self.assertFalse(os.path.exists(os.path.join(out, '_jobs', ok + '.json')))
        run = st.submit('generate', {'topic': 'run', 'mode': 'block'}); self._wait(st, run, lambda j: j['status'] == 'running' and j.get('out_dir'))
        q = st.submit('generate', {'topic': 'queued', 'mode': 'block'})
        self.assertFalse(st.delete(q)['pending']); self.assertIsNone(st.get(q))  # queued: gone at once, never runs
        run_dir = st.get(run)['out_dir']
        self.assertTrue(st.delete(run)['pending'])                                # running: stopped, then removed
        self._wait(st, run, lambda j: j is None)
        self.assertFalse(os.path.exists(run_dir))
        self.assertEqual(sorted(os.listdir(out)), ['_jobs'])                      # nothing left behind

if __name__ == '__main__':
    unittest.main()
