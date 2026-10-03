"""Thumbnails for the template picker: one sample storyboard rendered in every template, cached on disk."""
import os
import threading

from . import __version__
from .engine import templates as tpl

SAMPLE = {
    'name': 'Lumen', 'duration': 12, 'accent_source': 'template',
    'scenes': [
        {'type': 'hook', 'kicker': 'Still', 'big': 'guessing', 'punch': 'what users want?'},
        {'type': 'bullets', 'caption': 'Ship what matters', 'accent': 'matters', 'checks': True,
         'items': [{'title': 'Live feedback', 'sub': 'See reactions as they happen'},
                   {'title': 'Smart summaries', 'sub': 'Themes, not noise'},
                   {'title': 'One-click reports', 'sub': 'Share it with the team'}]},
        {'type': 'cta', 'name': 'Lumen', 'url': 'lumen.app', 'line': 'Try it free', 'accent': 'free'},
    ],
}
_lock = threading.Lock()


def preview_path(out_root, tid):
    tid = tpl.resolve_id(tid)
    d = os.path.join(out_root, '_previews'); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{tid}-{__version__}.png')
    with _lock:
        if not os.path.exists(path):
            from .engine.render import render_still
            from .engine.timeline import Timeline
            sb = {**SAMPLE, 'template': tid}
            p = next(x for x in Timeline(sb).plan_summary() if x['type'] == 'bullets')
            tmp = path + '.tmp.png'
            render_still(sb, p['start'] + p['duration'] * 0.9, tmp, scale=0.25)
            os.replace(tmp, path)
    return path
