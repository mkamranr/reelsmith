"""Story structures for templates.

Each template is a different kind of video, not just a different look:

  demo         Midnight   hook with pains → title → code → features → stats → steps → command → CTA
  story        Editorial  pull-quote cold open → headline → numbered chapters → numbers → closing quote → CTA
  walkthrough  Terminal   opening command → code → pipeline → command with output → numbers → CTA
  listicle     Pop        question hook → countdown (N … 1) → punchline → CTA
  keynote      Minimal    calm title → one statement at a time → feature panels → one number → CTA
  trailer      Aurora     teaser lines in letterbox → title reveal → features → numbers → vision line → CTA

The planner is told the structure (blueprint_text). Whatever comes back, from a model or the built-in planner, goes
through conform(), which converts scene types the template doesn't use, enforces its opening and order, and numbers
countdowns and chapters, so the structure holds even when a model ignores instructions.
"""
import re

from .engine import templates as tpl

ALLOWED = {
    'demo': {'hook', 'title', 'code', 'terminal', 'statement', 'bullets', 'features', 'stats', 'steps', 'cta'},
    'story': {'quote', 'title', 'chapter', 'stats', 'statement', 'cta'},
    'walkthrough': {'terminal', 'code', 'steps', 'stats', 'bullets', 'statement', 'title', 'cta'},
    'listicle': {'hook', 'rank', 'statement', 'stats', 'cta'},
    'keynote': {'title', 'statement', 'chapter', 'features', 'stats', 'cta'},
    'trailer': {'teaser', 'title', 'features', 'stats', 'statement', 'cta'},
}
OPENING = {'demo': 'hook', 'story': 'quote', 'walkthrough': 'terminal', 'listicle': 'hook', 'keynote': 'title', 'trailer': 'teaser'}
ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']


def _r(x): return int(x + 0.5)
def _clamp(x, a, b): return max(a, min(b, x))


def counts(bp, duration, has_numbers=True):
    """How many repeated scenes a structure gets for a given length."""
    t = next(v for v in tpl.TEMPLATES.values() if v['blueprint'] == bp)
    pace = t['pace']
    if bp == 'listicle':
        fixed = (4.0 + 4.5 + (2.8 if duration >= 30 else 0)) * pace
        return {'rank': _clamp(_r((duration * 0.92 - fixed) / (3.4 * pace)), 3, 5 if duration < 45 else 7)}
    if bp == 'story':
        fixed = (4.5 + 4.0 + 5.0 + (4.5 if duration >= 45 else 0) + (4.0 if has_numbers and duration >= 40 else 0)) * pace
        return {'chapter': _clamp(_r((duration * 0.95 - fixed) / (5.0 * pace)), 2, 5)}
    if bp == 'keynote':
        return {'statement': 1 if duration < 30 else 2 if duration < 55 else 3}
    if bp == 'trailer':
        return {'teaser_lines': 3 if duration < 40 else 4}
    return {}


