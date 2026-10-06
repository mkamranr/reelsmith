"""Reads a URL into {kind, title, url, facts, text}.

GitHub and Hugging Face get first-class treatment (README/model card + the stats worth a slide).
Anything else is fetched as HTML and reduced to readable text.

This runs inside a local server, so a URL fetcher can be aimed at the machine's own network.
Hosts that resolve to private, loopback or link-local addresses are refused unless
REELSMITH_ALLOW_PRIVATE=1 is set.
"""
import ipaddress
import json
import os
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = 'Mozilla/5.0 (Reelsmith; +https://github.com/) Python-urllib'
MAX_BYTES = 3_000_000
MAX_TEXT = 14_000


class SourceError(Exception):
    pass


def _guard(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise SourceError(f'Only http(s) URLs are supported: {url}')
    if os.environ.get('REELSMITH_ALLOW_PRIVATE') == '1':
        return
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror:
        raise SourceError(f'Could not resolve host: {u.hostname}')
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise SourceError(f'Refusing to fetch {u.hostname}: it resolves to a private address ({ip}).')


def _get(url, headers=None, as_json=False):
    _guard(url)
    req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        final = r.geturl()
        if final != url: _guard(final)
        data = r.read(MAX_BYTES)
        charset = r.headers.get_content_charset() or 'utf-8'
    body = data.decode(charset, errors='replace')
    return json.loads(body) if as_json else body


def _clean_md(md):
    md = re.sub(r'<!--.*?-->', '', md, flags=re.S)
    md = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md)                 # images
    md = re.sub(r'<img[^>]*>', '', md, flags=re.I)
    md = re.sub(r'\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)', '', md)     # badges
    md = re.sub(r'<[^>]+>', '', md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip()[:MAX_TEXT]


def github(owner, repo):
    h = {'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'): h['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    meta, readme, note = {}, '', None
    try:
        meta = _get(f'https://api.github.com/repos/{owner}/{repo}', h, as_json=True)
        readme = _get(f'https://api.github.com/repos/{owner}/{repo}/readme', {**h, 'Accept': 'application/vnd.github.raw'})
    except Exception as e:
        # Anonymous API calls are limited to 60/hour per IP. Fall back to the raw README so the
        # video can still be made; stars/forks/licence are simply left out rather than guessed.
        note = f'GitHub API unavailable ({e}); set GITHUB_TOKEN for repo stats.'
        for branch in ('HEAD', 'main', 'master'):
            try:
                readme = _get(f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md'); break
            except Exception:
                continue
        if not readme:
            raise SourceError(f'Could not read github.com/{owner}/{repo}: {e}')
    lic = (meta.get('license') or {}).get('spdx_id')
    facts = {k: v for k, v in {
        'stars': meta.get('stargazers_count'), 'forks': meta.get('forks_count'), 'language': meta.get('language'),
        'license': None if lic in (None, 'NOASSERTION') else lic, 'topics': meta.get('topics') or None,
        'homepage': meta.get('homepage') or None, 'description': meta.get('description')}.items() if v not in (None, '', [])}
    out = {'kind': 'github', 'title': meta.get('name') or repo, 'url': f'github.com/{owner}/{repo}',
           'facts': facts, 'text': _clean_md(readme)}
    try:                                    # README media, found before the text is cleaned of images
        from .spotlight_assets import media_from_markdown
        out['media'] = media_from_markdown(readme, f'github.com/{owner}/{repo}')
    except Exception:
        out['media'] = []
    if note: out['note'] = note
    return out


def huggingface(repo_id, kind='models'):
    meta = _get(f'https://huggingface.co/api/{kind}/{repo_id}', as_json=True)
    prefix = '' if kind == 'models' else f'{kind}/'
    try:
        card = _get(f'https://huggingface.co/{prefix}{repo_id}/raw/main/README.md')
        card = re.sub(r'^---.*?---', '', card, flags=re.S)
    except Exception:
        card = ''
    cd = meta.get('cardData') or {}
    facts = {k: v for k, v in {
        'downloads': meta.get('downloads'), 'likes': meta.get('likes'), 'task': meta.get('pipeline_tag'),
        'license': cd.get('license'), 'base_model': cd.get('base_model'), 'library': meta.get('library_name')}.items() if v not in (None, '', [])}
    return {'kind': 'huggingface', 'title': repo_id.split('/')[-1], 'url': f'huggingface.co/{prefix}{repo_id}',
            'facts': facts, 'text': _clean_md(card)}


class _Text(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header', 'form', 'aside'}
    BLOCK = {'p', 'h1', 'h2', 'h3', 'h4', 'li', 'blockquote', 'pre', 'td', 'dd', 'dt', 'div', 'section', 'article', 'br'}

    def __init__(self):
        super().__init__(); self.out = []; self.skip = 0; self.title = ''; self.meta = {}; self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP: self.skip += 1
        if tag == 'title': self._in_title = True
        if tag == 'meta':
            k = (a.get('name') or a.get('property') or '').lower()
            if k in ('description', 'og:title', 'og:description', 'og:site_name'): self.meta[k] = a.get('content', '')
        if tag in self.BLOCK: self.out.append('\n')
        if tag in ('h1', 'h2', 'h3') and not self.skip: self.out.append('## ')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == 'title': self._in_title = False

    def handle_data(self, d):
        if self._in_title: self.title += d
        elif not self.skip: self.out.append(d)


def webpage(url):
    html = _get(url)
    p = _Text(); p.feed(html)
    text = re.sub(r'[ \t\r\f\v]+', ' ', ''.join(p.out))
    text = re.sub(r'\n\s*\n+', '\n\n', text).strip()
    host = urllib.parse.urlparse(url).hostname or ''
    title = p.meta.get('og:title') or p.title.strip() or host
    facts = {k: v for k, v in {'site': p.meta.get('og:site_name') or host,
                               'description': p.meta.get('og:description') or p.meta.get('description')}.items() if v}
    return {'kind': 'web', 'title': title[:120], 'url': re.sub(r'^https?://(www\.)?', '', url).rstrip('/'),
            'facts': facts, 'text': text[:MAX_TEXT]}


def fetch_source(url):
    url = url.strip()
    if not re.match(r'^https?://', url): url = 'https://' + url
    u = urllib.parse.urlparse(url)
    host = (u.hostname or '').lower().removeprefix('www.')
    parts = [x for x in u.path.split('/') if x]
    try:
        if host == 'github.com' and len(parts) >= 2:
            return github(parts[0], parts[1].removesuffix('.git'))
        if host == 'huggingface.co' and parts:
            if parts[0] in ('datasets', 'spaces') and len(parts) >= 3:
                return huggingface(f'{parts[1]}/{parts[2]}', parts[0])
            if len(parts) >= 2:
                return huggingface(f'{parts[0]}/{parts[1]}')
        return webpage(url)
    except SourceError:
        raise
    except Exception as e:
        raise SourceError(f'Could not read {url}: {e}') from e
