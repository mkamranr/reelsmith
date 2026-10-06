"""Screenshots for the scroll-through scene.

capture()      a real screenshot of the page in a headless browser (Playwright + Chromium), in phone layout so it
               fits a vertical video. Dark templates get the site's dark mode. Requests to private addresses are
               blocked, like the link reader.
readme_page()  no browser available: the README is drawn as a GitHub-style page instead, so the scroll-through still
               works (it says "README" rather than pretending to be a screenshot).
page_image()   tries the first, falls back to the second.

Browser lookup: REELSMITH_CHROMIUM (path to a Chrome/Chromium binary), else Playwright's own Chromium
(`playwright install chromium`).
"""
import ipaddress
import os
import re
import socket
import urllib.parse

MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
             'Version/17.0 Mobile/15E148 Safari/604.1')
# where the interesting part of a page starts, per site (skips global navigation)
START = {'github.com': ['#repository-container-header', 'main'], 'huggingface.co': ['main', 'section']}
# where the README itself starts: above it the video moves briskly, through it slowly
README_SEL = {'github.com': ['article.markdown-body', '#readme', '[data-testid="readme"]'], 'huggingface.co': ['.model-card-content', '.prose']}
SCALE = 2.0      # 430 css px → 860 px wide: sharp in the phone frame, half the memory of 2.5× for long pages
# banners and prompts that would sit on top of the content
HIDE_CSS = """
[id*="cookie" i], [class*="cookie" i], [aria-label*="cookie" i], .js-header-wrapper, header.HeaderMktg,
.signup-prompt, .js-notice, [data-testid="banner"], .flash-full, footer, .footer { display: none !important; }
"""
_browser_ok = None


class CaptureError(Exception):
    pass


def _private(host):
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
    except socket.gaierror:
        return True
    return False


def browser_available():
    """True if Playwright is installed and a Chromium can be found. Cached."""
    global _browser_ok
    if _browser_ok is not None: return _browser_ok
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = os.environ.get('REELSMITH_CHROMIUM') or p.chromium.executable_path
            _browser_ok = bool(exe and os.path.exists(exe))
    except Exception:
        _browser_ok = False
    return _browser_ok


def capture(url, out_png, dark=False, max_height=7000, timeout=45):
    """Screenshot `url` in phone layout, long enough for the whole README of most repos.
    Returns {'path', 'width', 'height', 'kind': 'screenshot', 'focus_y'} where focus_y is where the README starts in the
    image (the scroll moves briskly above it and slowly through it)."""
    from .sources import _guard, SourceError
    try:
        _guard(url)
    except SourceError as e:
        raise CaptureError(str(e)) from e
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise CaptureError('Playwright is not installed (pip install playwright && playwright install chromium).') from e
    allow_private = os.environ.get('REELSMITH_ALLOW_PRIVATE') == '1'
    host_cache = {}

    def route(r):
        h = urllib.parse.urlparse(r.request.url).hostname or ''
        if r.request.url.startswith(('data:', 'blob:')): return r.continue_()
        if not allow_private:
            if h not in host_cache: host_cache[h] = _private(h)
            if host_cache[h]: return r.abort()
        return r.continue_()

    with sync_playwright() as p:
        exe = os.environ.get('REELSMITH_CHROMIUM') or None
        args = ['--no-sandbox', '--disable-dev-shm-usage'] if (os.geteuid() == 0 if hasattr(os, 'geteuid') else False) or os.path.exists('/.dockerenv') else []
        try:
            b = p.chromium.launch(executable_path=exe, args=args)
        except Exception as e:
            raise CaptureError(f'Could not start a browser: {str(e).splitlines()[0]}') from e
        try:
            ctx = b.new_context(viewport={'width': 430, 'height': 932}, device_scale_factor=SCALE, is_mobile=True,
                                has_touch=True, user_agent=MOBILE_UA, color_scheme='dark' if dark else 'light',
                                locale='en-US', bypass_csp=True)   # our banner-hiding CSS must apply
            page = ctx.new_page()
            page.route('**/*', route)
            page.goto(url, wait_until='domcontentloaded', timeout=timeout * 1000)
            try: page.wait_for_load_state('networkidle', timeout=8000)
            except Exception: pass
            try: page.add_style_tag(content=HIDE_CSS)
            except Exception: pass                              # nice-to-have; never fail a capture over it
            page.wait_for_timeout(700)
            host = (urllib.parse.urlparse(url).hostname or '').removeprefix('www.')
            start = 0
            for sel in START.get(host, []):
                y = page.evaluate("s => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().top + window.scrollY : null }", sel)
                if y is not None: start = max(0, int(y) - 8); break
            focus = None
            for sel in README_SEL.get(host, []):
                y = page.evaluate("s => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().top + window.scrollY : null }", sel)
                if y is not None: focus = max(0, int(y) - start); break
            width = page.evaluate('document.documentElement.clientWidth') or 430
            total = page.evaluate('document.documentElement.scrollHeight')
            h = max(400, min(max_height, total - start))
            page.screenshot(path=out_png, full_page=True, clip={'x': 0, 'y': start, 'width': width, 'height': h})
        except CaptureError:
            raise
        except Exception as e:
            raise CaptureError(f'Could not capture {url}: {str(e).splitlines()[0]}') from e
        finally:
            b.close()
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(out_png) as im: w, hh = im.size
    fy = int((focus or 0) * SCALE)
    return {'path': out_png, 'width': w, 'height': hh, 'kind': 'screenshot', 'focus_y': fy if fy < hh - 400 else 0}