def blueprint_text(template_id, duration, has_numbers=True):
    t = tpl.get(template_id); bp = t['blueprint']; c = counts(bp, duration, has_numbers)
    short = duration < 25
    if bp == 'listicle':
        n = c['rank']
        s = [f'1. hook: a question or bold claim that promises the list (e.g. big "{n}", punch "reasons to try …"). Pains only if natural.',
             f'2-{n + 1}. rank × {n}: a countdown from {n} to 1. Each has rank ("{n}" … "1"), title (≤40, the item) and sub '
             f'(≤90, why it matters). Every item must be distinct and come from the material; rank 1 is the strongest.']
        if duration >= 30: s.append(f'{n + 2}. statement: a one-line punchline.')
        s.append('Last. cta.')
    elif bp == 'story':
        n = c['chapter']
        s = ['1. quote: a cold open. The single most striking line from the material (or a sharp observation about it), with "by".',
             '2. title: the headline (name) and a standfirst (tagline).',
             f'3-{n + 2}. chapter × {n}: numbered sections, one idea each: title (≤44) and body (1-2 sentences, ≤150).']
        if has_numbers and duration >= 40: s.append('Then stats: "by the numbers", only real figures from the material.')
        if duration >= 45: s.append('Then quote: a closing pull-quote that lands the story.')
        s.append('Last. cta.')
    elif bp == 'walkthrough':
        s = ['1. terminal: open on the command that gets someone started (install, clone or run). No invented output.',
             '2. code: the core usage, real code from the material.']
        if not short:
            s += ['3. steps: how it works, as a pipeline of 3-5 steps.',
                  '4. terminal: running it, with outputs lines (prefix "✓ " only for results the material states).']
            if has_numbers: s.append('5. stats: only real figures.')
        s.append('Last. cta.')
    elif bp == 'keynote':
        k = c['statement']
        s = ['1. title: a calm opening. No hook, no pains.', '2. statement: the one idea, plainly said.']
        if not short: s.append('3. features: 2-3 panels, one benefit each, with 2-3 short points.')
        if k > 1: s.append(f'Then statement × {k - 1}: one idea each, never two in a row without something between.')
        if has_numbers and not short: s.append('Then stats: one single number that matters.')
        s.append('Last. cta.')
    elif bp == 'trailer':
        s = [f'1. teaser: {c["teaser_lines"]} very short lines (≤34 chars) building tension; the last line is the payoff. '
             'Do not name the product yet.',
             '2. title: the reveal (name + tagline).']
        if not short: s.append('3. features: 2-4 panels.')
        if has_numbers and not short: s.append('4. stats: only real figures.')
        s += ['Then statement: the vision, one line.', 'Last. cta.']
    else:
        s = ['1. hook with 2-3 pains the audience recognises.', '2. title.',
             '3. code (or terminal if the material has commands but no code).']
        if not short: s += ['4. features (2-3 panels) or bullets.', '5. stats only with real numbers.', '6. steps: how it works.',
                            '7. terminal: the command to try it.']
        s.append('Last. cta.')
    return (f'STRUCTURE: this template is a {t["format"].lower()}. Follow this order exactly:\n' + '\n'.join(s))


# ------------------------------------------------------------------ conforming
def _items(sc):
    """(title, sub) pairs from any list-like scene."""
    out = []
    for it in sc.get('items') or sc.get('steps') or []:
        if isinstance(it, str): out.append((it, ''))
        elif isinstance(it, dict): out.append((it.get('title', ''), it.get('sub') or it.get('subtitle') or ''))
    return [(a, b) for a, b in out if a]


def _cap(s):
    s = (s or '').strip()
    return s[:1].upper() + s[1:]


def _hook_text(sc):
    return ' '.join(x for x in (sc.get('kicker'), sc.get('big'), sc.get('punch')) if x).strip()


