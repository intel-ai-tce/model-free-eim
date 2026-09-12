# SPDX-License-Identifier: Apache-2.0

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))

from hardware import detect_recipe_hardware  # noqa: E402


class HardwareDetectionTests(unittest.TestCase):
    def detect(self, cpuinfo: str, requested: str = "auto"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cpuinfo"
            path.write_text(cpuinfo.strip() + "\n", encoding="utf-8")
            return detect_recipe_hardware(requested, path)

    def cpuinfo(self, model: int, name: str = "Intel(R) Xeon(R) CPU") -> str:
        return f"""
vendor_id : GenuineIntel
cpu family : 6
model : {model}
model name : {name}
"""

    def test_emerald_rapids_maps_to_xeon5(self):
        result = self.detect(self.cpuinfo(207))
        self.assertEqual(result.recipe_key, "xeon5")
        self.assertEqual(result.generation, "Emerald Rapids")

    def test_xeon6_cpuid_models(self):
        for model in (173, 174, 175):
            with self.subTest(model=model):
                self.assertEqual(self.detect(self.cpuinfo(model)).recipe_key, "xeon6")

    def test_model_name_fallback(self):
        result = self.detect(self.cpuinfo(999, "Intel(R) Xeon(R) Platinum 8592+"))
        self.assertEqual(result.recipe_key, "xeon5")
        self.assertEqual(result.method, "model name")

    def test_explicit_override_allows_future_hardware(self):
        result = self.detect(self.cpuinfo(999), "future-xeon")
        self.assertEqual(result.recipe_key, "future-xeon")
        self.assertEqual(result.method, "EIM_HARDWARE")

    def test_sapphire_rapids_requires_override(self):
        with self.assertRaisesRegex(RuntimeError, "Sapphire Rapids"):
            self.detect(self.cpuinfo(143))

    def test_non_intel_cpu_requires_override(self):
        cpuinfo = self.cpuinfo(173).replace("GenuineIntel", "AuthenticAMD")
        with self.assertRaisesRegex(RuntimeError, "requires an Intel CPU"):
            self.detect(cpuinfo)


if __name__ == "__main__":
    unittest.main()
