import os
import re
from pathlib import PurePosixPath
from functools import lru_cache
from rules import defaults, validate_rules

@lru_cache(maxsize=32)
def compile_pattern(remove, after_resolution):
    def alternatives(tags):
        return '|'.join(re.escape(tag) for tag in sorted(tags, key=len, reverse=True))
    parts = []
    if remove:
        parts.append(r'(?<![A-Za-z0-9])(?:' + alternatives(remove) + r')(?![A-Za-z0-9])')
    if after_resolution:
        parts.append(r'(?P<resolution>(?<![A-Za-z0-9])\d{3,4}p\.)(?:' + alternatives(after_resolution) + r')(?![A-Za-z0-9])')
    return re.compile('|'.join(parts) if parts else r'(?!)', re.I)

def clean_name(name, rules=None):
    rules = validate_rules(rules) if rules is not None else defaults()
    pattern = compile_pattern(tuple(rules['remove']), tuple(rules['afterResolution']))
    stem, extension = os.path.splitext(name)
    matches = [m.group().removeprefix(m.groupdict().get('resolution') or '') for m in pattern.finditer(stem)]
    if not matches:
        return name, []
    cleaned = pattern.sub(lambda m: m.groupdict().get('resolution') or '', stem)
    cleaned = re.sub(r'([ ._\-])[ ._\-]+', r'\1', cleaned).strip(' ._-')
    return (cleaned or 'untitled') + extension, matches

def plan_names(paths, reserved=(), rules=None):
    rules = validate_rules(rules) if rules is not None else defaults()
    occupied = set(paths) | set(reserved)
    result = []
    for path in sorted(paths):
        p = PurePosixPath(path)
        name, matches = clean_name(p.name, rules=rules)
        target = str(p.with_name(name))
        if target != path:
            base = PurePosixPath(target)
            index = 2
            while target in occupied:
                target = str(base.with_name(f'{base.stem} ({index}){base.suffix}'))
                index += 1
            occupied.add(target)
        result.append({'original': path, 'renamed': target, 'matches': matches})
    return result
