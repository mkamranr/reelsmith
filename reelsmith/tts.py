"""Text-to-speech: settings and an OpenAI-compatible /audio/speech client.

Works with Kokoro-FastAPI, OpenAI, and anything else that serves POST {base}/audio/speech
({model, input, voice, response_format, speed} -> audio bytes). Settings live next to the LLM settings in
tts.json, owner-only, and the browser only ever sees the key masked.
"""
import base64
import json
import os
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.request

import numpy as np

from . import config as cfgmod

SR = 48000

PRESETS = {
    'kokoro': {'label': 'Kokoro', 'base_url': 'http://localhost:8880/v1', 'model': 'kokoro', 'voice': 'af_heart',
               'needs_key': False, 'help': 'Kokoro-FastAPI (OpenAI-compatible). Voices look like af_heart, am_michael, bf_emma.'},
    'openai': {'label': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini-tts', 'voice': 'alloy',
               'needs_key': True, 'help': 'Uses your OpenAI API key.'},
    'custom': {'label': 'Other OpenAI-compatible', 'base_url': 'http://localhost:8000/v1', 'model': '', 'voice': '',
               'needs_key': False, 'help': 'Any server exposing POST /v1/audio/speech (openedai-speech, LocalAI, a gateway…).'},
}
OPENAI_VOICES = ['alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer', 'verse']

_LOCAL = os.environ.get('REELSMITH_LOCAL_HOST', '').strip()
if _LOCAL:
    for _p in PRESETS.values():
        _p['base_url'] = _p['base_url'].replace('//localhost:', f'//{_LOCAL}:')
if os.environ.get('REELSMITH_TTS_URL'):             # e.g. http://kokoro:8880/v1 for the bundled compose service
    PRESETS['kokoro']['base_url'] = os.environ['REELSMITH_TTS_URL'].rstrip('/')

DEFAULTS = {'provider': 'none', 'base_url': '', 'api_key': '', 'model': '', 'voice': '', 'speed': 1.0,
            'response_format': 'wav', 'timeout': 120, 'headers': {}}


class TTSError(Exception):
    pass


# ------------------------------------------------------------------ settings
def path():
    return os.path.join(os.path.dirname(cfgmod.path()), 'tts.json')


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(path()) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def normalize(new, old=None):
    old = old or load()
    cfg = dict(DEFAULTS); cfg.update(old)
    prov = str(new.get('provider', cfg['provider'])).strip()
    if prov not in PRESETS and prov != 'none':
        raise ValueError(f'Unknown TTS provider "{prov}". Choose one of: none, {", ".join(PRESETS)}.')
    if prov != cfg['provider']:
        cfg.update({'api_key': '', 'base_url': '', 'model': '', 'voice': '', 'headers': {}})
    cfg['provider'] = prov
    for k in ('base_url', 'model', 'voice'):
        if k in new: cfg[k] = str(new[k] or '').strip()
    if prov in PRESETS:
        p = PRESETS[prov]
        cfg['base_url'] = (cfg['base_url'] or p['base_url']).rstrip('/')
        cfg['model'] = cfg['model'] or p['model']
        cfg['voice'] = cfg['voice'] or p['voice']
        if not cfg['base_url'].startswith(('http://', 'https://')):
            raise ValueError('The TTS endpoint URL must start with http:// or https://')
    key = new.get('api_key')
    if key is not None and not cfgmod.is_masked(str(key)):
        cfg['api_key'] = str(key).strip()
    if new.get('speed') not in (None, ''):
        try: cfg['speed'] = max(0.5, min(2.0, float(new['speed'])))
        except (TypeError, ValueError): raise ValueError('speed must be a number between 0.5 and 2')
    if new.get('timeout') not in (None, ''):
        try: cfg['timeout'] = max(10, min(1800, int(new['timeout'])))
        except (TypeError, ValueError): raise ValueError('timeout must be a number of seconds')
    if new.get('response_format') in ('wav', 'mp3', 'flac', 'opus', 'aac', 'pcm'):
        cfg['response_format'] = new['response_format']
    if isinstance(new.get('headers'), dict):
        prev = cfg.get('headers') or {}
        cfg['headers'] = {str(k): (prev.get(k, '') if cfgmod.is_masked(str(v)) else str(v))
                          for k, v in new['headers'].items() if str(k).strip()}
    return cfg


