"""Run in the built container with tests mounted at /checks; no account required."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import http.cookiejar

process = subprocess.Popen(['/app/entrypoint.sh'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:8080'

def request(path, data=None, token=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()

try:
    for attempt in range(50):
        try:
            status, body = request('/api/health')
            break
        except OSError:
            time.sleep(.1)
    assert status == 200 and json.loads(body)['status'] == 'ok'
    assert request('/api/jobs')[0] == 401
    assert request('/api/jobs', token='incorrect')[0] == 401
    assert request('/api/storage')[0] == 401
    token = os.environ['API_TOKEN']
    # Use a cookie jar as a browser would; no API token on restored requests.
    jar = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = urllib.request.Request(base + '/api/session', method='POST', headers={'Authorization': 'Bearer ' + token})
    assert browser.open(login, timeout=10).status == 200
    assert browser.open(base + '/api/session', timeout=10).status == 200
    assert browser.open(base + '/api/jobs', timeout=10).status == 200
    logout = urllib.request.Request(base + '/api/session', method='DELETE')
    assert browser.open(logout, timeout=10).status == 200
    try:
        browser.open(base + '/api/session', timeout=10)
        raise AssertionError('Logged-out session must be rejected')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    assert request('/api/rules')[0] == 401
    status, body = request('/api/rules', token=token)
    assert status == 200
    original_rules = json.loads(body)
    custom_rules = {'version': 1, 'remove': ['CUSTOM'], 'afterResolution': ['SOURCE.DTS']}
    assert request('/api/rules', custom_rules, method='PUT')[0] == 401
    assert request('/api/rules', custom_rules, token=token, method='PUT')[0] == 200
    assert json.loads(request('/api/rules', token=token)[1]) == custom_rules
    assert request('/api/rules', {'version': 1}, token=token, method='PUT')[0] == 400
    assert json.loads(request('/api/rules', token=token)[1]) == custom_rules
    assert request('/api/rules', original_rules, token=token, method='PUT')[0] == 200
    assert request('/api/jobs', token=token) == (200, b'[]')
    assert request('/api/jobs', {'url': 'https://example.com'}, token=token)[0] == 400
    assert request('/api/jobs/' + 'a' * 32, token=token)[0] == 404
    assert request('/')[0] == 200
    assert b'MEGA Renamer' in request('/')[1]
    assert request('/api/account', token=token)[0] == 200
    assert request('/api/storage', token=token)[0] == 503
    assert request('/api/import-check', {'url': 'https://example.com'}, token=token)[0] == 400
    assert request('/api/trash/empty', {}, token=token)[0] == 400
    # This isolated container has no account session: verify a real command
    # failure is persisted and returned through the authenticated job API.
    status, body = request('/api/jobs', {'url': 'https://mega.nz/file/abc#smoke-key'}, token=token)
    assert status == 202
    job = json.loads(body)
    assert job['rules'] == original_rules
    for attempt in range(50):
        _, body = request('/api/jobs/' + job['id'], token=token)
        job = json.loads(body)
        if job['status'] == 'failed':
            break
        time.sleep(.1)
    assert job['status'] == 'failed'
    assert 'MEGAcmd df failed' in job['error']
    assert job['logs'][-1]['level'] == 'error'
    assert 'smoke-key' not in json.dumps(job['logs'])
    assert request('/api/jobs/' + job['id'], method='DELETE')[0] == 401
    assert request('/api/jobs/' + job['id'], token=token, method='DELETE')[0] == 200
    assert request('/api/jobs/' + job['id'], token=token)[0] == 404
    assert request('/api/jobs', token=token) == (200, b'[]')
    assert request('/api/jobs', token=token, method='DELETE')[0] == 200
    assert subprocess.run(['mega-version'], capture_output=True, timeout=10).returncode == 0
    print('Container smoke checks passed: health, auth, API validation, UI serving, MEGAcmd executable, persisted failure logs.')
finally:
    process.terminate()
    process.wait(timeout=10)
