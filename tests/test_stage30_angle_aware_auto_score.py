import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'index.html').read_text(encoding='utf-8')
BACKEND = (ROOT / 'backend' / 'main.py').read_text(encoding='utf-8')
class Stage30Tests(unittest.TestCase):
    def test_three_camera_angles(self):
        for angle in ('横から', '斜め後ろから', '後ろから'):
            self.assertIn('<option>' + angle + '</option>', HTML)
    def test_auto_score_is_saved_and_explained(self):
        self.assertIn('function buildAiFormAutoScore(sm,cameraAngle)', HTML)
        self.assertIn('autoScore:buildAiFormAutoScore', HTML)
        self.assertIn('フォームの上手さ・キック技術の点数ではなく', HTML)
    def test_missing_measurements_are_excluded(self):
        self.assertIn('Number.isFinite(f[m.key])', HTML)
        self.assertIn('採点対象外', HTML)
    def test_rear_angle_guidance(self):
        self.assertIn(chr(34) + '後ろから' + chr(34) + ': [', BACKEND)
        self.assertIn('接触位置は断定できません', BACKEND)
if __name__ == '__main__':
    unittest.main()