def save(cfg):
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, 'w') as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, p)
    try: os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError: pass
    return cfg


def public(cfg):
    out = {k: v for k, v in cfg.items() if k not in ('api_key', 'headers')}
    out['api_key'] = cfgmod.mask(cfg.get('api_key', ''))
    out['has_key'] = bool(cfg.get('api_key'))
    out['headers'] = {k: cfgmod.mask(v) for k, v in (cfg.get('headers') or {}).items()}
    return out


def settings():
    """Saved settings if a provider is configured, else None."""
    c = load()
    return c if c['provider'] in PRESETS and c.get('model') else None


# ------------------------------------------------------------------ client
def _headers(s):
    h = {'Content-Type': 'application/json', 'User-Agent': 'Reelsmith', **(s.get('headers') or {})}
    if s.get('api_key'): h['Authorization'] = 'Bearer ' + s['api_key']
    return h


def synth(text, s, voice=None):
    """Speak `text`; returns raw audio bytes in s['response_format']."""
    if PRESETS.get(s.get('provider'), {}).get('needs_key') and not s.get('api_key'):
        raise TTSError(f"{PRESETS[s['provider']]['label']} needs an API key (Settings → Voice).")
    url = s['base_url'].rstrip('/') + '/audio/speech'
    body = {'model': s['model'], 'input': text, 'voice': voice or s.get('voice') or 'alloy',
            'response_format': s.get('response_format') or 'wav', 'speed': float(s.get('speed') or 1.0)}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=_headers(s), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=int(s.get('timeout') or 120)) as r:
            data = r.read()
            ctype = r.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        raise TTSError(f'{e.code} from {url}: {e.read().decode(errors="replace")[:400]}') from e
    except urllib.error.URLError as e:
        hint = cfgmod.connection_hint(url) or (' Is the TTS server running and listening on 0.0.0.0?' if 'host.docker.internal' in url else '')
        raise TTSError(f'Could not reach {url}: {e.reason}.{hint}') from e
    except TimeoutError as e:
        raise TTSError(f'{url} did not answer within {s.get("timeout")}s. Raise the TTS timeout in Settings.') from e
    if 'json' in ctype or data[:1] == b'{':
        raise TTSError(f'{url} returned JSON instead of audio: {data[:300].decode(errors="replace")}')
    if len(data) < 100:
        raise TTSError(f'{url} returned almost no audio ({len(data)} bytes).')
    return data


