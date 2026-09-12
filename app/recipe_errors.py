#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project

"""Translate stable Recipes converter failures into user-facing alerts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeError:
    code: str
    message: str


def classify_recipe_error(
    log: str, model: str | None, hardware: str
) -> RecipeError | None:
    """Classify known recipe availability failures without masking other errors."""
    model_name = model or "the requested model"

    if "No recipe model matched" in log:
        return RecipeError(
            code="recipe_not_found",
            message=(
                f"No vLLM recipe was found for {model_name}. Check the model ID "
                "or select a model published at recipes.vllm.ai."
            ),
        )

    hardware_markers = (
        "is not available for this model",
        "has no per-hardware renderings",
        "has no usable hardware JSON paths",
    )
    if any(marker in log for marker in hardware_markers):
        return RecipeError(
            code="recipe_hardware_unavailable",
            message=(
                f"A recipe for {model_name} is not available for {hardware}. "
                "Choose supported hardware or another model."
            ),
        )

    return None
