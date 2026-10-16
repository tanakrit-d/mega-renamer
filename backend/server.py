import hmac
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit
from renamer import plan_names
from cloud import validate_link, parse_storage, link_metadata, capacity
from rules import read_rules, write_rules, initialize_rules

DATA = Path(os.environ.get('DATA_DIR', '/data'))
TOKEN = os.environ.get('API_TOKEN', '')
ROOT = os.environ.get('MEGA_DESTINATION', '/Imports').rstrip('/')
STATIC = os.environ.get('STATIC_DIR', '/app/web/dist')
JOBS = queue.Queue(maxsize=100)
ACCOUNT_LOCK = threading.Lock()
STORAGE_LOCK = threading.Lock()
STORAGE_CACHE = None
STORAGE_TIME = 0
TERMINAL = ('complete', 'failed', 'trashed', 'deleted')
SESSION_COOKIE = 'mega_renamer_session'
SESSION_AGE = 30 * 24 * 60 * 60
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

@contextmanager
def db():
    connection = sqlite3.connect(DATA / 'jobs.sqlite3', timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def save(job):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (job['id'], json.dumps(job)))

def redact(text, job=None):
    secrets = [TOKEN]
    if job and job.get('source'):
        source = job['source']
        secrets += [source, source.rsplit('#', 1)[-1]]
        if '!' in source:
            secrets.append(source.rsplit('!', 1)[-1])
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'https?://[^\s<>]+', '[URL redacted]', text)
    text = re.sub(r'\b[^\s@]+@[^\s@]+\.[^\s@]+', '[email redacted]', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)[:2000]

def event(job, message, level='info'):
    message = redact(message, job)
    job.setdefault('logs', []).append({'time': datetime.now(timezone.utc).isoformat(),
                                       'level': level, 'message': message})
    job['logs'] = job['logs'][-500:]
    logging.log(logging.ERROR if level == 'error' else logging.INFO,
                'job=%s %s', job['id'], message)
    save(job)

def command(name, *args, job=None):
    # Arguments and successful output may contain link keys: never log them.
    if job:
        event(job, f'Running MEGAcmd {name}.')
    try:
        result = subprocess.run(['mega-' + name, *args], capture_output=True, text=True,
                                timeout=int(os.environ.get('MEGA_TIMEOUT', '1800')))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'MEGAcmd {name} timed out.') from None
    if result.returncode:
        detail = redact((result.stderr or result.stdout or 'No diagnostic output.').strip(), job)
        raise RuntimeError(f'MEGAcmd {name} failed (exit {result.returncode}): {detail}')
    if job:
        event(job, f'MEGAcmd {name} completed.')
    return result.stdout

def storage_info(fresh=False):
    global STORAGE_CACHE, STORAGE_TIME
    with STORAGE_LOCK:
        if fresh or STORAGE_CACHE is None or time.monotonic() - STORAGE_TIME > 30:
            STORAGE_CACHE = {**parse_storage(command('df')), 'checkedAt': datetime.now(timezone.utc).isoformat()}
            STORAGE_TIME = time.monotonic()
        return dict(STORAGE_CACHE)

def invalidate_storage():
    global STORAGE_TIME
    with STORAGE_LOCK:
        STORAGE_TIME = 0

def check_capacity(source):
    storage = storage_info(fresh=True)
    return capacity(link_metadata(source), storage)

def safe_path(path, destination):
    # Source/export operations use handles. Destinations are resolved literally
    # by mega-mv, but escaped path components and multiline listings need care.
    if not path.startswith(destination + '/') or any(c in path for c in '\\:\r\n'):
        raise RuntimeError('An imported filename cannot safely be addressed by MEGAcmd. The import is retained for manual review.')
    return path