def _convert(sc, bp):
    """Scenes a structure doesn't use, re-expressed in its own vocabulary (may return several or none)."""
    k = sc['type']
    if k in ALLOWED[bp]: return [sc]
    listy = k in ('bullets', 'features', 'steps')
    if bp == 'story':
        if listy: return [{'type': 'chapter', 'title': a, 'body': b} for a, b in _items(sc)][:5]
        if k == 'rank': return [{'type': 'chapter', 'title': sc.get('title', ''), 'body': sc.get('sub', '')}]
        if k == 'hook': return [{'type': 'quote', 'text': _hook_text(sc)}]
        if k == 'teaser': return [{'type': 'quote', 'text': ' '.join(sc.get('lines') or [])}]
        return []
    if bp == 'listicle':
        if listy: return [{'type': 'rank', 'title': a, 'sub': b} for a, b in _items(sc)]
        if k == 'chapter': return [{'type': 'rank', 'title': sc.get('title', ''), 'sub': sc.get('body', '')}]
        if k == 'quote': return [{'type': 'statement', 'text': sc.get('text', '')}]
        if k == 'teaser': return [{'type': 'statement', 'text': ' '.join(sc.get('lines') or [])}]
        return []
    if bp in ('trailer', 'keynote'):
        if listy or k == 'rank':
            items = _items(sc) or [(sc.get('title', ''), sc.get('sub', ''))]
            return [{'type': 'features', 'items': [{'title': a, 'subtitle': b, 'points': []} for a, b in items][:4]}]
        if k == 'chapter' and bp == 'trailer':
            return [{'type': 'features', 'items': [{'title': sc.get('title', ''), 'subtitle': sc.get('body', ''), 'points': []}]}]
        if k == 'hook':
            if bp == 'trailer':
                first = ' '.join(x for x in (sc.get('kicker'), sc.get('big')) if x)
                return [{'type': 'teaser', 'lines': [_cap(x) for x in (first, sc.get('punch'), sc.get('answer')) if x][:4]}]
            return [{'type': 'statement', 'text': _cap(_hook_text(sc))}]
        if k in ('quote', 'teaser'): return [{'type': 'statement', 'text': sc.get('text') or ' '.join(sc.get('lines') or [])}]
        return []
    if bp == 'walkthrough':
        if k == 'features': return [{'type': 'bullets', 'caption': 'What you get', 'items': [{'title': a, 'sub': b} for a, b in _items(sc)]}]
        if k in ('rank', 'chapter'): return [{'type': 'bullets', 'items': [{'title': sc.get('title', ''), 'sub': sc.get('sub') or sc.get('body', '')}]}]
        if k == 'hook': return []                  # the opening command already does the hook's job
        if k in ('quote', 'teaser'):
            return [{'type': 'statement', 'text': sc.get('text') or ' '.join(sc.get('lines') or [])}]
        return []
    # demo
    if k in ('quote', 'teaser'): return [{'type': 'statement', 'text': sc.get('text') or ' '.join(sc.get('lines') or [])}]
    if k in ('rank', 'chapter'): return [{'type': 'bullets', 'items': [{'title': sc.get('title', ''), 'sub': sc.get('sub') or sc.get('body', '')}]}]
    return []


def _merge_bullets(scenes):
    """Neighbouring single-item bullets (from converted ranks/chapters) become one list."""
    out = []
    for s in scenes:
        if out and s['type'] == out[-1]['type'] == 'bullets' and len(out[-1].get('items', [])) < 5 and not s.get('caption'):
            out[-1]['items'] = (out[-1].get('items') or []) + (s.get('items') or [])
        else:
            out.append(s)
    return out


def conform(scenes, template_id, duration, name='', url='', material=None):
    """Make a scene list follow the template's structure. Returns a new list (sanitized again by the caller)."""
    bp = tpl.get(template_id)['blueprint']
    has_numbers = any(s['type'] == 'stats' for s in scenes)
    c = counts(bp, duration, has_numbers)
    cta = next((s for s in scenes if s['type'] == 'cta'), {'type': 'cta', 'name': name, 'url': url})
    body = [x for s in scenes if s['type'] != 'cta' for x in _convert(s, bp)]
    body = [s for s in body if any(v for k, v in s.items() if k != 'type')]
    body = _merge_bullets(body)
    first = OPENING[bp]
    opener = next((s for s in body if s['type'] == first), None)
    if opener is None:
        opener = _synth_opener(bp, scenes, name, url, material, c)
    rest = [s for s in body if s is not opener]

    if bp == 'listicle':
        ranks = [s for s in rest if s['type'] == 'rank']
        ranks = ranks[-c['rank']:] if len(ranks) > c['rank'] else ranks          # a countdown ends with the best
        n = len(ranks)
        for i, r in enumerate(ranks): r['rank'], r['of'] = str(n - i), n
        others = [s for s in rest if s['type'] != 'rank']
        if opener.get('big', '').isdigit() and n: opener['big'] = str(n)
        ordered = [opener] + ranks + [s for s in others if s['type'] == 'statement'][:1] + [s for s in others if s['type'] == 'stats'][:1]
    elif bp == 'story':
        title = next((s for s in rest if s['type'] == 'title'), None)
        chapters = [s for s in rest if s['type'] == 'chapter'][:c['chapter']]
        for i, ch in enumerate(chapters): ch['number'] = ROMAN[i] + '.'
        closing = [s for s in rest if s['type'] == 'quote'][:1] if duration >= 45 else []
        others = [s for s in rest if s['type'] in ('stats', 'statement')][:1]
        ordered = [opener] + ([title] if title else []) + chapters + others + closing
    elif bp == 'trailer':
        title = next((s for s in rest if s['type'] == 'title'), {'type': 'title', 'name': name})
        if opener.get('lines'): opener['lines'] = opener['lines'][:c['teaser_lines']]
        ordered = [opener, title] + _by_order([s for s in rest if s is not title and s['type'] != 'teaser'],
                                              ['features', 'stats', 'statement'], {'statement': 1})
    elif bp == 'keynote':
        chapters = [s for s in rest if s['type'] == 'chapter']
        for i, ch in enumerate(chapters): ch['number'] = f'{i + 1:02d}'
        ordered = [opener] + [s for s in rest if s['type'] != 'title']
        deduped = []                       # never two statements in a row
        for s in ordered:
            if deduped and s['type'] == deduped[-1]['type'] == 'statement': continue
            deduped.append(s)
        ordered = deduped
    elif bp == 'walkthrough':
        ordered = [opener] + _by_order(rest, ['title', 'code', 'bullets', 'steps', 'statement', 'terminal', 'stats'], {'statement': 1, 'title': 1})
    else:
        title = next((s for s in rest if s['type'] == 'title'), None)
        ordered = [opener] + ([title] if title else []) + [s for s in rest if s is not title]
    return ordered + [cta]


