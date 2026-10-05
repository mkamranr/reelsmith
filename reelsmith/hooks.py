"""The first two seconds.

Short-form feeds test a video on a small audience first; if that audience scrolls away in the first seconds, it stops
there. Most of that audience watches the first second muted, so the hook has to work as on-screen text alone.

write_hooks() asks the model for several candidates in proven patterns, has it score each against a rubric, and
returns them best first. The best becomes the cold open (on screen from frame 0); the rest are kept as alternatives
you can swap in and test against each other.
"""
import re

from . import llm

PATTERNS = {
    'problem': 'Call out the pain the viewer has right now ("Still writing READMEs by hand?").',
    'result': 'Show the end result first ("One command. A finished Reel.").',
    'curiosity': 'Open a loop the video closes ("The one flag that halves your build time").',
    'contrarian': 'Challenge a habit ("Stop designing carousels in Figma").',
    'number': 'Promise a specific, countable payoff ("3 repos that replace your design tool").',
    'callout': 'Name who it is for ("If you ship side projects, steal this").',
}

SYSTEM = """You write the first two seconds of short vertical videos (Reels, Shorts, TikTok). A new video is shown to a
small test audience first; if they scroll away in the first 2-3 seconds it is never shown to more people. Most of
them watch the first second with the sound off, so the hook must work as on-screen text alone.

A great hook:
- is readable in under 2 seconds: at most 9 words and 50 characters;
- makes the topic obvious instantly, using the words this niche searches for;
- is specific (a real number, tool, result or pain from the material), never vague;
- creates a reason to keep watching (a gap, a promise, a challenge), and the video can pay it off;
- never lies or overpromises: every claim must be supported by the material.
Never start with filler ("Hey guys", "In this video", "Introducing", "Did you know", "Meet"). No emoji, no hashtags.

Reply with ONLY JSON:
{"hooks": [{"text": "...", "accent": "the 1-2 words to highlight", "pattern": "problem|result|curiosity|contrarian|number|callout",
            "clarity": 1-10, "curiosity": 1-10, "specificity": 1-10, "fit": 1-10}, ...]}
Score honestly: clarity = understood instantly on mute; curiosity = reason to keep watching; specificity = concrete
detail; fit = speaks to the stated audience and matches what the video actually shows."""

FILLER = re.compile(r'^\s*(hey|hi|hello|in this video|introducing|did you know|meet|welcome|today)\b', re.I)


def _clean(t):
    t = re.sub(r'[#@]\w+', '', str(t or '')).strip().strip('"').strip()
    t = re.sub(r'\s+', ' ', t)
    return t


def _score(h):
    s = sum(float(h.get(k) or 0) for k in ('clarity', 'curiosity', 'specificity', 'fit'))
    words = len(h['text'].split())
    if words > 9: s -= (words - 9) * 2           # too long to read in two seconds
    if len(h['text']) > 50: s -= 3
    if FILLER.match(h['text']): s -= 8
    return s


def write_hooks(sb, inputs, source=None, n=6):
    """Candidates best-first: [{'text', 'accent', 'pattern', 'score'}]. Raises llm.LLMError on failure."""
    scenes = ' | '.join(f"[{s['type']}] " + ' '.join(str(v) for k, v in s.items() if isinstance(v, str) and k not in ('type', 'image', 'kind'))
                        for s in sb['scenes'][:8])[:1800]
    user = (f"Write {n} hook candidates, at least one per pattern where it fits:\n"
            + '\n'.join(f'- {k}: {v}' for k, v in PATTERNS.items())
            + f"\n\nWhat the video is about: {sb.get('name')}" + (f" — {inputs['topic']}" if inputs.get('topic') else '')
            + (f"\nAudience / niche: {inputs['audience']}" if inputs.get('audience') else '')
            + f"\nWhat the video shows, in order: {scenes}")
    if source and source.get('text'):
        user += f"\n\n<source url=\"{source.get('url')}\">\n{source['text'][:3000]}\n</source>"
    data = llm.complete_json(SYSTEM, user, max_tokens=1500)
    out = []
    for h in (data.get('hooks') if isinstance(data, dict) else data) or []:
        if not isinstance(h, dict): continue
        t = _clean(h.get('text'))
        if not t or len(t) > 70: continue
        h = {**h, 'text': t, 'accent': _clean(h.get('accent'))[:30], 'pattern': str(h.get('pattern') or '')[:12]}
        h['score'] = round(_score(h), 1)
        out.append({k: h[k] for k in ('text', 'accent', 'pattern', 'score')})
    out.sort(key=lambda h: -h['score'])
    seen, uniq = set(), []
    for h in out:
        k = h['text'].lower()
        if k not in seen: seen.add(k); uniq.append(h)
    return uniq


def heuristic_hook(sb, inputs):
    """No model: a problem- or result-style hook from the brief, kept short."""
    from .storyboard import _clause
    topic = (inputs.get('topic') or sb.get('topic') or '').strip()
    name = sb.get('name') or ''
    hook = next((s for s in sb['scenes'] if s['type'] == 'hook'), None)
    if topic:
        text = _clause(topic.rstrip('.!'), 50)
        if not text.endswith('?') and not re.match(r'^(stop|still|how|why|\d)', text, re.I) and len(text.split()) <= 6 and name:
            text = _clause(f'{text}: {name}', 50)
    elif hook:
        text = _clause(' '.join(x for x in (hook.get('kicker'), hook.get('big'), hook.get('punch')) if x), 50)
    else:
        text = _clause(name, 50)
    words = [w for w in re.findall(r"[A-Za-z][\w'-]+", text) if len(w) > 3]
    return {'text': text, 'accent': max(words, key=len) if words else '', 'pattern': 'heuristic', 'score': 0}


def apply(sb, hooks):
    """Put the best hook on screen from frame 0 (a cold open before the template's own opener) and keep the others."""
    if not hooks: return sb
    best = hooks[0]
    sb['hook_line'] = best
    sb['hook_alternatives'] = hooks[1:4]
    scenes = [s for s in sb['scenes'] if s['type'] != 'coldopen']
    if scenes and scenes[0]['type'] == 'hook':      # the cold open does the hook's job; don't say it twice
        scenes = scenes[1:]
    sub = (sb.get('audience') or '').strip()
    sb['scenes'] = [{'type': 'coldopen', 'text': best['text'], 'accent': best.get('accent', ''),
                     'sub': ('For ' + sub) if sub and not sub.lower().startswith('for ') else sub}] + scenes
    return sb
