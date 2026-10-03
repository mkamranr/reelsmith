"""Tiny, forgiving syntax highlighter. Good-looking beats correct: it only has to read well for 3 seconds."""
import re
from .lib import TH

KEYWORDS = set("""
import from export default async await function return const let var if else for while in of new class
extends def lambda yield with as try except catch finally raise throw pub fn impl struct enum use mod
match package func go defer interface type public private static void int string bool true false null
None True False nil self this select where insert update delete create table and or not is elif
""".split())

TOKEN = re.compile(r"""
 (?P<str>"[^"]*"?|'[^']*'?|`[^`]*`?)
|(?P<num>\b\d+(\.\d+)?\b)
|(?P<flag>(?<=\s)--?[A-Za-z][\w-]*)
|(?P<tag></?[A-Z][\w.]*)
|(?P<word>[A-Za-z_][\w]*)
|(?P<other>\s+|.)
""", re.X)


def _inline(s, base=None, weight=500):
    base = TH.text if base is None else base
    out = []
    for m in TOKEN.finditer(s):
        g = m.lastgroup; v = m.group()
        if g == 'str': rgb = TH.blue if v.startswith('`') else TH.str
        elif g == 'num': rgb = TH.purple
        elif g == 'flag': rgb = TH.blue
        elif g == 'tag': rgb = TH.tag
        elif g == 'word':
            nxt = s[m.end():m.end() + 1]
            rgb = TH.kw if v in KEYWORDS else TH.purple if nxt == '(' else base
        else: rgb = base
        if out and out[-1][1] == rgb and out[-1][2] == weight: out[-1] = (out[-1][0] + v, rgb, weight)
        else: out.append((v, rgb, weight))
    return out


def highlight(line, lang='code'):
    lang = (lang or 'code').lower()
    s = line.rstrip('\n')
    if not s.strip(): return []
    if lang in ('md', 'markdown'):
        if s.strip() == '---': return [(s, TH.acc, 800)]
        m = re.match(r'^(#{1,6} )(.*)$', s)
        if m: return [(m.group(1), TH.acc, 700), (m.group(2), TH.text, 700)]
        m = re.match(r'^(\s*[-*] )(.*)$', s)
        if m: return [(m.group(1), TH.acc, 500)] + _md_inline(m.group(2))
        if s.startswith('>'): return [(s, TH.muted, 500)]
        if s.startswith('```'): return [(s, TH.comment, 500)]
        m = re.match(r'^([\w-]+)(: ?)(.*)$', s)
        if m: return [(m.group(1), TH.acc2, 500), (m.group(2), TH.comment, 500), (m.group(3), TH.text, 500)]
        return _md_inline(s)
    if lang in ('sh', 'shell', 'bash', 'zsh', 'terminal', 'console'):
        if s.lstrip().startswith('#'): return [(s, TH.comment, 500)]
        if s.startswith('$ '): return [('$ ', TH.acc, 700)] + _inline(s[2:])
        return _inline(s)
    if lang in ('yaml', 'yml', 'toml', 'ini', 'env'):
        if s.lstrip().startswith('#'): return [(s, TH.comment, 500)]
        m = re.match(r'^(\s*[\w.-]+)(\s*[:=]\s*)(.*)$', s)
        if m: return [(m.group(1), TH.acc2, 500), (m.group(2), TH.comment, 500)] + _inline(m.group(3))
        return _inline(s)
    # generic code: strip trailing comment
    m = re.match(r'^(.*?)(\s*(//|#(?!include|!)|--\s).*)$', s)
    if m and not re.search(r'["\']', m.group(2)[:2]):
        return _inline(m.group(1)) + [(m.group(2), TH.comment, 500)]
    return _inline(s)


def _md_inline(s):
    out = []
    for part in re.split(r'(`[^`]*`|\*\*[^*]*\*\*)', s):
        if not part: continue
        if part.startswith('`'): out.append((part, TH.blue, 500))
        elif part.startswith('**'): out.append((part, TH.text, 700))
        else: out.append((part, TH.text, 500))
    return out
