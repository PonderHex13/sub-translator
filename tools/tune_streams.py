#!/usr/bin/env python3
"""Find how many parallel streams (translate.py -j N) give the best speed on this server and card.

For each N the tool translates a built-in sample with `translate.py -j N`, times it and prints a
table. Run it while the GPU is otherwise idle. Unknown options (for example -b or --temperature)
are passed on to translate.py.
"""
import argparse
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRANSLATE = HERE.parent / "translate.py"
SAMPLE = HERE / "sample_tune.srt"
CTX_PER_SLOT = 3072  # a default request (10 blocks plus context) needs about 2,400 tokens at most
WARMUP_BLOCKS = 20

EPILOG = """\
examples:
  %(prog)s                                  (test 1-4 streams on the server's current setup)
  %(prog)s --streams 1-3 --runs 2
  %(prog)s --slots-cmd "lemonade load MODEL --ctx-size {ctx} --llamacpp-args '--parallel {n}'"

Without --slots-cmd the server is not touched: set its slot count to the largest N first. Results
for N above the server's slot count are meaningless, because the extra requests just queue. A
server loaded with many slots can also be slower per stream (8 slots halved the speed of a single
stream on one test card), so --slots-cmd gives the most reliable numbers.
"""


def parse_streams(text):
    """'1-4' or '1,2,4' -> sorted list of unique stream counts."""
    counts = set()
    for part in text.split(","):
        part = part.strip()
        span = re.fullmatch(r"(\d+)-(\d+)", part)
        if span:
            low, high = int(span[1]), int(span[2])
            counts.update(range(low, high + 1))
        elif part.isdigit():
            counts.add(int(part))
        else:
            raise argparse.ArgumentTypeError(f"invalid stream list {text!r}; use 1-4 or 1,2,4")
    if not counts or min(counts) < 1:
        raise argparse.ArgumentTypeError("stream counts must be 1 or more")
    return sorted(counts)


def recommend(results, tolerance):
    """Smallest stream count whose rate is within `tolerance` of the best rate."""
    best = max(r["rate"] for r in results)
    return min(r["n"] for r in results if r["rate"] >= best * (1 - tolerance))


def sweep(streams, blocks, runs, measure, reload_server=None, report=print):
    """measure(n, blocks) -> (seconds, invalid_batches). Returns one result dict per stream count."""
    results = []
    for n in streams:
        if reload_server:
            reload_server(n)
        measure(n, min(WARMUP_BLOCKS, blocks))  # loads the model and warms caches, not timed
        samples = [measure(n, blocks) for _ in range(runs)]
        seconds = statistics.mean(s for s, _ in samples)
        result = {"n": n, "seconds": seconds, "rate": blocks / seconds,
                  "invalid": sum(i for _, i in samples)}
        base = results[0] if results else result
        result["speedup"] = result["rate"] / base["rate"]
        results.append(result)
        report(format_row(result))
    return results


def format_row(r):
    return (f"{r['n']:>7} {r['seconds']:>9.1f} {r['rate']:>12.2f} {r['rate'] / r['n']:>10.2f} "
            f"{r['speedup']:>8.2f}x {r['invalid']:>8}")


HEADER = f"{'streams':>7} {'seconds':>9} {'blocks/s':>12} {'per stream':>10} {'speedup':>9} {'invalid':>8}"


def make_measure(sample, workdir, extra):
    target = Path(workdir) / "tune.srt"
    output = Path(workdir) / "tune.sl.srt"

    def measure(n, blocks):
        shutil.copy(sample, target)
        output.unlink(missing_ok=True)
        cmd = [sys.executable, str(TRANSLATE), "-f", "-j", str(n), "-n", str(blocks), *extra, str(target)]
        start = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.monotonic() - start
        if proc.returncode != 0:
            tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
            sys.exit(f"translate.py failed with -j {n}:\n{tail}")
        return elapsed, proc.stderr.count("Invalid batch response")

    return measure


def main():
    ap = argparse.ArgumentParser(description=__doc__, epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--streams", type=parse_streams, default="1-4", metavar="LIST",
                    help="stream counts to test, e.g. 1-4 or 1,2,4 (default: 1-4)")
    ap.add_argument("--blocks", type=int, default=100, metavar="N",
                    help="blocks translated per timed run, at most the sample size (default: 100)")
    ap.add_argument("--runs", type=int, default=1, metavar="N", help="timed runs per stream count (default: 1)")
    ap.add_argument("--tolerance", type=float, default=0.10, metavar="X",
                    help="recommend the smallest N within this fraction of the best rate (default: 0.10)")
    ap.add_argument("--sample", type=Path, default=SAMPLE, help="English .srt used for the test")
    ap.add_argument("--slots-cmd", metavar="CMD",
                    help="shell command run before each N to set the server's slots; {n} is the number of "
                         "streams and {ctx} a context size of about 3,000 tokens per slot")
    ap.add_argument("--url", help="chat completions URL (passed to translate.py)")
    ap.add_argument("--model", help="model id (passed to translate.py)")
    args, extra = ap.parse_known_args()
    if isinstance(args.streams, str):
        args.streams = parse_streams(args.streams)
    if args.blocks < 1 or args.runs < 1 or not 0 <= args.tolerance < 1:
        ap.error("--blocks and --runs must be at least 1 and --tolerance between 0 and 1")
    if not args.sample.exists():
        ap.error(f"sample file {args.sample} not found")
    for flag, value in (("--url", args.url), ("--model", args.model)):
        if value:
            extra += [flag, value]

    reload_server = None
    if args.slots_cmd:
        def reload_server(n):
            subprocess.run(args.slots_cmd.format(n=n, ctx=n * CTX_PER_SLOT), shell=True, check=True)
    else:
        print(f"Server is not reloaded: make sure it has at least {max(args.streams)} slots.\n")

    print(HEADER)
    with tempfile.TemporaryDirectory() as workdir:
        measure = make_measure(args.sample, workdir, extra)
        results = sweep(args.streams, args.blocks, args.runs, measure, reload_server)

    best = recommend(results, args.tolerance)
    print(f"\nRecommended: {best} stream{'s' if best > 1 else ''} "
          f"(smallest count within {args.tolerance:.0%} of the best rate).")
    rates = [r["rate"] for r in results]
    if any(b < a * 0.95 for a, b in zip(rates, rates[1:])):
        print("Note: speed dropped for a higher stream count; check the server's slots and VRAM.")


if __name__ == "__main__":
    main()
