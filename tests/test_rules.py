import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from rules import defaults, initialize_rules, read_rules, validate_rules, write_rules
from renamer import clean_name

class RulesTests(unittest.TestCase):
    def test_initialize_once_and_persist_edits(self):
        custom = {'version': 1, 'remove': ['CUSTOM'], 'afterResolution': ['SOURCE.DTS']}
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(initialize_rules(directory), defaults())
            write_rules(directory, custom)
            self.assertEqual(initialize_rules(directory), custom)
            self.assertEqual(json.loads((Path(directory) / 'naming-rules.json').read_text()), custom)

    def test_reject_invalid_rules_without_changing_file(self):
        invalid = [None, {}, {'version': 2, 'remove': [], 'afterResolution': []},
                   {'version': True, 'remove': [], 'afterResolution': []},
                   {'version': 1, 'remove': 'WEB-DL', 'afterResolution': []},
                   {'version': 1, 'remove': [''], 'afterResolution': []},
                   {'version': 1, 'remove': ['a\nb'], 'afterResolution': []},
                   {'version': 1, 'remove': ['a/b'], 'afterResolution': []},
                   {'version': 1, 'remove': ['x' * 129], 'afterResolution': []},
                   {'version': 1, 'remove': ['CUSTOM'], 'afterResolution': ['custom']},
                   {'version': 1, 'remove': ['CUSTOM'] * 201, 'afterResolution': []}]
        with tempfile.TemporaryDirectory() as directory:
            original = initialize_rules(directory)
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    write_rules(directory, value)
                self.assertEqual(read_rules(directory), original)

    def test_interrupted_atomic_save_preserves_previous_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            original = initialize_rules(directory)
            with patch('rules.os.replace', side_effect=OSError('Write failed')):
                with self.assertRaises(OSError):
                    write_rules(directory, {'version': 1, 'remove': [], 'afterResolution': []})
            self.assertEqual(read_rules(directory), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_custom_tags_are_literals_and_can_disable_defaults(self):
        config = {'version': 1, 'remove': ['CUSTOM', '[group]', 'WEB.*'], 'afterResolution': []}
        self.assertEqual(clean_name('Film.CUSTOM.[group].WEB.*.mkv', config), ('Film.mkv', ['CUSTOM', '[group]', 'WEB.*']))
        self.assertEqual(clean_name('Film.WEB.x264.WEB-DL.mkv', config), ('Film.WEB.x264.WEB-DL.mkv', []))
        self.assertEqual(clean_name('Film.WEB-DL.mkv', {'version': 1, 'remove': [], 'afterResolution': []}), ('Film.WEB-DL.mkv', []))

    def test_custom_conditional_rule_preserves_resolution_and_exceptions(self):
        config = {'version': 1, 'remove': [], 'afterResolution': ['SOURCE.DTS']}
        self.assertEqual(clean_name('Film.1080p.SOURCE.DTS.mkv', config), ('Film.1080p.mkv', ['SOURCE.DTS']))
        self.assertEqual(clean_name('Film.2002.SOURCE.DTS.mkv', config), ('Film.2002.SOURCE.DTS.mkv', []))

    def test_longest_overlapping_tag_matches_first(self):
        config = {'version': 1, 'remove': ['TAG', 'TAG-HD'], 'afterResolution': []}
        self.assertEqual(clean_name('Film.TAG-HD.mkv', config), ('Film.mkv', ['TAG-HD']))

if __name__ == '__main__':
    unittest.main()
