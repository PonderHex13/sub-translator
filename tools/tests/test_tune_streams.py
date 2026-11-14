import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/, where tune_streams.py lives

import tune_streams as tune


class ParseStreamsTest(unittest.TestCase):
    def test_range_and_list(self):
        self.assertEqual(tune.parse_streams("1-4"), [1, 2, 3, 4])
        self.assertEqual(tune.parse_streams("4,1,2,2"), [1, 2, 4])
        self.assertEqual(tune.parse_streams("1-2,5"), [1, 2, 5])

    def test_invalid(self):
        for text in ("", "a", "0", "1-", "0-3"):
            with self.subTest(text=text):
                with self.assertRaises(argparse.ArgumentTypeError):
                    tune.parse_streams(text)


class RecommendTest(unittest.TestCase):
    def test_smallest_within_tolerance(self):
        results = [{"n": 1, "rate": 2.5}, {"n": 2, "rate": 3.8}, {"n": 3, "rate": 4.2}, {"n": 4, "rate": 4.25}]
        self.assertEqual(tune.recommend(results, 0.10), 3)
        self.assertEqual(tune.recommend(results, 0.0), 4)
        self.assertEqual(tune.recommend(results, 0.30), 2)
        self.assertEqual(tune.recommend(results, 0.50), 1)

    def test_slower_high_count_is_never_best(self):
        results = [{"n": 1, "rate": 2.5}, {"n": 8, "rate": 1.2}]
        self.assertEqual(tune.recommend(results, 0.10), 1)


class SweepTest(unittest.TestCase):
    def test_sweep_reloads_warms_up_and_computes_rates(self):
        calls, reloads, rows = [], [], []

        def measure(n, blocks):
            calls.append((n, blocks))
            return 100 / (2 * n), n % 2  # seconds, invalid batches

        results = tune.sweep([1, 2], 100, 2, measure, reloads.append, rows.append)
        self.assertEqual(reloads, [1, 2])
        # one warm-up (20 blocks) then two timed runs per stream count
        self.assertEqual(calls, [(1, 20), (1, 100), (1, 100), (2, 20), (2, 100), (2, 100)])
        self.assertEqual([r["n"] for r in results], [1, 2])
        self.assertAlmostEqual(results[0]["rate"], 2.0)
        self.assertAlmostEqual(results[1]["speedup"], 2.0)
        self.assertEqual(results[0]["invalid"], 2)
        self.assertEqual(len(rows), 2)

    def test_warmup_never_exceeds_sample(self):
        calls = []
        tune.sweep([1], 10, 1, lambda n, b: (calls.append(b), (1.0, 0))[1], report=lambda row: None)
        self.assertEqual(calls, [10, 10])


if __name__ == "__main__":
    unittest.main()
