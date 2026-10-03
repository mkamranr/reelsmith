"""LLM client — no SDKs, just HTTP + JSON.

Where settings come from (first match wins):
  1. Saved settings (web app → Settings, or `reelsmith config set …`), see config.py
  2. Environment: ANTHROPIC_API_KEY  → Anthropic
                  OPENAI_BASE_URL and/or OPENAI_API_KEY → OpenAI-compatible endpoint
                  OLLAMA_HOST → Ollama
     REELSMITH_MODEL overrides the model name.

Three wire formats:
  anthropic — POST {base}/v1/messages
  openai    — POST {base}/chat/completions   (OpenAI, OpenRouter, vLLM, LM Studio, llama.cpp, LocalAI, …)
  ollama    — POST {base}/api/chat           (native API, so the context window (num_ctx) can be set; Ollama's
                                              OpenAI-compatible route silently truncates long prompts to its default)
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import config as cfgmod


class LLMError(Exception):
    pass


def settings():
    """Resolved settings dict, or None when no LLM is configured."""
    c = cfgmod.load()
    if c['provider'] in cfgmod.PRESETS:
        p = cfgmod.PRESETS[c['provider']]
        return {**c, 'kind': p['kind'], 'label': p['label'], 'local': p['local'], 'source': 'settings'}
    env_model = os.environ.get('REELSMITH_MODEL')
    if os.environ.get('ANTHROPIC_API_KEY'):
        return {**cfgmod.DEFAULTS, 'provider': 'anthropic', 'kind': 'anthropic', 'label': 'Anthropic', 'local': False,
                'base_url': 'https://api.anthropic.com', 'api_key': os.environ['ANTHROPIC_API_KEY'],
                'model': env_model or 'claude-sonnet-5-5', 'source': 'env'}
    if os.environ.get('OPENAI_BASE_URL') or os.environ.get('OPENAI_API_KEY'):
        base = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
        return {**cfgmod.DEFAULTS, 'provider': 'custom', 'kind': 'openai', 'label': 'OpenAI-compatible',
                'local': 'localhost' in base or '127.0.0.1' in base, 'base_url': base,
                'api_key': os.environ.get('OPENAI_API_KEY', ''), 'model': env_model or 'gpt-4o-mini', 'source': 'env'}
    if os.environ.get('OLLAMA_HOST'):
        host = os.environ['OLLAMA_HOST']
        if not host.startswith('http'): host = 'http://' + host
        return {**cfgmod.DEFAULTS, **{k: v for k, v in cfgmod.PRESETS['ollama'].items() if k in cfgmod.DEFAULTS},
                'provider': 'ollama', 'kind': 'ollama', 'label': 'Ollama', 'local': True, 'base_url': host.rstrip('/'),
                'model': env_model or 'llama3.1:8b', 'source': 'env'}
    return None


def provider():
    s = settings()
    return s and {'kind': s['kind'], 'label': s['label'], 'model': s['model'], 'local': s['local'],
                  'base_url': s['base_url'], 'source': s['source']}


def resolve(c):
    """Turn a raw config dict (e.g. unsaved values from the Settings form) into resolved settings."""
    p = cfgmod.PRESETS.get(c.get('provider'))
    if not p: raise LLMError('Choose a provider first.')
    return {**cfgmod.DEFAULTS, **c, 'kind': p['kind'], 'label': p['label'], 'local': p['local'], 'source': 'form'}


# ------------------------------------------------------------------ http
def _req(url, headers=None, body=None, timeout=60, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ('POST' if data else 'GET'),
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'Reelsmith', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace')[:500]
        raise LLMError(f'{e.code} from {url}: {detail}') from e
    except urllib.error.URLError as e:
        raise LLMError(f'Could not reach {url}: {e.reason}.{cfgmod.connection_hint(url)}') from e
    except TimeoutError as e:
        raise LLMError(f'{url} did not answer within {timeout}s. Local models can be slow; raise the timeout in Settings.') from e


def _auth(s):
    h = dict(s.get('headers') or {})
    if s['kind'] == 'anthropic':
        if not s.get('api_key'): raise LLMError('Anthropic needs an API key.')
        h.update({'x-api-key': s['api_key'], 'anthropic-version': '2023-06-01'})
    elif s.get('api_key'):
        h['Authorization'] = 'Bearer ' + s['api_key']
    if s.get('provider') == 'openrouter':
        h.setdefault('X-Title', 'Reelsmith')
    return h


def _strip_reasoning(text):
    # reasoning models (DeepSeek-R1, QwQ, Qwen3 …) prepend their chain of thought
    return re.sub(r'<think>.*?</think>', '', text or '', flags=re.S | re.I).strip()


def complete(system, user, max_tokens=None, temperature=None, want_json=False, s=None):
    s = s or settings()
    if not s:
        raise LLMError('No LLM configured. Open Settings in the web app, or run `reelsmith config set --provider ollama`.')
    if s['kind'] == 'openai' and not s.get('model'):
        raise LLMError(f"Set a model name for {s['label']} (Settings → Model).")
    max_tokens = int(max_tokens or s.get('max_tokens') or 5000)
    temperature = float(s.get('temperature', 0.7) if temperature is None else temperature)
    base, timeout = s['base_url'].rstrip('/'), int(s.get('timeout') or 300)

    if s['kind'] == 'anthropic':
        data = _req(f'{base}/v1/messages', _auth(s), {'model': s['model'], 'max_tokens': max_tokens, 'temperature': temperature,
                    'system': system, 'messages': [{'role': 'user', 'content': user}]}, timeout)
        return _strip_reasoning(''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text'))

    msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if s['kind'] == 'ollama':
        body = {'model': s['model'], 'messages': msgs, 'stream': False,
                'options': {'temperature': temperature, 'num_ctx': int(s.get('num_ctx') or 16384), 'num_predict': max_tokens}}
        if want_json and s.get('json_mode', True): body['format'] = 'json'
        data = _req(f'{base}/api/chat', _auth(s), body, timeout)
        if data.get('error'): raise LLMError(f"Ollama: {data['error']}")
        return _strip_reasoning((data.get('message') or {}).get('content', ''))

    body = {'model': s['model'], 'messages': msgs, 'max_tokens': max_tokens, 'temperature': temperature}
    if want_json and s.get('json_mode', True):
        body['response_format'] = {'type': 'json_object'}
    return _openai_chat(s, base, body, timeout, want_json)


TRANSIENT = ('429', '500', '502', '503', '504', '408')
BACKOFF = (3, 8, 20, 45)        # seconds; ~75s in total before giving up on an overloaded or rate-limited provider
MAX_TOKENS_CAP = 32000


def _content_text(c):
    if isinstance(c, list):          # some providers return content parts
        return ''.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in c)
    return c or ''


def _openai_chat(s, base, body, timeout, want_json):
    """POST /chat/completions with the retries hosted routers need:
    - drop response_format when the server (or every OpenRouter provider) rejects it,
    - retry rate limits / upstream outages, including OpenRouter's errors delivered with HTTP 200,
    - when a reasoning model spends its output budget thinking, retry with a larger budget."""
    label = s.get('label') or base
    url = f'{base}/chat/completions'
    last = None
    waits, bumps = list(BACKOFF), 3
    for attempt in range(8):
        try:
            data = _req(url, _auth(s), body, timeout)
        except LLMError as e:
            code, text = str(e)[:3], str(e).lower()
            if 'response_format' in body and (code in ('400', '422', '500') or
                                              (code == '404' and ('parameter' in text or 'response_format' in text))):
                body.pop('response_format'); continue
            if code in TRANSIENT and waits:
                last = e; time.sleep(waits.pop(0)); continue
            if code in TRANSIENT: raise LLMError(str(e) + _busy_hint(s)) from e
            raise
        if isinstance(data, dict) and data.get('error'):
            err = data['error'] if isinstance(data['error'], dict) else {'message': str(data['error'])}
            prov = ((err.get('metadata') or {}).get('provider_name')) or data.get('provider')
            msg = err.get('message') or 'unknown error'
            raw = (err.get('metadata') or {}).get('raw')
            if raw: msg += f' ({str(raw)[:200]})'
            busy = str(err.get('code')) in TRANSIENT + ('None',)
            if busy and waits:
                last = LLMError(msg); time.sleep(waits.pop(0)); continue
            raise LLMError(f"{label} returned an error{' from ' + prov if prov else ''}: {msg}" + (_busy_hint(s) if busy else ''))
        try:
            choice = data['choices'][0]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f'Unexpected response from {base}: {str(data)[:300]}') from e
        m = choice.get('message') or {}
        content = _strip_reasoning(_content_text(m.get('content')))
        finish = choice.get('finish_reason') or choice.get('native_finish_reason')
        cut_short = finish == 'length' and (not content.strip() or (want_json and not _json_complete(content)))
        if cut_short:
            if body['max_tokens'] < MAX_TOKENS_CAP and bumps:
                bumps -= 1; body['max_tokens'] = min(MAX_TOKENS_CAP, body['max_tokens'] * 2); continue
            spent = ' It spent them reasoning.' if (m.get('reasoning') or m.get('reasoning_content')) else ''
            raise LLMError(f"{s.get('model')} ran out of output tokens ({body['max_tokens']}) before finishing its answer.{spent} "
                           f"Raise Max output tokens in Settings, or pick a model without extended reasoning.")
        if not content.strip() and (m.get('refusal')):
            raise LLMError(f"{s.get('model')} declined: {m['refusal']}")
        return content
    raise last or LLMError(f'{label} kept failing; try again in a minute.')


def _busy_hint(s):
    tail = (' On OpenRouter, a model served by several providers rarely hits this, because OpenRouter falls back to'
            ' another provider automatically; free and single-provider models are the ones that get overloaded.'
            if s.get('provider') == 'openrouter' else '')
    return (f' Still failing after {len(BACKOFF)} retries over about {sum(BACKOFF)}s, so the service is busy right now.'
            f' Use "Run again" on the job in a few minutes, or choose a different model.{tail}')


def _json_complete(text):
    try:
        extract_json(text); return True
    except Exception:
        t = re.sub(r'```(?:json)?', '', text).strip()
        try:
            json.loads(t); return True
        except Exception:
            return False


def extract_json(text):
    """First JSON object in a model reply. Tolerates fences, preambles and trailing commas."""
    t = re.sub(r'```(?:json)?', '', _strip_reasoning(text))
    start = t.find('{')
    if start < 0: raise LLMError('The model reply contained no JSON object.')
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"': in_str = True
        elif ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                blob = t[start:i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return json.loads(re.sub(r',\s*([}\]])', r'\1', blob))
    raise LLMError('The model reply had an unfinished JSON object. Raise "Max output tokens" in Settings.')


def complete_json(system, user, max_tokens=None, retries=1, s=None):
    last = None
    for attempt in range(retries + 1):
        msg = user if attempt == 0 else user + '\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object.'
        reply = complete(system, msg, max_tokens, want_json=True, s=s)
        try:
            return extract_json(reply)
        except (LLMError, json.JSONDecodeError) as e:
            last = e
    raise LLMError(f'Could not parse the model reply as JSON: {last}')


# ------------------------------------------------------------------ settings helpers
def list_models(s):
    base = s['base_url'].rstrip('/')
    if s['kind'] == 'ollama':
        data = _req(f'{base}/api/tags', _auth(s), timeout=15)
        return sorted(m.get('name') for m in data.get('models', []) if m.get('name'))
    if s['kind'] == 'anthropic':
        data = _req(f'{base}/v1/models', _auth(s), timeout=15)
        return [m.get('id') for m in data.get('data', []) if m.get('id')]
    data = _req(f'{base}/models', _auth(s), timeout=15)
    items = data.get('data', data.get('models', []))
    return sorted({(m.get('id') or m.get('name')) for m in items if isinstance(m, dict) and (m.get('id') or m.get('name'))})


def test(s):
    """Checks the endpoint answers and returns usable JSON. Returns a report dict; never raises."""
    report = {'ok': False, 'models': None, 'model_found': None, 'seconds': None, 'reply': None, 'error': None}
    try:
        report['models'] = list_models(s)[:200]
        if s.get('model'):
            report['model_found'] = s['model'] in report['models'] or any(m.split(':')[0] == s['model'] for m in report['models'])
    except LLMError as e:
        report['models_error'] = str(e)
    t0 = time.time()
    try:
        reply = complete('Reply with only JSON.', 'Reply with exactly {"ok": true}', max_tokens=50, temperature=0, want_json=True, s=s)
        report['reply'] = reply[:200]
        report['ok'] = extract_json(reply).get('ok') is True
        if not report['ok']: report['error'] = 'The model answered but not with the expected JSON. Larger models follow the storyboard format more reliably.'
    except (LLMError, json.JSONDecodeError) as e:
        report['error'] = str(e)
    report['seconds'] = round(time.time() - t0, 1)
    return report
