"""Video templates.

A template is a complete identity, not just colours: palette, typography, corner and border treatment, shadow style,
background, transition, music, how loud the sound effects are, and the tone the planner writes in. Every scene type
draws through these values, so any storyboard works with any template.
"""
INTER = {w: f'Inter-{w}.ttf' for w in (400, 500, 600, 700, 800, 900)}
JBM = {400: 'JBM-Regular.ttf', 500: 'JBM-Medium.ttf', 700: 'JBM-Bold.ttf', 800: 'JBM-ExtraBold.ttf'}
FRAUNCES = {w: f'Fraunces-{w}.ttf' for w in (400, 600, 700, 800)}
BRICOLAGE = {w: f'Bricolage-{w}.ttf' for w in (600, 700, 800)}
SPACE = {w: f'SpaceGrotesk-{w}.ttf' for w in (500, 600, 700)}

SYNTAX_DARK = dict(kw=(255, 123, 114), str=(165, 214, 255), blue=(121, 192, 255), purple=(210, 168, 255),
                   tag=(126, 231, 135), comment=(110, 128, 148))
SYNTAX_LIGHT = dict(kw=(207, 34, 46), str=(10, 48, 105), blue=(5, 80, 174), purple=(130, 80, 223),
                    tag=(17, 99, 41), comment=(110, 119, 129))
SYNTAX_PHOSPHOR = dict(kw=(255, 196, 0), str=(0, 229, 255), blue=(0, 229, 255), purple=(199, 146, 234),
                       tag=(57, 255, 136), comment=(64, 130, 90))

BASE = dict(
    light=False, accent='#F0B429', acc2=None, accent_free=False,
    red=(255, 99, 99), green=(86, 214, 140), syntax=SYNTAX_DARK,
    fonts=dict(sans=INTER, display=None, mono=JBM), display_from=700, display_weight={},
    track=1.0, radius=1.0, border_w=1.0, shadow='soft', shadow_alpha=1.0, glow=False,
    bg_style='grid', bg_colors=[], vignette=0.55, grain=0.06, scanlines=False, transition=None,
    music=dict(bpm=120, prog='minor', pad='saw', pad_gain=0.08, pad_lp=1400, arp=None, arp_gain=0.0,
               bass=0.3, kick=0.42, hats=0.07, clap=0.0),
    sfx={}, tone='', prefer=[],
)


def _t(**kw):
    t = dict(BASE); t.update(kw)
    t['music'] = {**BASE['music'], **kw.get('music', {})}
    return t


