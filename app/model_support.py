#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project

"""Client for the optional vLLM CPU model-support service."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


UrlOpener = Callable[..., Any]


def check_model_support(
    base_url: str,
    model: str,
    timeout: float = 180,
    opener: UrlOpener = urllib.request.urlopen,
) -> dict[str, Any]:
    """Run the service's fast database check without a Docker smoke test."""
    endpoint = base_url.rstrip("/") + "/api/check"
    payload = json.dumps(
        {"slug": model, "smoke_test": False, "verbose": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "model-free-eim/1.0",
        },
        method="POST",
    )

    try:
        with opener(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "state": "unavailable",
            "message": f"Model-support service could not be reached: {exc}",
        }
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {
            "state": "failed",
            "message": "Model-support service returned an invalid response.",
        }

    if not isinstance(result, dict):
        return {
            "state": "failed",
            "message": "Model-support service returned an invalid response.",
        }
    if result.get("ok") is not True:
        return {
            "state": "failed",
            "message": str(result.get("error") or "Model-support check failed."),
        }

    verdict = str(result.get("verdict", "")).upper()
    if verdict not in {"SUPPORTED", "UNSUPPORTED"}:
        return {
            "state": "failed",
            "message": "Model-support service returned no recognized verdict.",
        }

    if verdict == "SUPPORTED":
        message = (
            "Supported by vLLM CPU, but no tested Recipes configuration is "
            "available. Manual configuration is required."
        )
    else:
        message = "Not supported by vLLM CPU according to current support data."
    return {"state": "completed", "verdict": verdict, "message": message}
