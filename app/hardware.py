#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Resolve the vLLM Recipes hardware key from Linux CPU information."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


CPUINFO_PATH = Path("/proc/cpuinfo")

# Linux reports these CPUID model numbers as decimal values in /proc/cpuinfo.
_INTEL_FAMILY_6_MODELS = {
    0xCF: ("xeon5", "Emerald Rapids"),
    0xAD: ("xeon6", "Granite Rapids"),
    0xAE: ("xeon6", "Granite Rapids"),
    0xAF: ("xeon6", "Sierra Forest"),
}


@dataclass(frozen=True)
class HardwareSelection:
    recipe_key: str
    generation: str
    method: str
    cpu_model_name: str
    cpuid_family: int | None
    cpuid_model: int | None

    def to_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


def _read_first_processor(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip() and fields:
            break
        name, separator, value = raw_line.partition(":")
        if separator:
            fields[name.strip().lower()] = value.strip()
    return fields


def _integer(fields: dict[str, str], key: str) -> int | None:
    try:
        return int(fields[key])
    except (KeyError, ValueError):
        return None


def _model_name_fallback(model_name: str) -> tuple[str, str] | None:
    normalized = model_name.lower()
    if re.search(r"granite\s*rapids", normalized):
        return "xeon6", "Granite Rapids"
    if re.search(r"sierra\s*forest", normalized):
        return "xeon6", "Sierra Forest"
    if re.search(r"emerald\s*rapids", normalized):
        return "xeon5", "Emerald Rapids"

    # Xeon 6 uses 6xxx-style SKUs. Xeon Scalable generations 4 and 5 use
    # tiered names such as "Platinum 8480+" and "Platinum 8592+".
    if re.search(r"\bxeon(?:\(r\))?\s+6\d{3}[a-z+]*\b", normalized):
        return "xeon6", "Xeon 6"
    if re.search(
        r"\b(?:platinum|gold|silver|bronze|max)\s+\d5\d{2}[a-z+]*\b",
        normalized,
    ):
        return "xeon5", "5th Gen Xeon Scalable"
    return None


def detect_recipe_hardware(
    requested: str = "auto", cpuinfo_path: Path = CPUINFO_PATH
) -> HardwareSelection:
    """Return a Recipes key, preserving an explicit operator override."""
    requested = requested.strip().lower()
    fields = _read_first_processor(cpuinfo_path)
    model_name = fields.get("model name", "unknown")
    family = _integer(fields, "cpu family")
    model = _integer(fields, "model")

    if requested and requested != "auto":
        return HardwareSelection(
            recipe_key=requested,
            generation="operator override",
            method="EIM_HARDWARE",
            cpu_model_name=model_name,
            cpuid_family=family,
            cpuid_model=model,
        )

    vendor = fields.get("vendor_id")
    if vendor and vendor != "GenuineIntel":
        raise RuntimeError(
            f"Automatic Xeon detection requires an Intel CPU; detected {vendor}. "
            "Set EIM_HARDWARE to a Recipes hardware key to override detection."
        )

    match = _INTEL_FAMILY_6_MODELS.get(model) if family == 6 else None
    method = "CPUID"
    if match is None:
        match = _model_name_fallback(model_name)
        method = "model name"
    if match is not None:
        recipe_key, generation = match
        return HardwareSelection(
            recipe_key=recipe_key,
            generation=generation,
            method=method,
            cpu_model_name=model_name,
            cpuid_family=family,
            cpuid_model=model,
        )

    if family == 6 and model == 0x8F:
        detail = "Sapphire Rapids (4th Gen Xeon Scalable)"
    else:
        detail = model_name
    raise RuntimeError(
        f"Could not map {detail} (family={family}, model={model}) to xeon5 or "
        "xeon6. Set EIM_HARDWARE explicitly to a valid Recipes hardware key."
    )
