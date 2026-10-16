import hashlib
import sys
import tempfile
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import server

class SessionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for setting in (patch.object(server, 'DATA', Path(tmp.name)), patch.object(server, 'TOKEN', 'test-api-key')):
            setting.start()
            self.addCleanup(setting.stop)
        with server.db() as c:
            c.execute('CREATE TABLE browser_sessions (id_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL, token_hash TEXT NOT NULL)')

    def handler(self, cookie=None, method='GET', **headers):
        handler = object.__new__(server.Handler)
        handler.headers = {'Host': 'localhost:8080', **headers}
        if cookie:
            handler.headers['Cookie'] = cookie
        handler.command = method
        handler.reply = Mock()
        return handler

    def login(self):
        handler = self.handler(Authorization='Bearer test-api-key')
        self.assertTrue(handler.authorized())
        handler.create_session()
        raw = handler.reply.call_args.kwargs['cookie']
        parsed = SimpleCookie()
        parsed.load(raw)
        return f'{server.SESSION_COOKIE}={parsed[server.SESSION_COOKIE].value}', raw

    def test_persisted_cookie_restores_session_without_api_key(self):
        cookie, raw = self.login()
        self.assertIn('HttpOnly', raw)
        self.assertIn('SameSite=Strict', raw)
        self.assertIn('Max-Age=2592000', raw)
        self.assertIn('Path=/api', raw)
        self.assertTrue(self.handler(cookie).authorized())
        with server.db() as c:
            row = c.execute('SELECT * FROM browser_sessions').fetchone()
        self.assertNotIn(cookie.split('=', 1)[1], tuple(row))
        self.assertNotIn('test-api-key', tuple(row))

    def test_logout_revokes_cookie_on_server(self):
        cookie, _ = self.login()
        handler = self.handler(cookie, method='DELETE')
        handler.path = '/api/session'
        handler.do_DELETE()
        self.assertIn('Max-Age=0', handler.reply.call_args.kwargs['cookie'])
        self.assertFalse(self.handler(cookie).authorized())

    def test_expired_and_tampered_cookies_rejected(self):
        cookie, _ = self.login()
        self.assertFalse(self.handler(cookie[:-1] + ('A' if cookie[-1] != 'A' else 'B')).authorized())
        with server.db() as c:
            c.execute('UPDATE browser_sessions SET expires=?', (int(time.time()) - 1,))
        self.assertFalse(self.handler(cookie).authorized())

    def test_changing_api_key_invalidates_saved_session(self):
        cookie, _ = self.login()
        with patch.object(server, 'TOKEN', 'replacement-api-key'):
            self.assertFalse(self.handler(cookie).authorized())

    def test_cross_origin_cookie_mutations_rejected(self):
        cookie, _ = self.login()
        handler = self.handler(cookie, method='PUT', Origin='https://other.example')
        self.assertFalse(handler.authorized())
        self.assertEqual(handler.reply.call_args.args[0], 403)
        self.assertTrue(self.handler(cookie, method='PUT', Origin='http://localhost:8080').authorized())

    def test_invalid_bearer_does_not_fall_back_to_cookie(self):
        cookie, _ = self.login()
        self.assertFalse(self.handler(cookie, Authorization='Bearer incorrect').authorized())

    def test_https_proxy_sets_secure_cookie(self):
        handler = self.handler(**{'X-Forwarded-Proto': 'https'})
        self.assertIn('Secure', handler.cookie_header('a' * 43))

if __name__ == '__main__':
    unittest.main()