TEMPLATES = {
    'midnight': _t(
        name='Midnight', description='Dark navy, amber, a faint grid and confident kinetic type. The original look.',
        accent_free=True,
        bg=(10, 14, 20), surf=(20, 28, 38), text=(244, 247, 250), muted=(128, 147, 166), border=(30, 42, 54),
        codebg=(14, 20, 28), panel=(13, 18, 26),
        tone='Confident and developer-friendly. Concrete claims, show the thing working.',
        prefer=['code', 'terminal', 'steps', 'stats']),

    'editorial': _t(
        name='Editorial', description='Paper-light pages, a serif display face, a red accent and thin rules. Page-turn cuts.',
        light=True, accent='#C8102E', acc2='#8F0A20',
        bg=(242, 240, 235), surf=(255, 255, 255), text=(22, 20, 18), muted=(108, 102, 94), border=(212, 206, 196),
        codebg=(250, 248, 244), panel=(250, 248, 244), red=(200, 16, 46), green=(30, 120, 70), syntax=SYNTAX_LIGHT,
        fonts=dict(sans=INTER, display=FRAUNCES, mono=JBM), display_weight={700: 600, 800: 700, 900: 800},
        track=0.25, radius=0.3, shadow='soft', shadow_alpha=0.22, bg_style='paper', vignette=0.10, grain=0.05,
        transition='left',
        music=dict(bpm=90, prog='major', pad='sine', pad_gain=0.06, pad_lp=1800, arp='pluck', arp_gain=0.13,
                   bass=0.18, kick=0.16, hats=0.0),
        sfx={'impact': 0.45, 'boom': 0.6, 'whoosh': 0.55, 'riser': 0.6, 'key': 0.8},
        tone='Considered and magazine-like. Fewer, better words; one memorable line per scene; no hype.',
        prefer=['statement', 'bullets', 'stats', 'title']),

    'terminal': _t(
        name='Terminal', description='Black CRT with scanlines, all monospace, phosphor-green glow and glitch cuts.',
        accent='#39FF88', acc2='#00E5FF',
        bg=(4, 8, 6), surf=(8, 20, 13), text=(205, 255, 220), muted=(96, 168, 122), border=(32, 96, 60),
        codebg=(6, 14, 9), panel=(6, 14, 10), red=(255, 92, 92), green=(57, 255, 136), syntax=SYNTAX_PHOSPHOR,
        fonts=dict(sans=JBM, display=JBM, mono=JBM), track=0.0, radius=0.22, shadow='glow', shadow_alpha=0.8,
        glow=True, bg_style='crt', vignette=0.75, grain=0.08, scanlines=True, transition='glitch',
        music=dict(bpm=128, prog='minor', pad='square', pad_gain=0.035, pad_lp=1600, arp='square', arp_gain=0.12,
                   bass=0.28, kick=0.38, hats=0.06),
        sfx={'key': 1.25, 'tick': 1.3, 'error': 1.2, 'chime': 0.7},
        tone='Terse and technical, like a good commit message. Commands, flags and numbers over adjectives.',
        prefer=['terminal', 'code', 'steps', 'stats']),

    'pop': _t(
        name='Pop', description='Cream background, big colour shapes that change every scene, thick outlines and hard shadows.',
        light=True, accent='#2B59FF', acc2='#2B59FF',
        bg=(255, 246, 229), surf=(255, 255, 255), text=(17, 17, 17), muted=(72, 72, 72), border=(17, 17, 17),
        codebg=(255, 255, 255), panel=(255, 255, 255), red=(230, 57, 70), green=(20, 150, 90), syntax=SYNTAX_LIGHT,
        fonts=dict(sans=INTER, display=BRICOLAGE, mono=JBM), display_weight={700: 800, 800: 800, 900: 800},
        track=0.5, radius=1.15, border_w=2.2, shadow='hard', bg_style='pop',
        bg_colors=[(255, 107, 74), (255, 210, 63), (61, 219, 182), (255, 155, 210), (185, 168, 255)],
        vignette=0.0, grain=0.035, transition='pop',
        music=dict(bpm=128, prog='major', pad='saw', pad_gain=0.05, pad_lp=2600, arp='pluck', arp_gain=0.11,
                   bass=0.32, kick=0.5, hats=0.08, clap=0.22),
        sfx={'pop': 1.3, 'impact': 1.0, 'snap': 1.2},
        tone='Playful, punchy and high-energy. Short words, strong verbs, a little cheek. Make people smile.',
        prefer=['hook', 'statement', 'stats', 'features', 'bullets']),

    'minimal': _t(
        name='Minimal', description='Near-white, light-weight type, generous space, soft shadows and quiet crossfades.',
        light=True, accent='#2563EB', acc2='#1D4ED8',
        bg=(247, 247, 248), surf=(255, 255, 255), text=(15, 17, 21), muted=(107, 114, 128), border=(229, 231, 235),
        codebg=(249, 250, 251), panel=(255, 255, 255), red=(220, 38, 38), green=(22, 163, 74), syntax=SYNTAX_LIGHT,
        fonts=dict(sans=INTER, display=INTER, mono=JBM), display_weight={700: 600, 800: 600, 900: 700},
        track=1.4, radius=1.0, shadow='soft', shadow_alpha=0.28, bg_style='minimal', vignette=0.04, grain=0.025,
        transition='fade',
        music=dict(bpm=100, prog='major', pad='sine', pad_gain=0.07, pad_lp=2200, bass=0.15, kick=0.18, hats=0.0),
        sfx={'all': 0.6, 'impact': 0.35, 'boom': 0.45, 'riser': 0.5},
        tone='Calm, clear and premium. Simple sentences, one idea at a time, nothing shouted.',
        prefer=['title', 'statement', 'features', 'bullets']),

    'aurora': _t(
        name='Aurora', description='Deep violet with moving gradient light, frosted-glass cards and a modern grotesk.',
        accent='#F472B6', acc2='#22D3EE',
        bg=(11, 6, 32), surf=(255, 255, 255, 0.09), text=(250, 248, 255), muted=(196, 186, 228),
        border=(255, 255, 255, 0.24), codebg=(12, 8, 30, 0.62), panel=(18, 12, 44, 0.72),
        fonts=dict(sans=INTER, display=SPACE, mono=JBM), display_weight={700: 700, 800: 700, 900: 700},
        track=0.6, radius=1.3, shadow='soft', shadow_alpha=0.7, bg_style='aurora',
        bg_colors=[(124, 58, 237), (236, 72, 153), (6, 182, 212), (59, 130, 246)],
        vignette=0.45, grain=0.05, transition='dissolve',
        music=dict(bpm=110, prog='minor', pad='lush', pad_gain=0.085, pad_lp=1700, arp='bell', arp_gain=0.10,
                   bass=0.24, kick=0.3, hats=0.04),
        sfx={'impact': 0.8, 'whoosh': 0.8},
        tone='Visionary but specific, like a modern product launch. Big idea first, then proof.',
        prefer=['title', 'features', 'stats', 'statement']),
}

DEFAULT = 'midnight'


def get(tid):
    return TEMPLATES.get((tid or '').strip().lower()) or TEMPLATES[DEFAULT]


def resolve_id(tid):
    tid = (tid or '').strip().lower()
    return tid if tid in TEMPLATES else DEFAULT


def listing():
    def hexc(c): return '#%02x%02x%02x' % tuple(int(v) for v in c[:3])
    return [{'id': k, 'name': t['name'], 'description': t['description'], 'light': t['light'], 'accent': t['accent'],
             'swatches': [hexc(t['bg']), hexc(t['text']), t['accent'], t['acc2'] or t['accent']] +
                         [hexc(c) for c in t['bg_colors'][:2]],
             'accent_free': t['accent_free'], 'tone': t['tone']}
            for k, t in TEMPLATES.items()]
