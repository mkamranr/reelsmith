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
    align='c', margin=90, pace=1.0, format='', blueprint='demo',
    entrances=['rise'], sweep=False, hud='progress', device='browser', caption_style='pill', tr=0.42,
)


def _t(**kw):
    t = dict(BASE); t.update(kw)
    t['music'] = {**BASE['music'], **kw.get('music', {})}
    return t


TEMPLATES = {
    'midnight': _t(
        entrances=['rise', 'mask', 'pop', 'rise'], sweep=True, hud='progress', device='browser',
        format='Product demo', blueprint='demo',
        name='Midnight', description='Dark navy, amber, a faint grid and confident kinetic type. The original look.',
        accent_free=True,
        bg=(10, 14, 20), surf=(20, 28, 38), text=(244, 247, 250), muted=(128, 147, 166), border=(30, 42, 54),
        codebg=(14, 20, 28), panel=(13, 18, 26),
        tone='Confident and developer-friendly. Concrete claims, show the thing working.',
        prefer=['code', 'terminal', 'steps', 'stats']),

    'editorial': _t(
        entrances=['mask', 'blur', 'mask'], hud='deck', device='card', caption_style='serif', tr=0.5,
        format='Feature story', blueprint='story', align='l', margin=104, pace=1.1,
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
        entrances=['type', 'mask', 'type'], hud='terminal', device='browser', caption_style='mono', tr=0.34,
        format='README walkthrough', blueprint='walkthrough', align='l', margin=96, pace=0.95,
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
        entrances=['pop', 'slide', 'pop'], sweep=True, hud='none', device='phone', caption_style='bold', tr=0.36,
        format='Countdown listicle', blueprint='listicle', pace=0.8,
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
        entrances=['blur', 'rise', 'blur'], hud='none', device='phone', caption_style='clean', tr=0.55,
        format='Keynote', blueprint='keynote', pace=1.25,
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
        entrances=['blur', 'pop', 'blur'], sweep=True, hud='none', device='phone', caption_style='pill', tr=0.5,
        format='Launch trailer', blueprint='trailer',
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
    'cinema': _t(
        entrances=['blur', 'mask', 'blur'], sweep=True, hud='cinema', device='card', caption_style='film', tr=0.75,
        format='Mini documentary', blueprint='documentary', pace=1.15,
        name='Cinema', description='A warm film look: letterbox, drifting light leaks, serif titles and slow dissolves.',
        accent='#E8A04B', acc2='#C2562F',
        bg=(14, 11, 9), surf=(255, 240, 220, 0.07), text=(244, 236, 224), muted=(172, 158, 142), border=(255, 240, 220, 0.18),
        codebg=(20, 16, 13, 0.85), panel=(24, 19, 15, 0.88), red=(230, 90, 70), green=(150, 200, 120),
        fonts=dict(sans=INTER, display=FRAUNCES, mono=JBM), display_weight={700: 600, 800: 700, 900: 700},
        track=0.3, radius=0.6, shadow='soft', shadow_alpha=0.9, bg_style='cinema', vignette=0.72, grain=0.10,
        transition='dissolve',
        music=dict(bpm=76, prog='minor', pad='lush', pad_gain=0.09, pad_lp=1300, arp='bell', arp_gain=0.07,
                   bass=0.2, kick=0.1, hats=0.0),
        sfx={'impact': 0.7, 'boom': 1.1, 'whoosh': 0.5, 'key': 0.6, 'tick': 0.6},
        tone='Cinematic and human, like a short documentary. Stakes first, then the turn, then the payoff.',
        prefer=['teaser', 'quote', 'chapter', 'statement']),

    'showcase': _t(
        entrances=['slide', 'pop', 'rise'], sweep=True, hud='none', device='phone', caption_style='pill', tr=0.42,
        format='Screen tour', blueprint='tour',
        name='Showcase', description='A studio stage for your product: device frames, the page scrolling by, glossy light.',
        accent='#8B9DFF', acc2='#5EEAD4',
        bg=(16, 18, 24), surf=(34, 38, 48), text=(245, 246, 250), muted=(150, 158, 175), border=(52, 58, 72),
        codebg=(20, 22, 30), panel=(24, 27, 35),
        fonts=dict(sans=INTER, display=SPACE, mono=JBM), display_weight={700: 700, 800: 700, 900: 700},
        track=0.7, radius=1.25, shadow='soft', bg_style='studio', vignette=0.5, grain=0.04, transition='zoom',
        music=dict(bpm=116, prog='major', pad='saw', pad_gain=0.06, pad_lp=2000, arp='pluck', arp_gain=0.09,
                   bass=0.28, kick=0.42, hats=0.06),
        sfx={'pop': 1.1},
        tone='Product-focused and visual. Point at what is on screen; short, confident lines.',
        prefer=['scroll', 'features', 'stats', 'title']),

    'broadcast': _t(
        entrances=['slide', 'mask', 'slide'], hud='broadcast', device='browser', caption_style='strap', tr=0.32,
        format='News segment', blueprint='news', align='l', margin=80, pace=0.95,
        name='Broadcast', description='A news segment: red-and-navy straps, a running ticker, hard wipes, lower-third captions.',
        accent='#E11D2E', acc2='#FF4D5E',
        bg=(6, 16, 44), surf=(14, 30, 74), text=(255, 255, 255), muted=(172, 188, 218), border=(40, 66, 130),
        codebg=(8, 20, 52), panel=(10, 24, 60), red=(255, 80, 80), green=(90, 220, 150),
        fonts=dict(sans=INTER, display=INTER, mono=JBM), display_weight={700: 800, 800: 900, 900: 900},
        track=1.2, radius=0.15, shadow='soft', shadow_alpha=0.8, bg_style='broadcast', vignette=0.45, grain=0.03,
        transition='left',
        music=dict(bpm=124, prog='minor', pad='saw', pad_gain=0.05, pad_lp=1800, arp='square', arp_gain=0.07,
                   bass=0.3, kick=0.45, hats=0.08),
        sfx={'impact': 1.1, 'whoosh': 1.1, 'swish': 1.2},
        tone='Newsroom: who, what, why it matters. Crisp, factual sentences, no hype words.',
        prefer=['title', 'statement', 'bullets', 'stats', 'quote']),
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
             'accent_free': t['accent_free'], 'tone': t['tone'], 'format': t['format'], 'blueprint': t['blueprint']}
            for k, t in TEMPLATES.items()]