def decode(data, fmt='wav'):
    """Any audio bytes -> mono float32 at SR, via ffmpeg (handles wav/mp3/opus/flac/aac; pcm = 24 kHz s16le)."""
    if not shutil.which('ffmpeg'): raise TTSError('ffmpeg not found on PATH.')
    inp = ['-f', 's16le', '-ar', '24000', '-ac', '1'] if fmt == 'pcm' else []
    p = subprocess.run(['ffmpeg', '-loglevel', 'error', *inp, '-i', 'pipe:0', '-ac', '1', '-ar', str(SR), '-f', 'f32le', 'pipe:1'],
                       input=data, capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise TTSError(f'Could not decode the TTS audio: {p.stderr.decode(errors="replace")[-300:]}')
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def speak(text, s, voice=None):
    return decode(synth(text, s, voice), s.get('response_format') or 'wav')


# Standard English voices of Kokoro-82M v1.0. Offered as suggestions when a server doesn't list its own;
# "Play a sample" is what confirms a given server accepts a name.
KOKORO_VOICES = ['af_heart', 'af_alloy', 'af_aoede', 'af_bella', 'af_jessica', 'af_kore', 'af_nicole', 'af_nova', 'af_river',
                 'af_sarah', 'af_sky', 'am_adam', 'am_echo', 'am_eric', 'am_fenrir', 'am_liam', 'am_michael', 'am_onyx',
                 'am_puck', 'am_santa', 'bf_alice', 'bf_emma', 'bf_isabella', 'bf_lily', 'bm_daniel', 'bm_fable',
                 'bm_george', 'bm_lewis']


def _voice_names(data):
    """Voice names from the shapes servers use: ["a", ...], [{"id"|"name"|"voice_id": ...}], {"voices"|"data": [...]},
    or {"af_heart": {...}, ...}."""
    if isinstance(data, dict):
        for k in ('voices', 'data', 'items', 'results'):
            if k in data: return _voice_names(data[k])
        # {"af_heart": {...}, ...}: only when every value is a record, so {"detail": "Not Found"} isn't read as a voice
        if data and all(isinstance(v, (dict, list)) for v in data.values()) and \
                all(isinstance(k, str) and 1 < len(k) < 60 and ' ' not in k for k in data) and \
                not set(data) & {'detail', 'error', 'errors', 'message', 'status', 'code'}:
            return sorted(data)
        return []
    if isinstance(data, list):
        out = []
        for v in data:
            if isinstance(v, str): out.append(v)
            elif isinstance(v, dict):
                n = v.get('id') or v.get('voice_id') or v.get('name') or v.get('voice')
                if isinstance(n, str): out.append(n)
        return sorted(set(out))
    return []


def list_voices(s):
    """Returns {'voices': [...], 'source': 'server' | 'kokoro-standard' | 'openai-standard' | 'none', 'url': ...}."""
    from urllib.parse import urlparse
    base = s['base_url'].rstrip('/')
    u = urlparse(base); root = f'{u.scheme}://{u.netloc}'
    candidates = [base + '/audio/voices', root + '/v1/audio/voices', base + '/voices', root + '/v1/voices',
                  root + '/voices', root + '/api/voices', root + '/api/v1/voices', root + '/api/v1/audio/voices']
    for url in dict.fromkeys(candidates):
        try:
            req = urllib.request.Request(url, headers=_headers(s))
            with urllib.request.urlopen(req, timeout=6) as r:
                raw = r.read(2_000_000)
            if raw.lstrip()[:1] not in (b'{', b'['):
                continue                                       # e.g. a web UI answering every path with its HTML page
            data = json.loads(raw.decode(errors='replace'))
            names = _voice_names(data)
            if names: return {'voices': names, 'source': 'server', 'url': url}
        except Exception:
            continue
    if s.get('provider') == 'openai': return {'voices': OPENAI_VOICES, 'source': 'openai-standard', 'url': None}
    if s.get('provider') == 'kokoro' or 'kokoro' in (s.get('model') or '').lower():
        return {'voices': KOKORO_VOICES, 'source': 'kokoro-standard', 'url': None}
    return {'voices': [], 'source': 'none', 'url': None}


def test(s, voice=None):
    """Speak a short sample. Returns {ok, seconds, duration, audio (data URL for the browser), error}."""
    out = {'ok': False, 'seconds': None, 'duration': None, 'audio': None, 'error': None}
    t0 = time.time()
    try:
        data = synth('Hi, this is your Reelsmith voice-over. Here is how I will sound in your videos.', s, voice)
        pcm = decode(data, s.get('response_format') or 'wav')
        out.update(ok=True, duration=round(len(pcm) / SR, 2))
        mime = {'mp3': 'audio/mpeg', 'opus': 'audio/ogg', 'flac': 'audio/flac', 'aac': 'audio/aac'}.get(s.get('response_format'), 'audio/wav')
        if s.get('response_format') == 'pcm':
            import io, wave
            buf = io.BytesIO(); w = wave.open(buf, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(pcm, -1, 1) * 32767).astype('<i2').tobytes()); w.close(); data, mime = buf.getvalue(), 'audio/wav'
        out['audio'] = f'data:{mime};base64,' + base64.b64encode(data).decode()
    except TTSError as e:
        out['error'] = str(e)
    out['seconds'] = round(time.time() - t0, 1)
    return out
