import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

import translate


def args(jobs):
    return SimpleNamespace(model="test", context=1, blocks=5, temperature=0, sentence_batches=False, jobs=jobs)


def fake_batch(a, items, before, after, hints, temperature):
    time.sleep(0.002)
    return {n: f"sl {en}" for n, en in items}


def run_blocks(jobs, source, progress, batch=fake_batch):
    with mock.patch.object(translate, "translate_batch", batch), contextlib.redirect_stdout(io.StringIO()):
        return translate.translate_blocks(args(jobs), source, str(progress), [])


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.progress = Path(self.dir.name) / "progress.json"
        self.source = [f"line {i}" for i in range(1, 58)]

    def test_parallel_result_equals_sequential(self):
        sequential, failed_a = run_blocks(1, self.source, self.progress)
        self.progress.unlink()
        parallel, failed_b = run_blocks(4, self.source, self.progress)
        self.assertEqual(parallel, sequential)
        self.assertEqual((failed_a, failed_b), ([], []))
        self.assertEqual(len(parallel), len(self.source))

    def test_progress_file_is_complete_and_valid(self):
        run_blocks(4, self.source, self.progress)
        saved = json.loads(self.progress.read_text())
        self.assertEqual(len(saved["done"]), len(self.source))

    def test_work_runs_on_several_threads(self):
        threads = set()

        def batch(*a):
            threads.add(threading.get_ident())
            return fake_batch(*a)

        run_blocks(3, self.source, self.progress, batch)
        self.assertGreater(len(threads), 1)

    def test_failed_blocks_are_reported_in_order(self):
        def batch(a, items, *rest):
            return None if any(n in (7, 31) for n, _ in items) else fake_batch(a, items, *rest)

        _, failed = run_blocks(4, self.source, self.progress, batch)
        self.assertEqual(failed, [7, 31])

    def test_fatal_error_stops_run_and_keeps_progress(self):
        def batch(a, items, *rest):
            if items[0][0] > 20:
                raise requests.ConnectionError("server gone")
            return fake_batch(a, items, *rest)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_blocks(4, self.source, self.progress, batch)
        saved = json.loads(self.progress.read_text())
        self.assertTrue(0 < len(saved["done"]) < len(self.source))

    def test_resume_skips_finished_blocks_with_jobs(self):
        run_blocks(1, self.source[:20], self.progress)
        seen = []

        def batch(a, items, *rest):
            seen.extend(n for n, _ in items)
            return fake_batch(a, items, *rest)

        self.progress.write_text(json.dumps({"model": "test", "total": len(self.source),
                                             "done": {str(n): f"sl line {n}" for n in range(1, 21)},
                                             "sentence_batches": False}))
        final, _ = run_blocks(3, self.source, self.progress, batch)
        self.assertEqual(min(seen), 21)
        self.assertEqual(len(final), len(self.source))


if __name__ == "__main__":
    unittest.main()
