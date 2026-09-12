#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from sweep_runtime import run_sweep_process  # noqa: E402


class SweepWorkingDirectoryTests(unittest.TestCase):
    def test_sweep_uses_vllm_runtime_workdir(self):
        runtime_workdir = Path("/test/vllm-workspace")
        runner = Path("/test/job/sweep/run_full_sweep.sh")
        completed = SimpleNamespace(returncode=0)

        with (
            mock.patch.dict(
                "os.environ", {"EIM_VLLM_WORKDIR": str(runtime_workdir)}
            ),
            mock.patch.object(Path, "is_dir", return_value=True),
            mock.patch(
                "sweep_runtime.subprocess.run", return_value=completed
            ) as run,
        ):
            result = run_sweep_process(runner, mock.sentinel.log, {"A": "B"})

        self.assertIs(result, completed)
        self.assertEqual(run.call_args.args[0], ["bash", str(runner)])
        self.assertEqual(run.call_args.kwargs["cwd"], runtime_workdir)
        self.assertEqual(run.call_args.kwargs["stdout"], mock.sentinel.log)
        self.assertEqual(run.call_args.kwargs["env"], {"A": "B"})

    def test_missing_runtime_workdir_fails_with_actionable_error(self):
        with (
            mock.patch.dict(
                "os.environ", {"EIM_VLLM_WORKDIR": "/missing/workspace"}
            ),
            mock.patch.object(Path, "is_dir", return_value=False),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "vLLM runtime working directory does not exist"
            ):
                run_sweep_process(
                    Path("/test/run_full_sweep.sh"), mock.sentinel.log, {}
                )


if __name__ == "__main__":
    unittest.main()