def parse_nodes(output, destination, validate_paths=True):
    nodes = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'(.+) <(H:[A-Za-z0-9_-]{8})>', line)
        if not match:
            raise RuntimeError('Cannot parse the MEGAcmd node listing safely. The import is retained for manual review.')
        path, handle = match.groups()
        if path != destination and validate_paths:
            safe_path(path, destination)
        elif path != destination and not path.startswith(destination + '/'):
            raise RuntimeError('Node listing contains a path outside the expected folder.')
        if path in nodes:
            raise RuntimeError('Duplicate filenames found in the same folder. The import is retained for manual review.')
        nodes[path] = handle
    return nodes

def export(handle, job=None):
    output = command('export', '-a', '-f', handle, job=job)
    links = re.findall(r'https://mega\.nz/[^\s]+', output)
    if not links:
        raise RuntimeError('MEGAcmd did not return a public link.')
    return links[-1]

def process(job):
    destination = ROOT + '/' + job['id']
    job['destination'] = destination
    job['importCreated'] = False
    run = lambda name, *args: command(name, *args, job=job)
    try:
        if 'rules' not in job:
            job['rules'] = read_rules(DATA)
        job.update(status='checking', progress=5)
        event(job, 'Checking public-link size and available account storage.')
        job['capacity'] = check_capacity(job['source'])
        if not job['capacity']['fits']:
            raise RuntimeError(f"Insufficient cloud storage: import requires {job['capacity']['requiredBytes']} bytes including report reserve, but only {job['capacity']['availableBytes']} bytes are available. No files were imported.")
        event(job, f"Storage check passed: {job['capacity']['sourceBytes']} bytes of files plus {job['capacity']['reserveBytes']} bytes reserved for the filename report.")
        job.update(status='importing', progress=10)
        event(job, 'Import started.')
        run('mkdir', '-p', destination)
        job['importCreated'] = True
        save(job)
        run('import', job['source'], destination)
        nodes = parse_nodes(run('find', destination, '--type=f', '--show-handles'), destination)
        paths = list(nodes)
        if not paths:
            raise RuntimeError('No files found in this import.')
        folder_nodes = parse_nodes(run('find', destination, '--type=d', '--show-handles'), destination)
        if destination not in folder_nodes:
            raise RuntimeError('Import folder handle is missing from the MEGAcmd listing.')
        job['folderHandle'] = folder_nodes[destination]
        folders = [p for p in folder_nodes if p != destination]
        entries = plan_names(paths, reserved=folders, rules=job['rules'])
        for entry in entries:
            entry['handle'] = nodes[entry['original']]
        job.update(status='renaming', progress=35, files=entries)
        event(job, f'Found {len(entries)} files. Saving the original-name report before renaming.')
        report_name = 'original-filenames.txt'
        reserved = set(paths + folders + [e['renamed'] for e in entries])
        while destination + '/' + report_name in reserved:
            report_name = 'original-' + report_name
        # Upload the audit report before modifying any original names.
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / report_name
            report.write_text('MEGA Renamer — original filename manifest\n'
                              + '\n'.join(json.dumps({k: v for k, v in e.items()}, ensure_ascii=False)
                                          for e in entries) + '\n', encoding='utf-8')
            if report.stat().st_size > storage_info(fresh=True)['availableBytes']:
                raise RuntimeError('The import succeeded, but there is insufficient remaining space for its filename report. Files are retained without renaming.')
            run('put', str(report), folder_nodes[destination])
        for i, entry in enumerate(entries):
            if entry['original'] != entry['renamed']:
                run('mv', entry['handle'], entry['renamed'])
            event(job, f"File {i + 1}/{len(entries)}: {json.dumps(entry['renamed'], ensure_ascii=True)}; removed tags: {', '.join(entry['matches']) or 'none'}.")
            job['progress'] = 35 + int(35 * (i + 1) / len(entries))
            save(job)
        job['status'] = 'exporting'
        event(job, 'Generating public file links.')
        for entry in entries:
            entry['url'] = export(entry['handle'], job=job)
            save(job)
        current_nodes = parse_nodes(run('find', destination, '--type=f', '--show-handles'), destination)
        report_handle = current_nodes.get(destination + '/' + report_name)
        if not report_handle:
            raise RuntimeError('Uploaded filename report was not found.')
        job['manifestUrl'] = export(report_handle, job=job)
        job['folderUrl'] = export(folder_nodes[destination], job=job)
        job.update(status='complete', progress=100)
        event(job, f'Import complete. Generated links for {len(entries)} files and the filename report.')
    except Exception as error:
        job.update(status='failed', error=redact(str(error), job))
        event(job, job['error'], level='error')
    invalidate_storage()
    save(job)