def _by_order(scenes, order, limits=None):
    """Stable sort by scene type into the template's order, keeping at most limits[type] of a type."""
    limits = limits or {}; seen = {}
    out = []
    for s in sorted(scenes, key=lambda s: order.index(s['type']) if s['type'] in order else len(order)):
        seen[s['type']] = seen.get(s['type'], 0) + 1
        if seen[s['type']] <= limits.get(s['type'], 99): out.append(s)
    return out


def _synth_opener(bp, scenes, name, url, m, c):
    """The template's opening scene, made from what's there when the plan didn't include one."""
    m = m or {}
    lead = m.get('lead') or next((s.get('text') or s.get('tagline') or _hook_text(s) for s in scenes
                                  if s.get('text') or s.get('tagline') or s.get('type') == 'hook'), '') or name
    if bp == 'story':
        return {'type': 'quote', 'text': lead, 'by': name}
    if bp == 'walkthrough':
        cmd = (m.get('cmds') or [None])[0]
        if not cmd:
            cmd = f'git clone https://{url}' if url.startswith('github.com/') else 'cat README.md'
        return {'type': 'terminal', 'caption': 'Start here.', 'accent': 'here', 'command': cmd}
    if bp == 'listicle':
        n = c.get('rank', 5)
        return {'type': 'hook', 'kicker': 'Here are', 'big': str(n), 'punch': f'reasons to try {name}'[:34]}
    if bp == 'keynote':
        return {'type': 'title', 'name': name, 'tagline': lead}
    if bp == 'trailer':
        bits = [b.strip() for b in re.split(r'[.,;:—-]\s+', lead) if b.strip()][:c.get('teaser_lines', 3) - 1]
        return {'type': 'teaser', 'lines': (bits or ['Something new is here.']) + ['Meet ' + name + '.']}
    return {'type': 'hook', 'kicker': 'Meet', 'big': name[:16], 'punch': ''}


# ------------------------------------------------------------------ built-in planner
GENERIC = (r'licen[cs]e|contribut|install|table of contents|credits|acknowledg|^what |^why |overview|introduction|usage|'
           r'quick ?start|getting started|features?$|development|faq|roadmap|support|changelog|example|demo|requirements|'
           r'docker|cli$|how it works|keys|privacy|settings|testing')


