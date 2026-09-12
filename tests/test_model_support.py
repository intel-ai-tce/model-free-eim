#!/usr/bin/env python3

import json
import sys
import unittest
import urllib.error
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from model_support import check_model_support  # noqa: E402


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class ModelSupportTests(unittest.TestCase):
    def test_supported_fast_check(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return Response({"ok": True, "verdict": "SUPPORTED"})

        result = check_model_support(
            "http://support.example:8080/", "acme/model", 12, opener
        )
        self.assertEqual(result["verdict"], "SUPPORTED")
        self.assertEqual(captured["url"], "http://support.example:8080/api/check")
        self.assertEqual(
            captured["body"],
            {"slug": "acme/model", "smoke_test": False, "verbose": False},
        )
        self.assertEqual(captured["timeout"], 12)

    def test_unsupported_verdict(self):
        result = check_model_support(
            "http://support.example",
            "acme/model",
            opener=lambda *_args, **_kwargs: Response(
                {"ok": True, "verdict": "UNSUPPORTED"}
            ),
        )
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["verdict"], "UNSUPPORTED")

    def test_unavailable_service(self):
        def opener(*_args, **_kwargs):
            raise urllib.error.URLError("connection refused")

        result = check_model_support(
            "http://support.example", "acme/model", opener=opener
        )
        self.assertEqual(result["state"], "unavailable")

    def test_ok_does_not_replace_verdict(self):
        result = check_model_support(
            "http://support.example",
            "acme/model",
            opener=lambda *_args, **_kwargs: Response(
                {"ok": True, "verdict": "UNKNOWN"}
            ),
        )
        self.assertEqual(result["state"], "failed")


if __name__ == "__main__":
    unittest.main()
