import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import server

class TrashTests(unittest.TestCase):
    def test_trash_moves_whole_import_by_handle_without_permanent_delete(self):
        job = {'id': 'abc', 'status': 'complete', 'folderUrl': 'secret', 'manifestUrl': 'secret', 'files': [{'url': 'secret'}]}
        with patch.object(server, 'command', return_value='/Imports/abc <H:folder01>\n') as command, patch.object(server, 'save'):
            server.trash_import(job)
        self.assertEqual(job['status'], 'trashed')
        self.assertEqual(job['folderHandle'], 'H:folder01')
        self.assertEqual(command.call_args_list[-1].args, ('mv', 'H:folder01', '//bin'))
        self.assertNotIn('folderUrl', job)
        self.assertNotIn('url', job['files'][0])
        self.assertFalse(any(c.args[0] == 'rm' for c in command.call_args_list))

    def test_active_import_cannot_be_trashed(self):
        with patch.object(server, 'command') as command:
            with self.assertRaises(ValueError):
                server.trash_import({'id': 'abc', 'status': 'importing'})
        command.assert_not_called()

    def test_missing_folder_does_not_delete_anything(self):
        with patch.object(server, 'command', return_value='') as command, patch.object(server, 'save'):
            with self.assertRaises(RuntimeError):
                server.trash_import({'id': 'abc', 'status': 'failed'})
        self.assertEqual(len(command.call_args_list), 1)

    def test_empty_only_removes_top_level_handles_and_updates_jobs(self):
        listing = '//bin <H:bin00001>\n//bin/abc <H:folder01>\n//bin/abc/[file].mkv <H:file0001>\n//bin/other.txt <H:file0002>\n'
        job = {'id': 'abc', 'status': 'trashed', 'folderHandle': 'H:folder01'}
        with patch.object(server, 'command', return_value=listing) as command, patch.object(server, 'db') as db, patch.object(server, 'save') as save:
            db.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [{'body': json.dumps(job)}]
            result = server.empty_trash()
        deleted = [call.args for call in command.call_args_list if call.args[0] == 'rm']
        self.assertEqual(deleted, [('rm', '-r', '-f', 'H:folder01'), ('rm', '-r', '-f', 'H:file0002')])
        self.assertEqual(result['deletedItems'], 2)
        self.assertEqual(save.call_args.args[0]['status'], 'deleted')

    def test_empty_bin_is_noop(self):
        with patch.object(server, 'command', return_value='//bin <H:bin00001>\n') as command:
            self.assertEqual(server.empty_trash(), {'deletedItems': 0})
        self.assertEqual(len(command.call_args_list), 1)

    def test_empty_requires_confirmation(self):
        handler = object.__new__(server.Handler)
        handler.reply = unittest.mock.Mock()
        with patch.object(server, 'empty_trash') as empty:
            handler.manage_import(None, {})
        self.assertEqual(handler.reply.call_args.args[0], 400)
        empty.assert_not_called()

    def test_management_rejected_while_import_running(self):
        handler = object.__new__(server.Handler)
        handler.reply = unittest.mock.Mock()
        with server.ACCOUNT_LOCK, patch.object(server, 'empty_trash') as empty:
            handler.manage_import(None, {'confirm': 'EMPTY_ACCOUNT_TRASH'})
        self.assertEqual(handler.reply.call_args.args[0], 409)
        empty.assert_not_called()

    def test_combined_action_trashes_before_emptying(self):
        handler = object.__new__(server.Handler)
        handler.reply = unittest.mock.Mock()
        match = server.re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(trash|trash-empty)', '/api/jobs/' + 'a' * 32 + '/trash-empty')
        calls = []
        job = {'id': 'a' * 32, 'status': 'complete'}
        def trash(job):
            calls.append('trash')
            job['status'] = 'trashed'
        def empty():
            calls.append('empty')
            job['status'] = 'deleted'
            return {'deletedItems': 1}
        with patch.object(server, 'load_job', return_value=job), patch.object(server, 'trash_import', side_effect=trash), patch.object(server, 'empty_trash', side_effect=empty):
            handler.manage_import(match, {'confirm': 'EMPTY_ACCOUNT_TRASH'})
        self.assertEqual(calls, ['trash', 'empty'])
        self.assertEqual(handler.reply.call_args.args[1]['job']['status'], 'deleted')

    def test_combined_action_does_not_empty_if_trash_fails(self):
        handler = object.__new__(server.Handler)
        handler.reply = unittest.mock.Mock()
        match = server.re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(trash|trash-empty)', '/api/jobs/' + 'a' * 32 + '/trash-empty')
        with patch.object(server, 'load_job', return_value={'id': 'a' * 32, 'status': 'failed'}), patch.object(server, 'trash_import', side_effect=RuntimeError('Folder missing')), patch.object(server, 'empty_trash') as empty, patch.object(server, 'save'):
            handler.manage_import(match, {'confirm': 'EMPTY_ACCOUNT_TRASH'})
        empty.assert_not_called()
        self.assertEqual(handler.reply.call_args.args[0], 502)

    def test_partial_empty_keeps_successful_deletion_record(self):
        listing = '//bin/abc <H:folder01>\n//bin/other.txt <H:file0002>\n'
        job = {'id': 'abc', 'status': 'trashed', 'folderHandle': 'H:folder01'}
        def command(name, *args):
            if name == 'find':
                return listing
            if args[-1] == 'H:file0002':
                raise RuntimeError('Delete failed')
            return ''
        with patch.object(server, 'command', side_effect=command), patch.object(server, 'db') as db, patch.object(server, 'save') as save:
            db.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [{'body': json.dumps(job)}]
            with self.assertRaisesRegex(RuntimeError, 'Delete failed'):
                server.empty_trash()
        self.assertEqual(save.call_args.args[0]['status'], 'deleted')

if __name__ == '__main__':
    unittest.main()