def _plain(md):
    t = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md); t = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', t)
    t = re.sub(r'[`*_>#|]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def sections(text):
    """[(heading, first sentence)] for README-style markdown, generic headings skipped."""
    out = []
    parts = re.split(r'^(#{2,3} .+)$', text or '', flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        h = parts[i].strip('# ').strip()
        if not (3 < len(h) <= 40) or re.search(GENERIC, h, re.I): continue
        body = re.sub(r'```.*?```', ' ', parts[i + 1], flags=re.S)
        paras = [p for p in (_plain(x) for x in body.split('\n\n')) if len(p) > 20]
        sent = re.split(r'(?<=[.!?])\s+', paras[0])[0] if paras else ''
        out.append((h, sent[:140]))
    return out


def material(inputs, source):
    from .storyboard import _sentences, _product_name, _clause, _s
    src = source or {'text': '', 'facts': {}, 'title': '', 'url': ''}
    text, facts = src.get('text', ''), src.get('facts', {})
    topic = (inputs.get('topic') or '').strip()
    product = _product_name(inputs, source)
    sents = _sentences(inputs.get('description') or '') or ([facts['description']] if facts.get('description') else []) or _sentences(text)[:6]
    lead = sents[0] if sents else ''
    if not topic and not product and lead:
        topic = lead.rstrip('.!?'); sents = sents[1:]; lead = sents[0] if sents else ''
    name = _s(product or _clause(topic, 32) or 'Untitled', 32)
    secs = sections(text)
    feat = re.search(r'^## +features?\b.*?$(.*?)(?=^## |\Z)', text, re.M | re.S | re.I)
    if feat:
        fs = sections('\n' + re.sub(r'^###', '##', feat.group(1), flags=re.M))
        if len(fs) >= 2: secs = fs
    if len(secs) < 2:
        secs = secs + [(_clause(x, 40), '' if len(x) <= 40 else x) for x in sents[1:6]]
    code = re.findall(r'```(\w*)\n(.*?)```', text, re.S)
    other = next(((lang, b) for lang, b in code if lang not in ('bash', 'sh', 'shell', 'console', 'zsh', '', 'text')), None)
    shell_lines = [l.strip().lstrip('$ ').strip() for lang, b in code if lang in ('bash', 'sh', 'shell', 'console', 'zsh', '')
                   for l in b.split('\n') if l.strip() and not l.strip().startswith('#')]
    runners = r'^(npx|npm (run|start|i|install)|pip install|pipx|uvx|docker (run|compose)|brew install|cargo (run|install)|go (run|install)|node |python3? |deno |bun |git clone )'
    devtool = r'\b(test|lint|typecheck|format|prettier|eslint|dev:|build)\b'
    cmds = [c for c in shell_lines if len(c) <= 56 and re.match(runners, c) and not re.search(devtool, c)] \
        or [c for c in shell_lines if len(c) <= 56 and not re.search(devtool, c)]
    def fmt(v): return f"{v / 1000:.1f}k".replace('.0k', 'k') if v >= 1000 else str(v)
    nums = [(k, fmt(v)) for k, v in facts.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]
    return {'name': name, 'topic': topic, 'product': product, 'sents': sents, 'lead': lead, 'sections': secs,
            'code': other, 'cmds': cmds, 'nums': nums, 'facts': facts, 'url': src.get('url', ''),
            'tag': ' · '.join(str(x) for x in (facts.get('license'), facts.get('language')) if x)}


def assemble(m, template_id, duration):
    """Built-in planner: the template's structure filled from the material. Nothing invented."""
    from .storyboard import _clause, _s
    bp = tpl.get(template_id)['blueprint']; c = counts(bp, duration, bool(m['nums']))
    name, lead, topic, secs, sents = m['name'], m['lead'], m['topic'], m['sections'], m['sents']
    stats = [{'type': 'stats', 'caption': 'By the numbers', 'items': [{'value': v, 'label': k} for k, v in m['nums'][:3]]}] if m['nums'] else []
    cta = {'type': 'cta', 'name': name, 'url': m['url'], 'tagline': m['tag'],
           'line': _clause(topic, 44) if topic and m['product'] else 'Link in bio.'}
    code = []
    if m['code']:
        lang, block = m['code']
        code = [{'type': 'code', 'caption': 'See it in code.', 'accent': 'code', 'language': lang or 'code',
                 'filename': f'example.{lang or "txt"}', 'lines': block.strip('\n').split('\n')[:14]}]
    later = [x for x in sents[1:] if len(x) <= 70]
    if bp == 'listicle':
        items = secs[:c['rank']]
        ranks = [{'type': 'rank', 'title': _clause(a, 40), 'sub': _clause(b, 90)} for a, b in reversed(items)]
        hook = {'type': 'hook', 'kicker': 'Here are', 'big': str(len(ranks) or 3),
                'punch': _clause(f'reasons to try {name}' if m['product'] else f'things about {topic or name}', 34)}
        tail = [{'type': 'statement', 'text': _clause(lead, 70)}] if lead and duration >= 30 else []
        return [hook] + ranks + tail + stats + [cta]
    if bp == 'story':
        chapters = [{'type': 'chapter', 'title': _clause(a, 44), 'body': _clause(b, 150)} for a, b in secs[:c['chapter']]]
        out = [{'type': 'quote', 'text': _clause(lead or topic or name, 140), 'by': name},
               {'type': 'title', 'name': name, 'tagline': _clause(topic or lead, 70)}] + chapters + stats
        if duration >= 45 and later: out.append({'type': 'quote', 'text': later[-1], 'by': name})
        return out + [cta]
    if bp == 'walkthrough':
        start = m['cmds'][0] if m['cmds'] else (f"git clone https://{m['url']}" if m['url'].startswith('github.com/') else 'cat README.md')
        out = [{'type': 'terminal', 'caption': 'Start here.', 'accent': 'here', 'command': start}] + code
        if len(secs) >= 3 and duration >= 25:
            out.append({'type': 'steps', 'title': 'How it works', 'steps': [{'title': _clause(a, 22), 'sub': _clause(b, 40)} for a, b in secs[:5]]})
        if len(m['cmds']) > 1 and duration >= 25:
            out.append({'type': 'terminal', 'caption': 'Run it.', 'accent': 'Run', 'command': m['cmds'][1]})
        return out + stats + [cta]
    if bp == 'keynote':
        feats = [{'type': 'features', 'items': [{'title': _clause(a, 24), 'subtitle': _clause(b, 60), 'points': []} for a, b in secs[:3]]}] \
            if secs and duration >= 25 else []
        out = [{'type': 'title', 'name': name, 'tagline': _clause(topic or lead, 70)}]
        if lead: out.append({'type': 'statement', 'text': _clause(lead, 70)})
        out += feats
        if len(later) > 0 and c['statement'] > 1: out.append({'type': 'statement', 'text': later[0]})
        return out + stats[:1] + [cta]
    if bp == 'trailer':
        bits = [b.strip(' .') + '.' for b in re.split(r'[.,;:—]\s+', lead) if 3 < len(b.strip()) <= 34][:c['teaser_lines'] - 1]
        if not bits: bits = [_clause(topic, 34)] if topic else ['Something new is here.']
        teaser = {'type': 'teaser', 'lines': bits + [f'Meet {name}.'[:34]]}
        feats = [{'type': 'features', 'items': [{'title': _clause(a, 24), 'subtitle': _clause(b, 60), 'points': []} for a, b in secs[:3]]}] \
            if secs and duration >= 25 else []
        vision = [{'type': 'statement', 'text': later[-1]}] if later else []
        return [teaser, {'type': 'title', 'name': name, 'tagline': _clause(lead, 70)}] + feats + stats + vision + [cta]
    # demo: the original built-in plan
    big = name if len(name) <= 16 else name.split()[0][:16]
    hook = {'type': 'hook', 'kicker': _clause(topic, 60) if topic and m['product'] else 'Meet', 'big': big,
            'punch': '' if topic and m['product'] else _clause(lead, 34)}
    out = [hook] + ([{'type': 'title', 'name': name, 'tagline': _clause(lead, 70)}] if m['product'] else [])
    if later: out.append({'type': 'statement', 'text': later[0]})
    out += code
    if len(secs) >= 2: out.append({'type': 'bullets', 'caption': "What's inside", 'accent': 'inside', 'checks': True,
                                    'items': [{'title': _clause(a, 40), 'sub': _clause(b, 60)} for a, b in secs[:5]]})
    out += stats
    if m['cmds']: out.append({'type': 'terminal', 'caption': 'Try it now.', 'accent': 'now', 'command': m['cmds'][0]})
    return out + [cta]