# ------------------------------------------------------------------ fallback: draw the README as a page
def readme_page(md, title, url, facts, out_png, dark=False, width=1080, max_height=16000):
    import skia
    from .engine.lib import font_file
    bg, fg, mu, line, codebg, link = ((13, 17, 23), (230, 237, 243), (139, 148, 158), (48, 54, 61), (22, 27, 34), (68, 147, 248)) if dark \
        else ((255, 255, 255), (31, 35, 40), (89, 99, 110), (209, 217, 224), (246, 248, 250), (9, 105, 218))
    def F(w, s, mono=False):
        ft = skia.Font(skia.Typeface.MakeFromFile(font_file(w, mono)), s); ft.setSubpixel(True); ft.setEdging(skia.Font.Edging.kAntiAlias); return ft
    def C(c, a=1.0): return skia.Color(*[int(v) for v in c], int(a * 255))
    pad = 48; inner = width - 2 * pad
    ops = []; y = 0

    def wrap(text, f, w):
        out, cur = [], ''
        for word in text.split():
            t = (cur + ' ' + word).strip()
            if f.measureText(t) <= w or not cur: cur = t
            else: out.append(cur); cur = word
        return out + ([cur] if cur else [])

    # header like a repo page
    y += 40
    ops.append(('text', pad, y + 34, (url or title)[:48], F(500, 30), mu)); y += 70
    ops.append(('text', pad, y + 52, title[:30], F(700, 56), fg)); y += 90
    chips = [f'★ {facts["stars"]}' if facts.get('stars') is not None else None, facts.get('language'), facts.get('license')]
    x = pad
    for ch in [c for c in chips if c]:
        f = F(600, 26); w = f.measureText(str(ch)) + 36
        ops.append(('pill', x, y, w, 50, str(ch), f)); x += w + 12
    y += 80 if any(chips) else 10
    ops.append(('rule', y)); y += 40
    text = re.sub(r'<!--.*?-->', '', md or '', flags=re.S)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text); text = re.sub(r'<[^>]+>', '', text)
    # markdown → blocks (soft-wrapped lines joined into paragraphs, list items keep their continuation lines)
    blocks, para, item, in_code, code = [], [], None, False, []
    def flush():
        nonlocal para, item
        if para: blocks.append(('p', ' '.join(para))); para = []
        if item is not None: blocks.append(('li', item)); item = None
    for raw in text.split('\n'):
        if raw.strip().startswith('```'):
            if in_code: blocks.append(('code', code[:18])); code = []
            else: flush()
            in_code = not in_code; continue
        if in_code: code.append(raw.rstrip()[:60]); continue
        st = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', raw).replace('**', '').replace('`', '').strip()
        if not st: flush(); continue
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', st): flush(); blocks.append(('rule',)); continue
        m = re.match(r'^(#{1,6})\s+(.*)', st)
        if m: flush(); blocks.append(('h', len(m.group(1)), m.group(2))); continue
        m = re.match(r'^([-*+]|\d+\.)\s+(.*)', st)
        if m: flush(); item = m.group(2); continue
        if st.startswith('|'):
            flush()
            if not re.match(r'^\|[\s:|-]+\|?$', st): blocks.append(('table', st))
            continue
        if item is not None: item += ' ' + st
        else: para.append(st)
    flush()
    anchors = []
    for bl in blocks:
        if y > max_height: break
        k = bl[0]
        y_start = y
        if k == 'h':
            lvl, size = bl[1], {1: 54, 2: 44, 3: 36}.get(bl[1], 32); f = F(700, size)
            y += 26
            for ln in wrap(bl[2], f, inner): ops.append(('text', pad, y + size, ln, f, fg)); y += size * 1.3
            if lvl <= 2: ops.append(('rule', y + 6)); y += 22
            y += 10
            anchors.append({'kind': 'heading', 'x': pad, 'y': y_start, 'w': inner, 'h': y - y_start})
        elif k == 'p':
            f = F(400, 32)
            for ln in wrap(bl[1], f, inner): ops.append(('text', pad, y + 32, ln, f, fg)); y += 46
            y += 22
            anchors.append({'kind': 'paragraph', 'x': pad, 'y': y_start, 'w': inner, 'h': y - y_start})
        elif k == 'li':
            f = F(400, 32); ops.append(('dot', pad + 10, y + 22))
            if not anchors or anchors[-1]['kind'] != 'list': anchors.append({'kind': 'list', 'x': pad, 'y': y_start, 'w': inner, 'h': 300})
            for ln in wrap(bl[1], f, inner - 40): ops.append(('text', pad + 40, y + 32, ln, f, fg)); y += 46
            y += 10
        elif k == 'code':
            f = F(500, 26, True); h = 36 * len(bl[1]) + 40
            ops.append(('code', y, h, bl[1], f)); y += h + 28
            anchors.append({'kind': 'code', 'x': pad, 'y': y_start, 'w': inner, 'h': h})
        elif k == 'rule':
            ops.append(('rule', y + 10)); y += 40
        elif k == 'table':
            ops.append(('text', pad, y + 28, ' '.join(c.strip() for c in bl[1].strip('|').split('|'))[:64], F(400, 24, True), mu)); y += 38
    height = int(min(max_height, y + 60))
    surf = skia.Surface(width, height); c = surf.getCanvas(); c.clear(C(bg))
    for op in ops:
        k = op[0]
        if k == 'text': c.drawString(op[3], op[1], op[2], op[4], skia.Paint(AntiAlias=True, Color=C(op[5])))
        elif k == 'rule': c.drawRect(skia.Rect.MakeXYWH(pad, op[1], inner, 2), skia.Paint(Color=C(line)))
        elif k == 'dot': c.drawCircle(op[1], op[2], 5, skia.Paint(AntiAlias=True, Color=C(fg)))
        elif k == 'pill':
            _, x0, y0, w, h, label, f = op
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x0, y0, w, h), h / 2, h / 2), skia.Paint(AntiAlias=True, Color=C(codebg)))
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x0, y0, w, h), h / 2, h / 2), skia.Paint(AntiAlias=True, Color=C(line), Style=skia.Paint.kStroke_Style, StrokeWidth=2))
            c.drawString(label, x0 + 18, y0 + 34, f, skia.Paint(AntiAlias=True, Color=C(fg)))
        elif k == 'code':
            _, y0, h, lines, f = op
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(pad, y0, inner, h), 14, 14), skia.Paint(AntiAlias=True, Color=C(codebg)))
            for i, ln in enumerate(lines): c.drawString(ln, pad + 24, y0 + 44 + i * 36, f, skia.Paint(AntiAlias=True, Color=C(fg)))
    surf.makeImageSnapshot().save(out_png, skia.kPNG)
    anchors = [a for a in anchors if a['y'] < height - 200]
    return {'path': out_png, 'width': width, 'height': height, 'kind': 'readme', 'focus_y': 0, 'anchors': anchors}


def page_image(url, source, out_png, dark=False, log=print):
    """Screenshot when a browser is available, else the README drawn as a page. Returns info dict or None."""
    if url and browser_available():
        try:
            return capture(url if re.match(r'^https?://', url) else 'https://' + url, out_png, dark=dark)
        except Exception as e:                       # any failure (not just capture errors) falls back to the README
            log(f'  note: screenshot failed ({str(e).splitlines()[0] if str(e) else type(e).__name__}); drawing the README instead.')
    elif url:
        log('  note: no headless browser found (pip install playwright && playwright install chromium); drawing the README instead.')
    if source and source.get('text'):
        return readme_page(source['text'], source.get('title') or '', source.get('url') or url or '', source.get('facts') or {}, out_png, dark=dark)
    return None


def screenshot_support():
    """('browser', detail) when a headless Chromium can be launched, else ('readme', why). Used at startup."""
    try:
        import PIL  # noqa: F401  (the screenshot step reads image sizes with Pillow)
    except ImportError:
        return 'readme', 'Pillow is not installed (pip install Pillow)'
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 'readme', 'Playwright is not installed (pip install "reelsmith[screenshots]" && playwright install chromium)'
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=os.environ.get('REELSMITH_CHROMIUM') or None,
                                  args=['--no-sandbox', '--disable-dev-shm-usage'] if os.path.exists('/.dockerenv') else [])
            v = b.version; b.close()
        return 'browser', f'Chromium {v} ready'
    except Exception as e:
        return 'readme', f'Chromium could not start: {str(e).splitlines()[0][:120]}'
