import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import server

class HistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = patch.object(server, 'DATA', Path(tmp.name))
        data.start()
        self.addCleanup(data.stop)
        with server.db() as connection:
            connection.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)')

    def delete(self, path):
        handler = object.__new__(server.Handler)
        handler.path = path
        handler.authorized = Mock(return_value=True)
        handler.reply = Mock()
        with patch.object(server, 'command') as command:
            handler.do_DELETE()
        command.assert_not_called()
        return handler.reply.call_args.args

    def test_remove_one_record_preserves_other_history(self):
        for i in range(2):
            server.save({'id': f'{i:032x}', 'status': 'complete', 'logs': [], 'files': []})
        self.assertEqual(self.delete('/api/jobs/' + '0' * 32), (200, {'removedRecords': 1}))
        self.assertIsNone(server.load_job('0' * 32))
        self.assertIsNotNone(server.load_job(f'{1:032x}'))

    def test_clear_includes_old_records_beyond_visible_limit_and_keeps_queue(self):
        for i in range(40):
            server.save({'id': f'{i:032x}', 'status': server.TERMINAL[i % 4]})
        server.save({'id': 'f' * 32, 'status': 'queued'})
        self.assertEqual(self.delete('/api/jobs'), (200, {'removedRecords': 40}))
        with server.db() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
        self.assertEqual(server.load_job('f' * 32)['status'], 'queued')

    def test_queue_and_running_records_cannot_be_removed(self):
        for status in ('queued', 'checking', 'importing', 'renaming', 'exporting'):
            server.save({'id': 'a' * 32, 'status': status})
            self.assertEqual(self.delete('/api/jobs/' + 'a' * 32)[0], 409)
            self.assertIsNotNone(server.load_job('a' * 32))

    def test_delete_blocked_while_cloud_operation_running(self):
        server.save({'id': 'a' * 32, 'status': 'complete'})
        with server.ACCOUNT_LOCK:
            self.assertEqual(self.delete('/api/jobs')[0], 409)
        self.assertIsNotNone(server.load_job('a' * 32))

    def test_missing_record_and_empty_history(self):
        self.assertEqual(self.delete('/api/jobs/' + 'a' * 32)[0], 404)
        self.assertEqual(self.delete('/api/jobs'), (200, {'removedRecords': 0}))

if __name__ == '__main__':
    unittest.main()
