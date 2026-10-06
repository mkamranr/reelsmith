"""Footage for the Spotlight template (a screen-recorded repo explainer).

capture_desktop()  the page in desktop layout inside a browser, plus where its interesting parts are ("anchors": the
                   README's logo, title, description, headings, lists, code, images) so the camera can move between
                   them, plus the README's media (images, GIFs, videos).
media_from_markdown()  the same media found in README Markdown, for when no browser is available.
download_media()   fetch media (size-capped, private addresses refused) and turn GIFs and videos into a few seconds
                   of frames that play inside the browser window.
"""
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

DESK_W, DESK_SCALE = 1100, 1.5          # css px viewport width; device scale → 1650 px wide screenshots
MAX_BYTES = 30_000_000
SKIP = re.compile(r'shields\.io|badge|badgen|img\.shields|/actions/workflows/|codecov|travis-ci|\.svg(\?|$)', re.I)

ANCHOR_JS = r"""(start) => {
  const root = document.querySelector('article.markdown-body') || document.querySelector('#readme') || document.querySelector('main') || document.body;
  const out = []; const S = %s;
  const add = (kind, el) => { const r = el.getBoundingClientRect(); if (r.height < 12 || r.width < 40) return;
    out.push({kind, x: r.left * S, y: (r.top + window.scrollY - start) * S, w: r.width * S, h: r.height * S}); };
  const rr = root.getBoundingClientRect(); out.push({kind: 'readme', x: rr.left * S, y: (rr.top + window.scrollY - start) * S, w: rr.width * S, h: Math.min(rr.height, 900) * S});
  root.querySelectorAll('img').forEach((el, i) => { if (i < 8 && el.naturalWidth > 120) add('image', el); });
  root.querySelectorAll('video').forEach((el, i) => { if (i < 4) add('video', el); });
  root.querySelectorAll('h1, h2, h3').forEach((el, i) => { if (i < 10) add('heading', el); });
  root.querySelectorAll(':scope > p').forEach((el, i) => { if (i < 6) add('paragraph', el); });
  root.querySelectorAll(':scope > ul, :scope > ol').forEach((el, i) => { if (i < 4) add('list', el); });
  root.querySelectorAll('pre').forEach((el, i) => { if (i < 3) add('code', el); });
  const media = [];
  root.querySelectorAll('img').forEach(el => { if (el.naturalWidth > 160 && el.naturalHeight > 90) media.push({url: el.currentSrc || el.src, kind: 'image', w: el.naturalWidth, h: el.naturalHeight, alt: el.alt || ''}); });
  root.querySelectorAll('video').forEach(el => { const s = el.currentSrc || el.src || (el.querySelector('source') || {}).src; if (s) media.push({url: s, kind: 'video', w: el.videoWidth || 0, h: el.videoHeight || 0, alt: ''}); });
  return {anchors: out, media, title: document.title};
}"""


class AssetError(Exception):
    pass


def capture_desktop(url, out_png, dark=False, max_height=6000, timeout=45):
    """Desktop-layout screenshot from the repository header down, with anchors and README media."""
    from .capture import CaptureError, _private, START, HIDE_CSS
    from .sources import _guard, SourceError
    try:
        _guard(url)
    except SourceError as e:
        raise CaptureError(str(e)) from e
    from playwright.sync_api import sync_playwright
    allow_private = os.environ.get('REELSMITH_ALLOW_PRIVATE') == '1'
    cache = {}

    def route(r):
        if r.request.url.startswith(('data:', 'blob:')): return r.continue_()
        h = urllib.parse.urlparse(r.request.url).hostname or ''
        if not allow_private:
            if h not in cache: cache[h] = _private(h)
            if cache[h]: return r.abort()
        return r.continue_()

    with sync_playwright() as p:
        args = ['--no-sandbox', '--disable-dev-shm-usage'] if os.path.exists('/.dockerenv') or (hasattr(os, 'geteuid') and os.geteuid() == 0) else []
        b = p.chromium.launch(executable_path=os.environ.get('REELSMITH_CHROMIUM') or None, args=args)
        try:
            ctx = b.new_context(viewport={'width': DESK_W, 'height': 900}, device_scale_factor=DESK_SCALE,
                                color_scheme='dark' if dark else 'light', locale='en-US', bypass_csp=True)
            page = ctx.new_page(); page.route('**/*', route)
            page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
            try: page.wait_for_load_state('networkidle', timeout=8000)
            except Exception: pass
            try: page.add_style_tag(content=HIDE_CSS)
            except Exception: pass
            page.wait_for_timeout(600)
            host = (urllib.parse.urlparse(url).hostname or '').removeprefix('www.')
            start = 0
            for sel in START.get(host, []):
                y = page.evaluate("s => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().top + window.scrollY : null }", sel)
                if y is not None: start = max(0, int(y) - 8); break
            info = page.evaluate(ANCHOR_JS % DESK_SCALE, start)
            total = page.evaluate('document.documentElement.scrollHeight')
            h = max(600, min(max_height, total - start))
            page.screenshot(path=out_png, full_page=True, clip={'x': 0, 'y': start, 'width': DESK_W, 'height': h})
        except CaptureError:
            raise
        except Exception as e:
            raise CaptureError(f'Could not capture {url}: {str(e).splitlines()[0]}') from e
        finally:
            b.close()
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(out_png) as im: w, hh = im.size
    anchors = [a for a in info.get('anchors', []) if 0 <= a['y'] < hh - 40]
    return {'path': out_png, 'width': w, 'height': hh, 'kind': 'desktop', 'anchors': anchors,
            'media': [m for m in info.get('media', []) if m.get('url') and not SKIP.search(m['url'])], 'title': info.get('title', '')}


