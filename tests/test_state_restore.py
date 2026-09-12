#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path


import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from persisted_state import restore_last_job  # noqa: E402


class StateRestoreTests(unittest.TestCase):
    def restore(self, root: Path, state: dict, files: tuple[str, ...]):
        job_id = state["job"]["id"]
        sweep_dir = root / "jobs" / job_id / "sweep"
        sweep_dir.mkdir(parents=True)
        for filename in files:
            (sweep_dir / filename).write_text("test", encoding="utf-8")
        state_file = root / "state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return restore_last_job(state_file, root / "jobs", state["model"])

    def test_restores_completed_job_and_rechecks_files(self):
        state = {
            "model": "test/model",
            "job": {
                "id": "20260912-120000-deadbeef",
                "state": "completed",
                "stage": "completed",
                "report_available": False,
                "recommendation_available": True,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            job = self.restore(
                Path(directory), state, ("sweep-report.html",)
            )
        self.assertIsNotNone(job)
        self.assertTrue(job["report_available"])
        self.assertFalse(job["recommendation_available"])

    def test_marks_running_job_interrupted(self):
        state = {
            "model": "test/model",
            "job": {
                "id": "20260912-120000-deadbeef",
                "state": "running",
                "stage": "running_sweep",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            job = self.restore(Path(directory), state, ())
        self.assertIsNotNone(job)
        self.assertEqual(job["state"], "interrupted")
        self.assertEqual(job["stage"], "interrupted")

    def test_rejects_job_id_with_path_traversal(self):
        state = {
            "model": "test/model",
            "job": {"id": "../outside", "state": "completed"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            state_file.write_text(json.dumps(state), encoding="utf-8")
            job = restore_last_job(state_file, root / "jobs", "test/model")
        self.assertIsNone(job)


if __name__ == "__main__":
    unittest.main()
