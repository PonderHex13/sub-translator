import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import translate


class BatchingTest(unittest.TestCase):
    def test_fixed_mode_is_unchanged(self):
        self.assertEqual(list(translate.batch_ranges(["x"] * 12, 5)), [(0, 5), (5, 10), (10, 12)])

    def test_sentence_boundary_with_tags_and_abbreviations(self):
        self.assertTrue(translate.sentence_boundary('DONE!</i>'))
        for text in ("CONTINUES,", "WAIT...", "Mr.", "Dr.", "U.S.", ""):
            with self.subTest(text=text):
                self.assertFalse(translate.sentence_boundary(text))

    def test_nearest_boundary_and_fallback_stay_bounded(self):
        source = ["x"] * 20
        source[5] = "Finished."
        ranges = list(translate.batch_ranges(source, 5, True))
        self.assertEqual(ranges[0], (0, 6))
        self.assertEqual(ranges[1], (6, 11))
        self.assertTrue(all(0 < end - start <= 7 for start, end in ranges))
        self.assertEqual([i for start, end in ranges for i in range(start, end)], list(range(20)))

    def test_resume_rejects_different_batch_mode(self):
        args = SimpleNamespace(model="test", context=0, blocks=5, temperature=0, sentence_batches=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            original = json.dumps({"model": "test", "total": 1, "done": {"1": "one"}})
            path.write_text(original)
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    translate.translate_blocks(args, ["one"], str(path), [])
            self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