def media_from_markdown(md, repo_url):
    """Image/GIF/video links in README Markdown, made absolute (GitHub relative paths → raw.githubusercontent.com)."""
    owner_repo = re.match(r'(?:https?://)?github\.com/([^/]+/[^/#?]+)', repo_url or '')
    out = []
    links = re.findall(r'!\[([^\]]*)\]\(([^)\s]+)', md or '') + [('', u) for u in re.findall(r'<img[^>]+src="([^"]+)"', md or '', re.I)]
    links += [('', u) for u in re.findall(r'(https://github\.com/user-attachments/assets/[0-9a-f-]{20,})', md or '')]
    links += [('', u) for u in re.findall(r'<video[^>]+src="([^"]+)"', md or '', re.I)]
    for alt, u in links:
        u = u.strip()
        if not u or SKIP.search(u): continue
        if not re.match(r'^https?://', u):
            if not owner_repo: continue
            u = f'https://raw.githubusercontent.com/{owner_repo.group(1).removesuffix(".git")}/HEAD/' + u.lstrip('./')
        kind = 'video' if re.search(r'\.(mp4|mov|webm)(\?|$)|user-attachments/assets', u, re.I) else 'image'
        if not any(m['url'] == u for m in out): out.append({'url': u, 'kind': kind, 'w': 0, 'h': 0, 'alt': alt})
    return out[:8]


def _fetch(url, path):
    from .sources import _guard, UA
    _guard(url)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        final = r.geturl()
        if final != url: _guard(final)
        ctype = r.headers.get('Content-Type', '')
        n = 0
        with open(path, 'wb') as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk: break
                n += len(chunk)
                if n > MAX_BYTES: raise AssetError('file too large')
                f.write(chunk)
    return ctype


LOGO = re.compile(r'logo|icon|banner|header|avatar|favicon|wordmark|badge', re.I)


def rank_media(items):
    """Demos first (videos, GIFs), then large images; logos, icons and wide banners are not demos."""
    def score(m):
        u = (m.get('url') or '').lower(); alt = (m.get('alt') or '').lower()
        if LOGO.search(u.rsplit('/', 1)[-1]) or LOGO.search(alt): return -1
        w, h = m.get('w') or 0, m.get('h') or 0
        if w and h and (w / h > 3.2 or h < 140): return -1
        if m.get('kind') == 'video' or u.endswith(('.mp4', '.mov', '.webm')) or 'user-attachments/assets' in u: return 3
        if u.split('?')[0].endswith('.gif'): return 2
        return 1
    ranked = sorted(((score(m), i, m) for i, m in enumerate(items)), key=lambda x: (-x[0], x[1]))
    return [m for sc, _, m in ranked if sc > 0]


def download_media(items, out_dir, limit=4, seconds=8.0, fps=15, log=print):
    """Download up to `limit` usable media items. Returns [{'name', 'kind': 'image'|'frames', 'file'|'dir', 'n', 'fps', 'w', 'h'}]."""
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    assets = []
    for i, m in enumerate(items):
        if len(assets) >= limit: break
        pre = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(m['url']).path))[:60]
        if pre and any(a['name'] == pre for a in assets): continue
        raw = os.path.join(out_dir, f'raw{i}')
        try:
            ctype = _fetch(m['url'], raw)
        except Exception as e:
            log(f'  note: skipped a README image ({str(e)[:80]}).'); continue
        name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(m['url']).path))[:60] or f'media-{i}'
        if any(a['name'] == name for a in assets):           # same file linked twice (page vs Markdown address)
            try: os.remove(raw)
            except OSError: pass
            continue
        is_vid = m['kind'] == 'video' or 'video' in ctype or name.lower().endswith(('.mp4', '.mov', '.webm'))
        is_gif = 'gif' in ctype or name.lower().endswith('.gif')
        try:
            if is_vid or is_gif:
                d = os.path.join(out_dir, f'm{i}'); os.makedirs(d, exist_ok=True)
                r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', raw, '-t', str(seconds),
                                    '-vf', f'fps={fps},scale=1100:-2:flags=lanczos', '-q:v', '4', os.path.join(d, '%04d.jpg')],
                                   capture_output=True, timeout=120)
                frames = sorted(f for f in os.listdir(d) if f.endswith('.jpg'))
                if r.returncode != 0 or len(frames) < 2: raise AssetError((r.stderr or b'no frames').decode(errors='replace')[-120:])
                with Image.open(os.path.join(d, frames[0])) as im: w, h = im.size
                assets.append({'name': name, 'kind': 'frames', 'dir': os.path.basename(d), 'n': len(frames), 'fps': fps, 'w': w, 'h': h})
            else:
                with Image.open(raw) as im:
                    im = im.convert('RGB')
                    if im.width < 200 or im.height < 120: raise AssetError('too small')
                    im.thumbnail((1600, 1600))
                    f = os.path.join(out_dir, f'm{i}.jpg'); im.save(f, quality=90)
                    assets.append({'name': name, 'kind': 'image', 'file': os.path.basename(f), 'w': im.width, 'h': im.height})
        except Exception as e:
            log(f'  note: skipped {name} ({str(e)[:80]}).')
        finally:
            try: os.remove(raw)
            except OSError: pass
    return assets
