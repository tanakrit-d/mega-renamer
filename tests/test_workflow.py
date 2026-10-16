import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import server

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        capacity_patch = patch.object(server, 'check_capacity', return_value={
            'fits': True, 'sourceBytes': 100, 'reserveBytes': 1048576,
            'requiredBytes': 1048676, 'availableBytes': 10000000, 'shortfallBytes': 0})
        storage_patch = patch.object(server, 'storage_info', return_value={'availableBytes': 10000000})
        capacity_patch.start()
        storage_patch.start()
        self.addCleanup(capacity_patch.stop)
        self.addCleanup(storage_patch.stop)

    def test_import_manifest_rename_export_order(self):
        calls = []
        dest = '/Imports/abc'
        def mega(name, *args, **kwargs):
            calls.append((name, args))
            if name == 'find':
                if '--type=d' in args:
                    return dest + ' <H:folder01>\n'
                if any(c[0] == 'put' for c in calls):
                    return dest + '/Film.mkv <H:file0001>\n' + dest + '/original-filenames.txt <H:report01>\n'
                return dest + '/Film.WEB-DL.mkv <H:file0001>\n'
            if name == 'put':
                report = Path(args[0]).read_text()
                self.assertIn('Film.WEB-DL.mkv', report)
                self.assertIn('WEB-DL', report)
            if name == 'export':
                return 'Exported: https://mega.nz/file/abc#key\n'
            return ''
        job = {'id': 'abc', 'source': 'https://mega.nz/folder/abc#key', 'files': [],
               'rules': {'version': 1, 'remove': ['WEB-DL'], 'afterResolution': []}}
        with patch.object(server, 'command', side_effect=mega), patch.object(server, 'save'), patch.object(server, 'read_rules', side_effect=AssertionError('Queued job must use its saved rules')):
            server.process(job)
        self.assertEqual(job['status'], 'complete')
        self.assertEqual(job['files'][0]['renamed'], dest + '/Film.mkv')
        self.assertLess([c[0] for c in calls].index('put'), [c[0] for c in calls].index('mv'))
        self.assertEqual(len([c for c in calls if c[0] == 'export']), 3)
        self.assertEqual(next(c[1] for c in calls if c[0] == 'mv'), ('H:file0001', dest + '/Film.mkv'))
        self.assertTrue(all(c[1][-1].startswith('H:') for c in calls if c[0] == 'export'))
        self.assertIn('Import complete.', job['logs'][-1]['message'])

    def test_failure_retains_import(self):
        with patch.object(server, 'command', side_effect=RuntimeError('Import failed')), patch.object(server, 'save'):
            job = {'id': 'abc', 'source': 'https://mega.nz/file/abc#key'}
            server.process(job)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['destination'], '/Imports/abc')

    def test_over_limit_blocks_before_creating_folder(self):
        check = {'fits': False, 'requiredBytes': 2000000, 'availableBytes': 1}
        with patch.object(server, 'check_capacity', return_value=check), patch.object(server, 'command') as command, patch.object(server, 'save'):
            job = {'id': 'abc', 'source': 'https://mega.nz/file/abc#key'}
            server.process(job)
        command.assert_not_called()
        self.assertEqual(job['status'], 'failed')
        self.assertIn('Insufficient cloud storage', job['error'])
        self.assertEqual(job['capacity'], check)

    def test_report_space_checked_before_upload_and_rename(self):
        dest = '/Imports/abc'
        def mega(name, *args, **kwargs):
            if name == 'find':
                return dest + ' <H:folder01>\n' if '--type=d' in args else dest + '/Film.WEB-DL.mkv <H:file0001>\n'
            return ''
        with patch.object(server, 'command', side_effect=mega) as command, patch.object(server, 'storage_info', return_value={'availableBytes': 0}), patch.object(server, 'save'):
            job = {'id': 'abc', 'source': 'https://mega.nz/file/abc#key'}
            server.process(job)
        self.assertEqual(job['status'], 'failed')
        self.assertIn('filename report', job['error'])
        self.assertFalse(any(c.args[0] in ('put', 'mv') for c in command.call_args_list))

    def test_unsupported_path_rejected(self):
        for path in ['/Imports/abc/Film\\a.mkv', '/other/file.mkv', '/Imports/abc/a\nb']:
            with self.assertRaises(RuntimeError):
                server.safe_path(path, '/Imports/abc')

    def test_bracketed_and_wildcard_names_have_handles(self):
        dest = '/Imports/abc'
        for name in ['Film.WEB-DL[TAoE].mkv', 'Film.WEBRip[abc]*?.mkv', 'Folder [group]/Film.WEB-DL.mkv']:
            with self.subTest(name=name):
                calls = []
                def mega(command, *args, **kwargs):
                    calls.append((command, args))
                    if command == 'find':
                        if '--type=d' in args:
                            return dest + ' <H:folder01>\n'
                        if any(c[0] == 'put' for c in calls):
                            return dest + '/original-filenames.txt <H:report01>\n'
                        return dest + '/' + name + ' <H:file0001>\n'
                    if command == 'export':
                        return 'https://mega.nz/file/abc#key'
                    return ''
                job = {'id': 'abc', 'source': 'https://mega.nz/folder/abc#key'}
                with patch.object(server, 'command', side_effect=mega), patch.object(server, 'save'):
                    server.process(job)
                self.assertEqual(job['status'], 'complete')
                self.assertEqual(next(args[0] for cmd, args in calls if cmd == 'mv'), 'H:file0001')
                self.assertTrue(all(args[-1].startswith('H:') for cmd, args in calls if cmd == 'export'))

    def test_listing_rejects_duplicates_and_malformed_lines(self):
        for listing in ['/Imports/abc/file <H:bad>\n', '/Imports/abc/a\nb <H:file0001>\n',
                        '/Imports/abc/a <H:file0001>\n/Imports/abc/a <H:file0002>\n']:
            with self.assertRaises(RuntimeError):
                server.parse_nodes(listing, '/Imports/abc')

    def test_failed_command_exposes_redacted_diagnostic(self):
        job = {'id': 'abc', 'source': 'https://mega.nz/file/abc#private-key'}
        with patch.object(server, 'TOKEN', 'private-token'), patch.object(server, 'save'), patch.object(server.subprocess, 'run') as run:
            run.return_value.returncode = 54
            run.return_value.stderr = 'Access denied https://mega.nz/file/abc#private-key private-key private-token user@example.com'
            with self.assertRaisesRegex(RuntimeError, 'Access denied') as caught:
                server.command('import', job['source'], job=job)
            message = str(caught.exception)
            for secret in ['private-key', 'private-token', 'user@example.com', 'https://mega.nz/']:
                self.assertNotIn(secret, message)
            self.assertIn('exit 54', message)

    def test_timeout_is_actionable(self):
        with patch.object(server.subprocess, 'run', side_effect=server.subprocess.TimeoutExpired('secret', 3)):
            with self.assertRaisesRegex(RuntimeError, 'MEGAcmd import timed out'):
                server.command('import', 'secret')

    def test_logs_are_bounded_and_persisted(self):
        job = {'id': 'abc', 'logs': [{'message': 'old'}] * 500}
        with patch.object(server, 'save') as save:
            server.event(job, 'New entry')
        self.assertEqual(len(job['logs']), 500)
        self.assertEqual(job['logs'][-1]['message'], 'New entry')
        self.assertIn('time', job['logs'][-1])
        save.assert_called_once_with(job)

    def test_logs_survive_database_reload(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)):
            with server.db() as connection:
                connection.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            server.event({'id': 'abc'}, 'Saved failure detail', level='error')
            with server.db() as connection:
                stored = json.loads(connection.execute('SELECT body FROM jobs WHERE id=?', ('abc',)).fetchone()['body'])
            self.assertEqual(stored['logs'][0]['message'], 'Saved failure detail')
            self.assertEqual(stored['logs'][0]['level'], 'error')

    def test_command_uses_argv(self):
        with patch.object(server.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'ok'
            server.command('mv', '/a/$(bad).mkv', '/a/good.mkv')
            self.assertEqual(run.call_args.args[0], ['mega-mv', '/a/$(bad).mkv', '/a/good.mkv'])
            self.assertNotIn('shell', run.call_args.kwargs)

if __name__ == '__main__':
    unittest.main()
