import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from renamer import clean_name, plan_names

class NamingTests(unittest.TestCase):
    def test_all_release_tags(self):
        for tag in ['WEB-DL','WEBRip','BDRip','HDRip','DVDRip','WEB.x264','WEB.h264','HDTV.x264','HDTV.XviD','BluRay.x264']:
            with self.subTest(tag=tag):
                self.assertEqual(clean_name('Film.2025.' + tag + '.mkv'), ('Film.2025.mkv', [tag]))

    def test_resolution_rule(self):
        self.assertEqual(clean_name('Film.1080p.BluRay.DTS.mkv'), ('Film.1080p.mkv', ['BluRay.DTS']))
        self.assertEqual(clean_name('Film.2160p.BluRay.DTS-HD.mkv'), ('Film.2160p.mkv', ['BluRay.DTS-HD']))

    def test_exceptions(self):
        for name in ['Phone.Booth.2002.BluRay.DTS-HD.MA.5.1.mkv', 'REMUX.BluRay.DTS.mkv', 'BluRay.1080p.DTS.mkv', 'Film.A1080p.BluRay.DTS.mkv', 'Film.WEBRipper.mkv']:
            self.assertEqual(clean_name(name), (name, []))

    def test_multiple_and_case(self):
        self.assertEqual(clean_name('Film web-dl HDTV.x264.mp4'), ('Film.mp4', ['web-dl','HDTV.x264']))

    def test_collisions(self):
        result = plan_names(['/a/Film.WEB-DL.mkv','/a/Film.WEBRip.mkv','/a/Film.mkv'])
        self.assertEqual(len({r['renamed'] for r in result}), 3)
        self.assertEqual(result[-1]['renamed'], '/a/Film.mkv')

    def test_folder_reservation(self):
        result = plan_names(['/a/Film.WEB-DL.mkv'], reserved=['/a/Film.mkv'])
        self.assertEqual(result[0]['renamed'], '/a/Film (2).mkv')

if __name__ == '__main__':
    unittest.main()
