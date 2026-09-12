#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from recipe_errors import classify_recipe_error  # noqa: E402


class RecipeErrorTests(unittest.TestCase):
    def test_classifies_missing_model_recipe(self):
        error = classify_recipe_error(
            "ERROR: No recipe model matched 'acme/unknown'.",
            "acme/unknown",
            "xeon6",
        )
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "recipe_not_found")
        self.assertIn("acme/unknown", error.message)

    def test_classifies_unavailable_hardware(self):
        error = classify_recipe_error(
            "ERROR: Hardware 'xeon6' is not available for this model.",
            "acme/model",
            "xeon6",
        )
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "recipe_hardware_unavailable")

    def test_does_not_misclassify_network_failure(self):
        error = classify_recipe_error(
            "ERROR: <urlopen error connection timed out>",
            "acme/model",
            "xeon6",
        )
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
