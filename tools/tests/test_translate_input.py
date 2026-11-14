import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import translate


class InputErrorTest(unittest.TestCase):
    def test_missing_file_raises_input_error(self):
        with self.assertRaises(translate.InputError) as ctx:
            translate.process_file(SimpleNamespace(force=False), "/nonexistent/episode.srt", None)
        self.assertIn("file not found", str(ctx.exception))

    def run_main(self, *paths):
        err, out = io.StringIO(), io.StringIO()
        argv = ["translate.py", *paths]
        with mock.patch("sys.argv", argv), mock.patch.object(translate, "check_model"), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as exit_info:
                translate.main()
        return exit_info.exception.code, err.getvalue(), out.getvalue()

    def test_missing_file_prints_message_without_traceback(self):
        code, err, _ = self.run_main("/nonexistent/episode.srt")
        self.assertIn("Error: /nonexistent/episode.srt: file not found", err)
        self.assertIn("1 input file(s) could not be read", str(code))
        self.assertNotIn("Traceback", err)

    def test_other_files_are_still_processed(self):
        with tempfile.TemporaryDirectory() as directory:
            skipped = Path(directory) / "show.sl.srt"  # skipped by name, so no model is needed
            skipped.write_text("")
            code, err, out = self.run_main("/nonexistent/a.srt", str(skipped), "/nonexistent/b.srt")
        self.assertIn("a.srt: file not found", err)
        self.assertIn("b.srt: file not found", err)
        self.assertIn("Skipping", out)  # the existing file between them was still reached
        self.assertIn("2 input file(s)", str(code))
    def test_missing_glossary_stops_before_any_work(self):
        err = io.StringIO()
        with mock.patch("sys.argv", ["translate.py", "-g", "/nonexistent/glossary.txt", "episode.srt"]), \
                mock.patch.object(translate, "check_model") as check, mock.patch.object(translate, "process_file") as process, \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as exit_info:
                translate.main()
        self.assertEqual(exit_info.exception.code, 2)
        self.assertIn("glossary file not found: /nonexistent/glossary.txt", err.getvalue())
        check.assert_not_called()
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
