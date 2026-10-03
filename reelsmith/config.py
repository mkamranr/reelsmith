"""Persistent LLM settings.

Stored at $REELSMITH_CONFIG, or ~/.config/reelsmith/config.json, with owner-only permissions because it can hold
an API key. Settings saved here take precedence over environment variables; with no saved provider, the
environment variables documented in llm.py are used.
"""
import json
import os
import stat

PRESETS = {
    'ollama':     {'label': 'Ollama', 'kind': 'ollama', 'base_url': 'http://localhost:11434', 'model': 'llama3.1:8b',
                   'needs_key': False, 'local': True, 'num_ctx': 16384, 'max_source_chars': 9000, 'timeout': 600,
                   'help': 'Runs models on this machine. Install from ollama.com, then `ollama pull llama3.1:8b`.'},
    'vllm':       {'label': 'vLLM', 'kind': 'openai', 'base_url': 'http://localhost:8000/v1', 'model': '',
                   'needs_key': False, 'local': True, 'max_source_chars': 12000, 'timeout': 600,
                   'help': 'Point at a running `vllm serve <model>`. The model name must match what vLLM serves.'},
    'lmstudio':   {'label': 'LM Studio', 'kind': 'openai', 'base_url': 'http://localhost:1234/v1', 'model': '',
                   'needs_key': False, 'local': True, 'max_source_chars': 9000, 'timeout': 600,
                   'help': 'Start the local server in LM Studio (Developer tab) and load a model.'},
    'openai':     {'label': 'OpenAI', 'kind': 'openai', 'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini',
                   'needs_key': True, 'local': False, 'max_source_chars': 14000, 'timeout': 180,
                   'help': 'Uses your OpenAI API key.'},
    'openrouter': {'label': 'OpenRouter', 'kind': 'openai', 'base_url': 'https://openrouter.ai/api/v1', 'model': '',
                   'needs_key': True, 'local': False, 'max_source_chars': 14000, 'timeout': 180,
                   'help': 'One key for many hosted models. Model names look like `vendor/model`.'},
    'anthropic':  {'label': 'Anthropic', 'kind': 'anthropic', 'base_url': 'https://api.anthropic.com', 'model': 'claude-sonnet-5-5',
                   'needs_key': True, 'local': False, 'max_source_chars': 14000, 'timeout': 180,
                   'help': 'Uses your Anthropic API key.'},
    'custom':     {'label': 'Other OpenAI-compatible', 'kind': 'openai', 'base_url': 'http://localhost:8080/v1', 'model': '',
                   'needs_key': False, 'local': True, 'max_source_chars': 9000, 'timeout': 600,
                   'help': 'Any server exposing /v1/chat/completions: llama.cpp server, LocalAI, TGI, Jan, a company gateway…'},
}

# In a container, "localhost" is the container itself. REELSMITH_LOCAL_HOST (set by docker-compose to
# host.docker.internal) points the local presets (Ollama, vLLM, LM Studio, custom) at the machine running Docker.
_LOCAL = os.environ.get('REELSMITH_LOCAL_HOST', '').strip()
if _LOCAL:
    for _p in PRESETS.values():
        _p['base_url'] = _p['base_url'].replace('//localhost:', f'//{_LOCAL}:')
if os.environ.get('REELSMITH_OLLAMA_URL'):          # e.g. http://ollama:11434 for the bundled compose service
    PRESETS['ollama']['base_url'] = os.environ['REELSMITH_OLLAMA_URL'].rstrip('/')


DEFAULTS = {'provider': 'none', 'base_url': '', 'api_key': '', 'model': '', 'temperature': 0.7, 'max_tokens': 5000,
            'timeout': 300, 'json_mode': True, 'num_ctx': 16384, 'max_source_chars': 14000, 'headers': {}}


