import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class Stage41PhaseGuardRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("Node.js is required for runtime behavior tests")
        match = re.search(
            r"(function validateKickPhaseTimestamp\(record,phaseKey,time\)\{.*?\n\})",
            HTML,
            re.S,
        )
        if not match:
            raise AssertionError("phase timestamp validator not found")
        cls.function_source = match.group(1)

    def run_case(self, record, key, time):
        script = self.function_source + "\n" + (
            "const record = " + json.dumps(record, ensure_ascii=False) + ";\n"
            "const result = validateKickPhaseTimestamp(record, "
            + json.dumps(key) + ", " + json.dumps(time) + ");\n"
            "process.stdout.write(JSON.stringify(result));"
        )
        result = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_valid_timestamp_between_neighbors_is_accepted(self):
        record = {"reviewedKickPhases": {
            "approach": {"confirmedBy": "parent_manual_review", "status": "確認済み", "timeSeconds": 1.0},
            "impact": {"confirmedBy": "parent_manual_review", "status": "確認済み", "timeSeconds": 2.0},
        }}
        self.assertEqual("", self.run_case(record, "plant", 1.5))

    def test_timestamp_before_preceding_phase_is_rejected(self):
        record = {"reviewedKickPhases": {
            "approach": {"confirmedBy": "parent_manual_review", "status": "確認済み", "timeSeconds": 1.0},
        }}
        self.assertIn("前の節目", self.run_case(record, "plant", 0.8))

    def test_timestamp_after_following_phase_is_rejected(self):
        record = {"reviewedKickPhases": {
            "impact": {"confirmedBy": "parent_manual_review", "status": "確認済み", "timeSeconds": 2.0},
        }}
        self.assertIn("次の節目", self.run_case(record, "swing", 2.2))

    def test_equal_timestamp_is_rejected(self):
        record = {"reviewedKickPhases": {
            "approach": {"confirmedBy": "parent_manual_review", "status": "確認済み", "timeSeconds": 1.0},
        }}
        self.assertIn("前の節目", self.run_case(record, "plant", 1.0))

    def test_unconfirmed_and_unobservable_phases_do_not_constrain(self):
        record = {"reviewedKickPhases": {
            "approach": {"confirmedBy": "parent_manual_review", "status": "映像で確認できず", "timeSeconds": None},
            "impact": {"confirmedBy": "parent_manual_review", "status": "未確認", "timeSeconds": 0.2},
        }}
        self.assertEqual("", self.run_case(record, "plant", 1.0))

    def test_unknown_phase_is_rejected(self):
        self.assertIn("節目または時刻", self.run_case({}, "unknown", 1.0))


if __name__ == "__main__":
    unittest.main()
