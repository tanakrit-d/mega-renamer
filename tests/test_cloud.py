import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from cloud import capacity, link_metadata, parse_storage, validate_link

DF = '''Cloud drive:          5000 B in 2 file(s) and 1 folder(s)
Inbox:                0 B in 0 file(s) and 0 folder(s)
Rubbish bin:          2000 B in 1 file(s) and 1 folder(s)
---------------------------------------------------------------------------
USED STORAGE:         8000 B       80.00% of 10000 B
---------------------------------------------------------------------------
Total size taken up by file versions: 1000 B
'''

class StorageTests(unittest.TestCase):
    def test_exact_storage_includes_trash_and_versions(self):
        self.assertEqual(parse_storage(DF), {'usedBytes': 8000, 'totalBytes': 10000, 'availableBytes': 2000, 'trashBytes': 2000})

    def test_over_quota_clamps_free_space(self):
        self.assertEqual(parse_storage(DF.replace('8000 B', '11000 B'))['availableBytes'], 0)

    def test_unparseable_storage_fails_closed(self):
        for text in ['', 'USED STORAGE: 1 GiB 50% of 2 GiB', DF.replace('Rubbish bin:', 'Unknown:')]:
            with self.assertRaises(RuntimeError):
                parse_storage(text)

    def test_capacity_boundary_and_report_reserve(self):
        metadata = {'sourceBytes': 100, 'fileCount': 1}
        required = 100 + 1048576
        self.assertTrue(capacity(metadata, {'availableBytes': required})['fits'])
        result = capacity(metadata, {'availableBytes': required - 1})
        self.assertFalse(result['fits'])
        self.assertEqual(result['shortfallBytes'], 1)
        self.assertEqual(capacity({'sourceBytes': 100, 'fileCount': 1000}, {'availableBytes': 0})['reserveBytes'], 4096000)

    def test_file_and_folder_metadata_modern_and_legacy(self):
        for url, result, action in [
            ('https://mega.nz/file/abc#key', {'s': 123}, {'a': 'g', 'p': 'abc'}),
            ('https://mega.nz/#!abc!key', {'s': 123}, {'a': 'g', 'p': 'abc'}),
            ('https://mega.nz/folder/abc#key', {'s': [123, 4, 2]}, {'a': 'pli', 'ph': 'abc'}),
            ('https://mega.nz/#F!abc!key', {'s': [123, 4, 2]}, {'a': 'pli', 'ph': 'abc'}),
        ]:
            with self.subTest(url=url), patch('cloud.urllib.request.urlopen', return_value=io.BytesIO(json.dumps([result]).encode())) as request:
                metadata = link_metadata(url)
                self.assertEqual(metadata['sourceBytes'], 123)
                self.assertEqual(metadata['fileCount'], 4 if action['a'] == 'pli' else 1)
                self.assertEqual(json.loads(request.call_args.args[0].data), [action])
                self.assertNotIn(b'key', request.call_args.args[0].data)

    def test_unavailable_or_invalid_metadata_blocks(self):
        for result in [-9, {}, {'s': -1}, {'s': True}, {'s': '123'}, {'s': [0]}]:
            with patch('cloud.urllib.request.urlopen', return_value=io.BytesIO(json.dumps([result]).encode())):
                with self.assertRaises(RuntimeError):
                    link_metadata('https://mega.nz/file/abc#key')

    def test_invalid_url_rejected_without_network(self):
        for source in ['http://mega.nz/file/abc#key', 'https://evil.com/file/abc#key', None, 'https://mega.nz/file/abc']:
            with self.assertRaises(ValueError):
                validate_link(source)

if __name__ == '__main__':
    unittest.main()