def clear_links(job):
    job.pop('folderUrl', None)
    job.pop('manifestUrl', None)
    for entry in job.get('files', []):
        entry.pop('url', None)

def load_job(job_id):
    with db() as c:
        row = c.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
    return json.loads(row['body']) if row else None

def trash_import(job):
    if job['status'] not in ('complete', 'failed'):
        raise ValueError('Only completed or failed imports can be moved to trash.')
    destination = ROOT + '/' + job['id']
    nodes = parse_nodes(command('find', destination, '--type=d', '--show-handles', job=job), destination)
    handle = nodes.get(destination)
    if not handle:
        raise RuntimeError('The import folder no longer exists at its expected destination.')
    command('mv', handle, '//bin', job=job)
    job.update(status='trashed', folderHandle=handle)
    clear_links(job)
    event(job, 'Import moved to account trash. Space is released only after emptying the trash.')
    invalidate_storage()

def empty_trash():
    # Delete top-level nodes by handle; never pass the bin itself to mega-rm.
    nodes = parse_nodes(command('find', '//bin', '--show-handles'), '//bin', validate_paths=False)
    roots = [(path, handle) for path, handle in nodes.items()
             if path != '//bin' and '/' not in path[len('//bin/'):]]
    deleted = 0
    for _, handle in roots:
        command('rm', '-r', '-f', handle)
        deleted += 1
        with db() as c:
            rows = c.execute('SELECT body FROM jobs').fetchall()
        for row in rows:
            job = json.loads(row['body'])
            if job['status'] == 'trashed' and job.get('folderHandle') == handle:
                job['status'] = 'deleted'
                clear_links(job)
                event(job, 'Import permanently deleted when the account trash was emptied.')
        invalidate_storage()
    return {'deletedItems': deleted}

