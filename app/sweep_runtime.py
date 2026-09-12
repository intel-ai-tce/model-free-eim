#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project

"""Launch generated sweep scripts from the vLLM runtime workspace."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import IO


DEFAULT_VLLM_WORKDIR = "/vllm-workspace"


def run_sweep_process(
    runner: Path,
    log: IO[str],
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run a sweep without losing vLLM-relative recipe asset paths."""
    workdir = Path(os.environ.get("EIM_VLLM_WORKDIR", DEFAULT_VLLM_WORKDIR))
    if not workdir.is_dir():
        raise RuntimeError(f"vLLM runtime working directory does not exist: {workdir}")

    # Recipes may emit paths relative to the source tree, such as
    # examples/tool_chat_template_gemma4.jinja. Generated sweep scripts locate
    # their own files through SCRIPT_DIR, so they do not require cwd to be the
    # sweep output directory.
    return subprocess.run(
        ["bash", str(runner)],
        cwd=workdir,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        check=False,
    )
