#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project

"""Validation and restoration of persisted manager state."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


JOB_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def restore_last_job(
    state_file: Path, jobs_dir: Path, current_model: str | None
) -> dict[str, Any] | None:
    """Return the validated last job, with file availability refreshed."""
    if not state_file.is_file():
        return None
    try:
        saved = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(saved, dict):
        return None
    saved_model = saved.get("model")
    if saved_model and current_model and saved_model != current_model:
        return None

    job = saved.get("job")
    if not isinstance(job, dict):
        return None
    job_id = job.get("id")
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return None

    sweep_dir = jobs_dir / job_id / "sweep"
    if not sweep_dir.is_dir():
        return None

    restored = dict(job)
    restored["report_available"] = (
        sweep_dir / "sweep-report.html"
    ).is_file()
    restored["recommendation_available"] = (
        sweep_dir / "recommended-config.yml"
    ).is_file()
    if restored.get("state") in {"queued", "running"}:
        restored.update(
            state="interrupted",
            stage="interrupted",
            error="Manager restarted before the sweep completed.",
        )
    return restored
