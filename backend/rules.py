import json
import os
import tempfile
import threading
from pathlib import Path

DEFAULT_FILE = Path(__file__).with_name('naming-rules.json')
LOCK = threading.RLock()

def validate_rules(value):
    if not isinstance(value, dict) or set(value) != {'version', 'remove', 'afterResolution'}:
        raise ValueError('Rules must contain version, remove, and afterResolution only.')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Rules version must be 1.')
    result = {'version': 1}
    seen = set()
    for field in ('remove', 'afterResolution'):
        tags = value[field]
        if not isinstance(tags, list) or len(tags) > 200:
            raise ValueError(f'{field} must be a list of at most 200 strings.')
        result[field] = []
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip() or len(tag) > 128:
                raise ValueError('Each filtered string must contain 1–128 characters.')
            tag = tag.strip()
            if '/' in tag or any(not c.isprintable() for c in tag):
                raise ValueError('Filtered strings cannot contain slashes or control characters.')
            if tag.casefold() in seen:
                raise ValueError(f'Duplicate filtered string: {tag}')
            seen.add(tag.casefold())
            result[field].append(tag)
    return result

def defaults():
    return validate_rules(json.loads(DEFAULT_FILE.read_text(encoding='utf-8')))

def read_rules(data_dir):
    with LOCK:
        path = Path(data_dir) / 'naming-rules.json'
        if not path.exists():
            return defaults()
        return validate_rules(json.loads(path.read_text(encoding='utf-8')))

def write_rules(data_dir, value):
    value = validate_rules(value)
    directory = Path(data_dir)
    with LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                             prefix='.naming-rules-', delete=False) as file:
                temporary = file.name
                json.dump(value, file, indent=2, ensure_ascii=False)
                file.write('\n')
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, directory / 'naming-rules.json')
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return value

def initialize_rules(data_dir):
    with LOCK:
        if not (Path(data_dir) / 'naming-rules.json').exists():
            write_rules(data_dir, defaults())
        return read_rules(data_dir)