def worker():
    while True:
        job = JOBS.get()
        with ACCOUNT_LOCK:
            process(job)
        JOBS.task_done()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC, **kwargs)

    def log_message(self, format, *args):
        pass

    def reply(self, status, body, cookie=None):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self):
        authorization = self.headers.get('Authorization')
        if TOKEN and authorization is not None:
            if hmac.compare_digest(authorization.encode(), ('Bearer ' + TOKEN).encode()):
                return True
        elif TOKEN:
            session = self.session_id()
            if session:
                with db() as c:
                    row = c.execute('SELECT expires, token_hash FROM browser_sessions WHERE id_hash=?',
                                    (hashlib.sha256(session.encode()).hexdigest(),)).fetchone()
                if row and row['expires'] > time.time() and hmac.compare_digest(row['token_hash'], hashlib.sha256(TOKEN.encode()).hexdigest()):
                    if self.command not in ('GET', 'HEAD'):
                        origin = self.headers.get('Origin')
                        if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                            self.reply(403, {'error': 'Browser session requests must come from this workspace.'})
                            return False
                    return True
        self.reply(401, {'error': 'Enter the configured API token to connect.'})
        return False

    def session_id(self):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            value = cookie.get(SESSION_COOKIE)
            return value.value if value and re.fullmatch(r'[A-Za-z0-9_-]{43}', value.value) else None
        except Exception:
            return None

    def cookie_header(self, value, age=SESSION_AGE):
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE] = value
        cookie[SESSION_COOKIE]['path'] = '/api'
        cookie[SESSION_COOKIE]['max-age'] = age
        cookie[SESSION_COOKIE]['httponly'] = True
        cookie[SESSION_COOKIE]['samesite'] = 'Strict'
        if self.headers.get('X-Forwarded-Proto', '').lower() == 'https':
            cookie[SESSION_COOKIE]['secure'] = True
        return cookie.output(header='').strip()

    def create_session(self):
        session = secrets.token_urlsafe(32)
        with db() as c:
            c.execute('DELETE FROM browser_sessions WHERE expires<=?', (int(time.time()),))
            previous = self.session_id()
            if previous:
                c.execute('DELETE FROM browser_sessions WHERE id_hash=?', (hashlib.sha256(previous.encode()).hexdigest(),))
            c.execute('INSERT INTO browser_sessions VALUES (?, ?, ?)',
                      (hashlib.sha256(session.encode()).hexdigest(), int(time.time()) + SESSION_AGE,
                       hashlib.sha256(TOKEN.encode()).hexdigest()))
        self.reply(200, {'authenticated': True}, cookie=self.cookie_header(session))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/health':
            self.reply(200, {'status': 'ok'})
        elif path.startswith('/api/'):
            if not self.authorized():
                return
            if path == '/api/session':
                self.reply(200, {'authenticated': True})
            elif path == '/api/account':
                try:
                    command('whoami')
                    self.reply(200, {'connected': True})
                except Exception:
                    self.reply(200, {'connected': False})
            elif path == '/api/rules':
                try:
                    self.reply(200, read_rules(DATA))
                except Exception as error:
                    self.reply(503, {'error': redact(str(error))})
            elif path == '/api/storage':
                try:
                    self.reply(200, storage_info())
                except Exception as error:
                    self.reply(503, {'error': redact(str(error))})
            elif path == '/api/jobs' or re.fullmatch(r'/api/jobs/[a-f0-9]{32}', path):
                with db() as c:
                    if path == '/api/jobs':
                        rows = c.execute('SELECT body FROM jobs ORDER BY rowid DESC LIMIT 30').fetchall()
                        self.reply(200, [json.loads(r['body']) for r in rows])
                    else:
                        row = c.execute('SELECT body FROM jobs WHERE id=?', (path.rsplit('/', 1)[-1],)).fetchone()
                        self.reply(200 if row else 404, json.loads(row['body']) if row else {'error': 'Job not found'})
            else:
                self.reply(404, {'error': 'Not found'})
        else:
            super().do_GET()

    def do_POST(self):
        if not self.authorized():
            return
        if self.path == '/api/session':
            return self.create_session()
        action_match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(trash|trash-empty)', self.path)
        if self.path not in ('/api/jobs', '/api/import-check', '/api/trash/empty') and not action_match:
            return self.reply(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > 8192:
                raise ValueError('Request must be between 1 and 8192 bytes.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Request must be a JSON object.')
            if action_match or self.path == '/api/trash/empty':
                return self.manage_import(action_match, body)
            source = validate_link(body.get('url', ''))
            if self.path == '/api/import-check':
                return self.reply(200, check_capacity(source))
            if JOBS.full():
                return self.reply(429, {'error': 'The queue is full. Try again later.'})
            job = {'id': uuid.uuid4().hex, 'source': source, 'status': 'queued', 'progress': 0, 'files': [], 'logs': [], 'rules': read_rules(DATA)}
            event(job, 'Import queued.')
            JOBS.put_nowait(job)
            self.reply(202, job)
        except (ValueError, AttributeError, TypeError) as error:
            self.reply(400, {'error': str(error)})
        except Exception as error:
            self.reply(503, {'error': redact(str(error))})

    def do_PUT(self):
        if not self.authorized():
            return
        if self.path != '/api/rules':
            return self.reply(404, {'error': 'Not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size < 1 or size > 32768:
                raise ValueError('Rules request must be between 1 and 32768 bytes.')
            value = json.loads(self.rfile.read(size))
            self.reply(200, write_rules(DATA, value))
        except (ValueError, TypeError) as error:
            self.reply(400, {'error': str(error)})
        except Exception as error:
            self.reply(503, {'error': redact(str(error))})

    def do_DELETE(self):
        if not self.authorized():
            return
        if self.path == '/api/session':
            session = self.session_id()
            if session:
                with db() as c:
                    c.execute('DELETE FROM browser_sessions WHERE id_hash=?', (hashlib.sha256(session.encode()).hexdigest(),))
            return self.reply(200, {'authenticated': False}, cookie=self.cookie_header('', age=0))
        match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})', self.path)
        if self.path != '/api/jobs' and not match:
            return self.reply(404, {'error': 'Not found'})
        # Avoid a worker or cloud action saving a record again after deletion.
        if not ACCOUNT_LOCK.acquire(blocking=False):
            return self.reply(409, {'error': 'An import or trash operation is running. Try again after it finishes.'})
        try:
            with db() as c:
                if match:
                    row = c.execute('SELECT body FROM jobs WHERE id=?', (match[1],)).fetchone()
                    if not row:
                        return self.reply(404, {'error': 'Job not found'})
                    if json.loads(row['body'])['status'] not in TERMINAL:
                        return self.reply(409, {'error': 'Queued or running imports cannot be removed from history.'})
                    ids = [match[1]]
                else:
                    rows = c.execute('SELECT id, body FROM jobs').fetchall()
                    ids = [row['id'] for row in rows if json.loads(row['body'])['status'] in TERMINAL]
                c.executemany('DELETE FROM jobs WHERE id=?', [(job_id,) for job_id in ids])
            self.reply(200, {'removedRecords': len(ids)})
        except Exception as error:
            self.reply(503, {'error': redact(str(error))})
        finally:
            ACCOUNT_LOCK.release()

    def manage_import(self, action_match, body):
        full_empty = not action_match or action_match[2] == 'trash-empty'
        if full_empty and body.get('confirm') != 'EMPTY_ACCOUNT_TRASH':
            return self.reply(400, {'error': 'Confirm emptying the entire account trash with confirm: EMPTY_ACCOUNT_TRASH.'})
        if not ACCOUNT_LOCK.acquire(blocking=False):
            return self.reply(409, {'error': 'An import or trash operation is running. Try again after it finishes.'})
        job = None
        try:
            if action_match:
                job = load_job(action_match[1])
                if not job:
                    return self.reply(404, {'error': 'Job not found'})
                if job['status'] not in TERMINAL:
                    return self.reply(409, {'error': 'This import is still processing.'})
                if job['status'] == 'deleted' or (job['status'] == 'trashed' and not full_empty):
                    return self.reply(409, {'error': 'This import has already been moved to trash or deleted.'})
                if job['status'] != 'trashed':
                    trash_import(job)
            result = empty_trash() if full_empty else {}
            if job:
                result['job'] = load_job(job['id'])
            self.reply(200, result)
        except Exception as error:
            message = redact(str(error), job)
            if job:
                event(job, message, level='error')
            self.reply(502, {'error': message})
        finally:
            invalidate_storage()
            ACCOUNT_LOCK.release()

def main():
    if not TOKEN:
        raise SystemExit('API_TOKEN is required. Set a long random token before starting.')
    DATA.mkdir(parents=True, exist_ok=True)
    initialize_rules(DATA)
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS browser_sessions (id_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL, token_hash TEXT NOT NULL)')
        for row in c.execute('SELECT body FROM jobs').fetchall():
            job = json.loads(row['body'])
            if job['status'] not in TERMINAL:
                job.update(status='failed', error='Service restarted. Imported files are retained; inspect the destination before resubmitting.')
                job.setdefault('logs', []).append({'time': datetime.now(timezone.utc).isoformat(),
                                                   'level': 'error', 'message': job['error']})
                job['logs'] = job['logs'][-500:]
                c.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job), job['id']))
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()

if __name__ == '__main__':
    main()
