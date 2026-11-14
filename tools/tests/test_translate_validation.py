import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import translate


class BatchValidationTest(unittest.TestCase):
    def translate(self, response):
        with patch("translate.ask", return_value=response):
            with contextlib.redirect_stderr(io.StringIO()):
                return translate.translate_batch(None, [(1, "one"), (2, "two")], [], [], [], 0)

    def test_valid_and_reordered_blocks(self):
        self.assertEqual(self.translate("2| dva\n1| ena\n"), {1: "ena", 2: "dva"})

    def test_invalid_responses_are_rejected(self):
        responses = [
            "1| ena\n1| druga\n2| dva",
            "1| ena\n2| dva\n3| extra",
            "1| ena",
            "1| ena\n2| ",
            "1| ena\n2| dva\nadditional commentary",
            "1| ena\n2| два",
        ]
        for response in responses:
            with self.subTest(response=response):
                self.assertIsNone(self.translate(response))

    def test_retry_and_split_after_invalid_responses(self):
        args = SimpleNamespace(model="test", context=0, blocks=2, temperature=0)
        responses = ["1| ena\n1| ena\n2| dva", "1| ena\n2| dva\n3| tri",
                     "1| ena", "2| dva"]
        with tempfile.TemporaryDirectory() as directory:
            with patch("translate.ask", side_effect=responses) as ask:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result, failed = translate.translate_blocks(
                        args, ["one", "two"], str(Path(directory) / "progress.json"), []
                    )
        self.assertEqual(result, {1: "ena", 2: "dva"})
        self.assertEqual(failed, [])
        self.assertEqual(ask.call_count, 4)


if __name__ == "__main__":
    unittest.main()