def path():
    return os.environ.get('REELSMITH_CONFIG') or os.path.join(os.path.expanduser('~'), '.config', 'reelsmith', 'config.json')


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(path()) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def normalize(new, old=None):
    """Validate a settings dict from the UI/CLI. A masked or empty key keeps the previously saved key."""
    old = old or load()
    cfg = dict(DEFAULTS); cfg.update(old)
    prov = str(new.get('provider', cfg['provider'])).strip()
    if prov not in PRESETS and prov != 'none':
        raise ValueError(f'Unknown provider "{prov}". Choose one of: none, {", ".join(PRESETS)}.')
    if prov != cfg['provider']:
        # a new provider starts from its own preset: never carry a URL, model or key across providers
        cfg['api_key'] = ''; cfg['base_url'] = ''; cfg['model'] = ''; cfg['headers'] = {}
        for k in ('timeout', 'num_ctx', 'max_source_chars'):
            cfg[k] = PRESETS.get(prov, {}).get(k, DEFAULTS[k])
    cfg['provider'] = prov
    for k in ('base_url', 'model'):
        if k in new: cfg[k] = str(new[k] or '').strip()
    if prov in PRESETS:
        p = PRESETS[prov]
        cfg['base_url'] = (cfg['base_url'] or p['base_url']).rstrip('/')
        if not cfg['model']: cfg['model'] = p['model']
        if not cfg['base_url'].startswith(('http://', 'https://')):
            raise ValueError('The endpoint URL must start with http:// or https://')
    key = new.get('api_key')
    if key is not None and not is_masked(str(key)):
        cfg['api_key'] = str(key).strip()
    for k, lo, hi, typ in (('temperature', 0.0, 2.0, float), ('max_tokens', 256, 32000, int), ('timeout', 10, 3600, int),
                           ('num_ctx', 2048, 262144, int), ('max_source_chars', 1000, 60000, int)):
        if k in new and new[k] not in (None, ''):
            try: cfg[k] = max(lo, min(hi, typ(new[k])))
            except (TypeError, ValueError): raise ValueError(f'{k} must be a number')
    if 'json_mode' in new: cfg['json_mode'] = bool(new['json_mode'])
    if isinstance(new.get('headers'), dict):
        prev = cfg.get('headers') or {}
        # a masked value coming back from the UI means "keep what is saved"
        cfg['headers'] = {str(k): (prev.get(k, '') if is_masked(str(v)) else str(v))
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


def mask(key):
    if not key: return ''
    return ('•' * 6) + key[-4:] if len(key) > 8 else '•' * 6


def is_masked(key):
    return key.startswith('•')


def public(cfg):
    """What the UI may see: everything except the raw key."""
    out = {k: v for k, v in cfg.items() if k != 'api_key'}
    out['api_key'] = mask(cfg.get('api_key', ''))
    # header values often carry credentials too (Authorization, X-Api-Key): show names, mask values
    out['headers'] = {k: mask(v) for k, v in (cfg.get('headers') or {}).items()}
    out['has_key'] = bool(cfg.get('api_key'))
    out['path'] = path()
    return out


# ------------------------------------------------------------------ container-aware connection hints
LOOPBACK = ('localhost', '127.0.0.1', '::1', '0.0.0.0')


def in_docker():
    return os.path.exists('/.dockerenv') or bool(os.environ.get('REELSMITH_IN_DOCKER'))


def connection_hint(url):
    """Extra advice for a failed connection to `url`. In a container, localhost is the container itself, which is
    the usual reason a model or TTS server that works in the browser can't be reached from Reelsmith."""
    import socket
    from urllib.parse import urlparse
    u = urlparse(url)
    host = (u.hostname or '').lower()
    if host not in LOOPBACK:
        return ''
    if not in_docker():
        return ' Is the server running?'
    port = u.port or (443 if u.scheme == 'https' else 80)
    alt = u._replace(netloc=f'host.docker.internal:{port}').geturl()
    alt_base = alt.split('/audio/')[0].split('/chat/')[0].split('/api/')[0].split('/models')[0].split('/v1/messages')[0]
    try:
        socket.create_connection(('host.docker.internal', port), timeout=2).close()
        reachable = True
    except OSError:
        reachable = False
    msg = (f' Reelsmith is running in a container, where "{host}" means the container itself, not your computer.')
    if reachable:
        return msg + f' Your server does answer at {alt_base} from here, so use that as the endpoint URL.'
    return (msg + f' Use {alt_base} instead, and make sure the server on your computer listens on all interfaces'
            f' (0.0.0.0), not only 127.0.0.1. Right now nothing answers there on port {port} either.')
