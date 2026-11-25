"""Unit tests that do not touch Qdrant or Ollama."""

from __future__ import annotations

import unittest

from nomad_search import config
from nomad_search.format import format_hits


class UrlTests(unittest.TestCase):
    def test_accepts_loopback(self) -> None:
        self.assertEqual(
            config.require_local_http_url("http://127.0.0.1:6333", "u"),
            "http://127.0.0.1:6333",
        )
        self.assertEqual(
            config.require_local_http_url("http://localhost:11434", "u"),
            "http://127.0.0.1:11434",
        )

    def test_rejects_non_local(self) -> None:
        with self.assertRaises(ValueError):
            config.require_local_http_url("http://192.168.1.177:6333", "u")
        with self.assertRaises(ValueError):
            config.require_local_http_url("https://127.0.0.1:6333", "u")
        with self.assertRaises(ValueError):
            config.require_local_http_url("http://user:pass@127.0.0.1:6333", "u")
        with self.assertRaises(ValueError):
            config.require_local_http_url("http://127.0.0.1:6333/secret", "u")


class QueryTests(unittest.TestCase):
    def test_sanitize_and_clamp(self) -> None:
        self.assertEqual(config.sanitize_query("  treat a   burn "), "treat a burn")
        self.assertEqual(config.clamp_top_k(None), 5)
        self.assertEqual(config.clamp_top_k(0), 1)
        self.assertEqual(config.clamp_top_k(99), config.MAX_TOP_K)
        with self.assertRaises(ValueError):
            config.sanitize_query("   ")
        with self.assertRaises(ValueError):
            config.clamp_top_k("nope")
        long_q = "x" * (config.MAX_QUERY_CHARS + 50)
        self.assertEqual(len(config.sanitize_query(long_q)), config.MAX_QUERY_CHARS)


class FormatTests(unittest.TestCase):
    def test_format_hits(self) -> None:
        empty = format_hits("nothing", [])
        self.assertIn("No matching passages", empty)
        text = format_hits(
            "burn",
            [
                {
                    "rank": 1,
                    "score": 0.81,
                    "title": "Burns",
                    "section": "First aid",
                    "source": "MedlinePlus",
                    "path": "medlineplus.gov/burns",
                    "text": "Cool the burn with cool water.",
                }
            ],
        )
        self.assertIn("MedlinePlus — Burns", text)
        self.assertIn("Cool the burn", text)
        self.assertIn("score 0.8100", text)


if __name__ == "__main__":
    unittest.main()


class TrimTests(unittest.TestCase):
    def test_trim_nav_banner(self) -> None:
        from nomad_search.search import _trim_nav
        raw = (
            "Skip navigation Official websites use .govA .gov website belongs to an official "
            "government organization in the United States. You Are Here: Home → Burns "
            "URL of this page: //medlineplus.gov/ency/patientinstructions/000662.htm "
            "Minor burns - aftercare You can care for minor burns at home."
        )
        out = _trim_nav(raw)
        self.assertTrue(out.startswith("Minor burns"), out[:80])
        self.assertNotIn("Skip navigation", out)
        self.assertEqual(_trim_nav("Cool the burn with water."), "Cool the burn with water.")
