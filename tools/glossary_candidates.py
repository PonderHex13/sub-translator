#!/usr/bin/env python3
"""Make paste files for ChatGPT that help build glossary entries.

Scans English .srt files (a whole series) for frequent terms and short phrases that are not yet
in the glossaries, and writes them in chunks, each with one example line. Paste a chunk into
ChatGPT, then review its answer and append it to glossary_common.txt or the show's glossary.txt.
"""
import argparse
import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)
import translate  # noqa: E402

STOP = set("""a about after again all also am an and any are aren't as at be because been before being both but by
can can't could couldn't did didn't do does doesn't doing don't down for from get got had hadn't has hasn't have
haven't having he he'd he'll he's her here hers herself him himself his how i i'd i'll i'm i've if in into is isn't
it it's its itself just let's me more most my myself no nor not now of off on once one only or other our ours out
over own same she she'd she'll she's should shouldn't so some such than that that's the their theirs them then there
there's these they they'd they'll they're they've this those through to too under until up us very was wasn't we we'd
we'll we're we've were weren't what what's when where which while who whom why will with won't would wouldn't you
you'd you'll you're you've your yours yourself oh yeah okay uh um well hey go going gonna know like want mean right
say said see think come back look way time need tell make take give let""".split())

HEADER = (
    "Below is a list of terms and short phrases that occur often in the English subtitles of {show}, "
    "each with an example line. From this list, pick ONLY the entries whose meaning is context-dependent, "
    "idiomatic, domain-specific, slang, a fixed phrase, or a name, and whose literal translation into "
    "Slovenian may be wrong or ambiguous. Use the examples, not assumptions about the series. "
    "Skip ordinary words and phrases. For each pick, answer with one line "
    "`English = Slovenian`, in natural spoken Slovenian suitable for subtitles. Names that stay unchanged are "
    "written `Name = Name`. Output only these lines.\n"
    "If I send further chunks, continue in the same chat with the same rules.\n\n"
)


def words(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace(" // ", " "))


def ref_blocks(path):
    """Block numbers used in the reference file of this episode, to keep them out of the extraction."""
    m = re.search(r"E(\d+)\.srt$", path)
    ref = os.path.join(os.path.dirname(os.path.abspath(path)), "Tests", f"ref_E{m.group(1)}.txt") if m else ""
    if not ref or not os.path.exists(ref):
        return set()
    return {ln.strip() for ln in open(ref, encoding="utf-8") if ln.strip().isdigit()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="+", help="English .srt files of the series")
    ap.add_argument("-s", "--show", default="the series",
                    help="show or series name for the instruction (default: %(default)s)")
    ap.add_argument("-g", "--glossary", help="show glossary (default: glossary.txt next to the first input)")
    ap.add_argument("-o", "--out", default="glossary_paste", help="output folder (default: %(default)s)")
    ap.add_argument("--min-count", type=int, default=5, help="minimum occurrences (default: %(default)s)")
    ap.add_argument("--min-episodes", type=int, default=2, help="minimum episodes it appears in (default: %(default)s)")
    ap.add_argument("--top", type=int, default=300, help="maximum candidates (default: %(default)s)")
    ap.add_argument("--chunk", type=int, default=100, help="candidates per paste file (default: %(default)s)")
    ap.add_argument("--keep-refs", action="store_true",
                    help="also use blocks listed in Tests/ref_E*.txt (by default they are excluded, "
                         "so glossary terms do not over-fit the scoring set)")
    a = ap.parse_args()

    gpath = a.glossary or os.path.join(os.path.dirname(os.path.abspath(a.input[0])), "glossary.txt")
    known = {en.lower() for en, _, _ in translate.load_glossary(gpath)} if os.path.exists(gpath) else set()
    common = os.path.join(PROJECT_ROOT, "glossary_common.txt")
    if os.path.exists(common):
        known |= {en.lower() for en, _, _ in translate.load_glossary(common)}

    count = collections.Counter()
    eps = collections.defaultdict(set)
    example = {}
    for path in a.input:
        skip = set() if a.keep_refs else ref_blocks(path)
        for b in translate.parse_srt(open(path, encoding="utf-8", errors="replace").read()):
            if b["num"] in skip:
                continue
            line = translate.flat(b)
            w = words(line)
            seen = set()
            for n in (1, 2, 3):
                for i in range(len(w) - n + 1):
                    g = w[i:i + n]
                    if g[0] in STOP or g[-1] in STOP or all(x in STOP for x in g):
                        continue
                    if n == 1 and len(g[0]) < 5:
                        continue
                    term = " ".join(g)
                    if term in seen:
                        continue
                    seen.add(term)
                    count[term] += 1
                    eps[term].add(path)
                    if term not in example or len(line) < len(example[term]):
                        example[term] = line

    cands = [(t, c) for t, c in count.items()
             if c >= a.min_count and len(eps[t]) >= min(a.min_episodes, len(a.input)) and t not in known]
    by_count = dict(cands)
    # drop a shorter term when a longer one containing it is almost as frequent
    cands = [(t, c) for t, c in cands
             if not any(t != u and f" {t} " in f" {u} " and cu >= 0.8 * c for u, cu in by_count.items())]
    cands.sort(key=lambda tc: -tc[1] * (1 + 0.5 * (len(tc[0].split()) - 1)))
    singles = [tc for tc in cands if " " not in tc[0]][:a.top // 3]
    phrases = [tc for tc in cands if " " in tc[0]][:a.top - len(singles)]
    cands = sorted(singles + phrases, key=lambda tc: -tc[1])[:a.top]

    os.makedirs(a.out, exist_ok=True)
    for old in glob.glob(os.path.join(a.out, "candidates_*.txt")):
        os.remove(old)
    chunks = [cands[i:i + a.chunk] for i in range(0, len(cands), a.chunk)]
    for k, chunk in enumerate(chunks, 1):
        with open(os.path.join(a.out, f"candidates_{k}.txt"), "w", encoding="utf-8") as f:
            f.write(HEADER.format(show=a.show) if k == 1 else "Next chunk, same rules:\n\n")
            for t, c in chunk:
                f.write(f"- {t}  ({c}x, {len(eps[t])} episodes)  e.g. \"{example[t]}\"\n")
    print(f"{len(cands)} candidates in {len(chunks)} file(s) in {a.out}/")


if __name__ == "__main__":
    main()
