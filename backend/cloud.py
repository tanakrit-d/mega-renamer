"""Storage parsing and public-link metadata, without changing account sessions."""
import json
import re
import urllib.error
import urllib.request

LINK = re.compile(r'https://mega\.nz/(?:(file|folder)/([\w-]+)#([\w-]+)|(#F!|#!)([\w-]+)!([\w-]+))')

def validate_link(source):
    if not isinstance(source, str) or not LINK.fullmatch(source.strip()):
        raise ValueError('Provide a MEGA file or folder URL including its decryption key.')
    return source.strip()

def parse_storage(output):
    # Without -h, MEGAcmd reports exact bytes, including account rubbish/versions.
    used = re.search(r'^USED STORAGE:\s*(\d+)\s*(?:B|Bytes)?\s+.*?\bof\s+(\d+)\s*(?:B|Bytes)?\s*$', output, re.M | re.I)
    trash = re.search(r'^Rubbish bin:\s*(\d+)', output, re.M | re.I)
    if not used or not trash:
        raise RuntimeError('Cannot read exact storage values from MEGAcmd df. Imports are blocked until storage can be checked.')
    used_bytes, total_bytes = map(int, used.groups())
    return {'usedBytes': used_bytes, 'totalBytes': total_bytes,
            'availableBytes': max(0, total_bytes - used_bytes), 'trashBytes': int(trash.group(1))}

def link_metadata(source):
    match = LINK.fullmatch(validate_link(source))
    folder = match.group(1) == 'folder' or match.group(4) == '#F!'
    handle = match.group(2) or match.group(5)
    # These are the requests used by MEGA's official webclient LinkInfoHelper.
    payload = {'a': 'pli', 'ph': handle} if folder else {'a': 'g', 'p': handle}
    request = urllib.request.Request('https://g.api.mega.co.nz/cs?id=0',
                                     data=json.dumps([payload]).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Metadata response too large')
        result = json.loads(raw)
        if not isinstance(result, list) or len(result) != 1:
            raise ValueError('Unexpected metadata response')
        info = result[0]
        if isinstance(info, int):
            raise RuntimeError(f'MEGA could not inspect the public link (API error {info}). Check that the link is available.')
        size = info['s'][0] if folder else info['s']
        count = info['s'][1] if folder else 1
        if type(size) is not int or size < 0 or type(count) is not int or count < 0:
            raise ValueError('Invalid metadata size')
        return {'sourceBytes': size, 'fileCount': count}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise RuntimeError('Cannot inspect the public link size. Try again or check the link; no files have been imported.') from error

def capacity(metadata, storage):
    reserve = max(1024 * 1024, metadata['fileCount'] * 4096)
    required = metadata['sourceBytes'] + reserve
    available = storage['availableBytes']
    return {**metadata, 'reserveBytes': reserve, 'requiredBytes': required,
            'availableBytes': available, 'fits': required <= available,
            'shortfallBytes': max(0, required - available)}
