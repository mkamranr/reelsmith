"""Thumbnails for the template picker. One sample story, planned in each template's own structure, showing the
scene that defines it (a countdown item for Pop, a chapter for Editorial…). Rendered once and cached on disk."""
import os
import threading

from . import __version__
from .engine import templates as tpl

SAMPLE = {
    'name': 'Lumen', 'duration': 30, 'url': 'lumen.app', 'accent_source': 'template',
    'scenes': [
        {'type': 'hook', 'kicker': 'Still', 'big': 'guessing', 'punch': 'what users want?'},
        {'type': 'title', 'name': 'Lumen', 'tagline': 'Feedback you can act on.'},
        {'type': 'statement', 'text': 'Ship what matters.', 'accent': 'matters'},
        {'type': 'bullets', 'caption': 'Ship what matters', 'accent': 'matters', 'checks': True,
         'items': [{'title': 'Live feedback', 'sub': 'See reactions as they happen'},
                   {'title': 'Smart summaries', 'sub': 'Themes, not noise'},
                   {'title': 'One-click reports', 'sub': 'Share it with the team'}]},
        {'type': 'terminal', 'caption': 'Start here.', 'accent': 'here', 'command': 'npx lumen init'},
        {'type': 'cta', 'name': 'Lumen', 'url': 'lumen.app', 'line': 'Try it free', 'accent': 'free'},
    ],
}
SIGNATURE = {'demo': ('bullets', 0.9), 'story': ('chapter', 0.9), 'walkthrough': ('terminal', 0.92),
             'listicle': ('rank', 0.8), 'keynote': ('statement', 0.85), 'trailer': ('teaser', 0.97)}
_lock = threading.Lock()


def sample_for(tid):
    from .storyboard import sanitize, restructure
    inputs = {'template': tid, 'duration': SAMPLE['duration']}
    return restructure(sanitize(dict(SAMPLE), inputs), inputs)


def signature_time(sb, tid):
    from .engine.timeline import Timeline
    kind, frac = SIGNATURE[tpl.get(tid)['blueprint']]
    plan = Timeline(sb).plan_summary()
    p = next((x for x in plan if x['type'] == kind), plan[1] if len(plan) > 1 else plan[0])
    return p['start'] + p['duration'] * frac


def preview_path(out_root, tid):
    tid = tpl.resolve_id(tid)
    d = os.path.join(out_root, '_previews'); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{tid}-{__version__}.png')
    with _lock:
        if not os.path.exists(path):
            from .engine.render import render_still
            sb = sample_for(tid)
            tmp = path + '.tmp.png'
            render_still(sb, signature_time(sb, tid), tmp, scale=0.25)
            os.replace(tmp, path)
    return path
