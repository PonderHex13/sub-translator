#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time

import requests

MODEL = "gams3-12b-instruct@q6_k"
URL = "http://localhost:1234/v1/chat/completions"
BATCH = 5
CONTEXT = 2
MAX_LINE = 42
TOKENS_PER_BLOCK = 160  # a normal block needs about 30, so 5 blocks allow 800 tokens
TEMPERATURE = 0
RETRY_TEMPERATURE = 0.5  # a rejected batch must be retried differently, 0 would repeat the same output
OUT_SUFFIX = ".sl"
COMMON_GLOSSARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary_common.txt")

DESCRIPTION = f"""\
Translate English .srt subtitles into Slovenian in one command.

For each input file NAME.srt the tool translates it with {MODEL} (served by
an OpenAI-compatible server), fixes the layout (at most two lines of {MAX_LINE} characters per block) and writes
a single file NAME{OUT_SUFFIX}.srt next to the input. Block numbers and timestamps are never changed.
Temporary progress files are removed when an episode is done. An interrupted
run resumes where it stopped. Episodes whose output exists are skipped (-f to redo).

After each episode a short summary of blocks that need a manual look is printed
(blocks left in English, blocks too long for two lines, glossary terms that seem
to be missing, unchanged English and repeated adjacent text). These are
heuristic warnings, not proof of an error. No review files are written.
Malformed batch responses are retried and, if necessary, split into smaller batches.
--sentence-batches optionally moves batch boundaries near sentence endings.
"""

EPILOG = """\
examples:
  %(prog)s subs/episode.srt
  %(prog)s subs/episode*.srt
  %(prog)s -f subs/episode.srt
  %(prog)s -n 30 subs/episode.srt   (quick test, first 30 blocks)

The glossary is read from glossary.txt next to the input file unless -g is given. It is combined with
glossary_common.txt (next to this script); entries in the show glossary win.
"""

SYSTEM = (
    "You are a professional English-to-Slovenian subtitle translator.\n"
    "Translate the provided dialogue into natural, fluent, contemporary spoken Slovenian "
    "(slovenščina), suitable for television and film.\n\n"
    "Translation rules:\n"
    "- Translate meaning, intent and tone, not word for word.\n"
    "- Use surrounding dialogue and the glossary to understand context and maintain consistency.\n"
    "- Preserve humour, sarcasm, irony, idioms, wordplay and emotional nuance. Use natural "
    "Slovenian equivalents where appropriate.\n"
    "- Use idiomatic Slovenian grammar and natural sentence structure. Never use Croatian or "
    "Serbian expressions.\n"
    "- Preserve character names and proper nouns, applying Slovenian grammatical inflection "
    "where appropriate.\n"
    "- Follow glossary translations consistently.\n"
    "- Preserve character relationships, formality and forms of address.\n"
    "- Infer gender only when supported by context.\n"
    "- Preserve the original tone and intensity, including profanity.\n"
    "- Be concise without sacrificing meaning.\n"
    "- Use normal Slovenian sentence case, regardless of source capitalisation.\n"
    "- Do not add explanations, interpretations or information absent from the source.\n\n"
    "Output requirements:\n"
    "- Translate only the blocks designated for translation; use surrounding blocks as context "
    "only. When dialogue is ambiguous, use context to choose the most natural translation "
    "without inventing unsupported details.\n"
    "- Preserve each translated block's number and order. Never merge, split, skip, reorder or "
    "add blocks, or move dialogue between blocks.\n"
    "- Preserve the exact ` // ` separator wherever it appears within a block.\n"
    "- Return exactly one line per block to be translated, in the format `N| translation`.\n"
    "- Output only translations, without explanations, notes, alternatives or Markdown."
)

SHORTEN_SYSTEM = (
    "You shorten Slovenian subtitles. You get the English original and a Slovenian translation that is "
    "too long for a subtitle. Rewrite the Slovenian so it keeps the meaning but is at most {limit} "
    "characters long, using natural spoken Slovenian. Output only the shortened Slovenian text, "
    "on one line, nothing else."
)

GLOSSARY_NOTE = "Glossary (use these Slovenian terms; inflect them as Slovenian grammar requires):\n"


# ---------- glossary and text helpers ----------

def merge_glossaries(show, common):
    """Show entries first; common entries only for English terms the show glossary does not define."""
    defined = {en.lower() for en, _, _ in show}
    return show + [t for t in common if t[0].lower() not in defined]


def load_glossary(path):
    terms = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            en, sl = (x.strip() for x in line.split("=", 1))
            if en and sl:
                terms.append((en, re.compile(r"(?<!\w)" + re.escape(en) + r"(?!\w)", re.I), sl))
    return terms


def terms_in(glossary, text):
    return [(en, sl) for en, rx, sl in glossary if rx.search(text)]


def is_shouting(text):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 2 and sum(c.isupper() for c in letters) / len(letters) > 0.6


def fix_case(text, glossary, starts_sentence):
    text = text.lower()
    # restore capitals of glossary terms in their glossary spelling; proper names
    # also match inflected forms (Teksas -> Teksasu, Čikago -> Čikaga)
    for _, _, sl in sorted(glossary, key=lambda g: -len(g[2])):
        if sl[0].isupper():
            base = sl[:-1] if len(sl) >= 4 and sl[-1].lower() in "aeiou" else sl
            text = re.sub(r"(?<!\w)" + re.escape(base) + r"(\w{0,4})(?!\w)",
                          lambda m, base=base: base + m.group(1), text, flags=re.I)
        else:
            text = re.sub(r"(?<!\w)" + re.escape(sl) + r"(?!\w)", sl, text, flags=re.I)
    chars = list(text)
    cap_next = starts_sentence
    for i, c in enumerate(chars):
        if c.isalpha():
            if cap_next:
                chars[i] = c.upper()
            cap_next = False
        elif c in ".!?…":
            cap_next = True
    return "".join(chars)


def ends_sentence(text):
    return bool(re.search(r"([.!?…]|--|–|—)[\"')\]]*\s*$", text))


def term_present(sl, out):
    """True if every word of the Slovenian glossary term appears (by stem) in the translation."""
    out = out.lower()

    def root(w):
        return w[:-2] if len(w) > 5 else w[:-1] if len(w) > 3 else w
    return all(root(w) in out for w in re.findall(r"\w+", sl.lower()))


def foreign_script(text):
    """True if the text contains Cyrillic, Greek, CJK or similar letters that never belong in Slovenian."""
    return bool(re.search(r"[\u0370-\u03FF\u0400-\u052F\u0590-\u06FF\u0900-\u0DFF\u3040-\u9FFF\uAC00-\uD7AF]", text))


def runaway(en, sl):
    """True if the model got stuck in a loop: a word repeated 4+ times in a row, or far too long for the source."""
    loop = r"\b(\w+)(?:\W+\1\b){3,}"
    if re.search(loop, sl, re.I) and not re.search(loop, en, re.I):
        return True
    return len(sl) > max(120, 4 * len(en))


def review_words(text):
    text = re.sub(r"</?[^>]+>|\{\\[^}]*\}", " ", text)
    return re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*", text.casefold())


def unchanged_english(source, translated, glossary):
    """Return unchanged full text or longer words, excluding keep-as-is entries."""
    for en, rx, sl in glossary:
        if en.casefold() == sl.casefold():
            source = rx.sub(" ", source)
            translated = rx.sub(" ", translated)
    source_words = review_words(source)
    target_words = review_words(translated)
    if not source_words or not target_words:
        return []
    if source_words == target_words:
        return ["entire remaining text: " + " ".join(source_words)]
    target_set = set(target_words)
    return list(dict.fromkeys(word for word in source_words
                              if len(word) >= 5 and word in target_set))


def repeated_adjacent(source_a, source_b, target_a, target_b):
    """Find substantial shared target phrases not repeated verbatim in source."""
    first, second = review_words(target_a), review_words(target_b)
    source_first, source_second = review_words(source_a), review_words(source_b)
    if source_first == source_second:
        return ""
    best = ()
    for i in range(len(first)):
        for j in range(len(second)):
            end = 0
            while (i + end < len(first) and j + end < len(second)
                   and first[i + end] == second[j + end]):
                end += 1
            phrase = tuple(first[i:i + end])
            if len(phrase) < 3 or sum(map(len, phrase)) < 12 or len(phrase) <= len(best):
                continue
            def contains(words):
                return any(tuple(words[k:k + len(phrase)]) == phrase
                           for k in range(len(words) - len(phrase) + 1))
            if not (contains(source_first) and contains(source_second)):
                best = phrase
    return " ".join(best)


# ---------- SRT ----------

def parse_srt(text):
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    blocks = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = raw.split("\n")
        if len(lines) >= 2 and "-->" in lines[1]:
            blocks.append({"num": lines[0].strip(), "time": lines[1].strip(), "text": lines[2:]})
    return blocks


def flat(block):
    return " // ".join(t.strip() for t in block["text"] if t.strip())


def sentence_boundary(text):
    text = re.sub(r"</?[^>]+>|\{\\[^}]*\}", "", text).strip()
    text = text.rstrip("\"'\u2019\u201d)]} ")
    if re.search(r"(?:\.{2,}|\u2026)$", text):
        return False
    if re.search(r"\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|etc)\.$", text, re.I):
        return False
    if re.search(r"\b(?:[a-z]\.){1,}$", text, re.I):
        return False
    return bool(re.search(r"[.!?]$", text))


def batch_ranges(src, size, sentence_batches=False):
    start = 0
    while start < len(src):
        target = min(start + size, len(src))
        end = target
        if sentence_batches and target < len(src):
            low = max(start + 1, target - 2)
            high = min(len(src), target + 2)
            candidates = [i for i in range(low, high + 1) if sentence_boundary(src[i - 1])]
            if candidates:
                end = min(candidates, key=lambda i: (abs(i - target), -i))
        yield start, end
        start = end


# ---------- model server ----------

def models_url(url):
    return url.rsplit("/chat/completions", 1)[0] + "/models"


def check_model(url, model):
    try:
        r = requests.get(models_url(url), timeout=15)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
    except (requests.RequestException, ValueError) as e:
        sys.exit(f"Cannot reach the model server at {models_url(url)}: {e}")
    if model not in ids:
        sys.exit(f"Model '{model}' is not available on the model server. Download/load it, or pass --model.\n"
                 f"Available: {', '.join(ids) or 'none'}")


def post_with_retry(url, timeout, payload, wait_total=900, pause=30):
    """POST to the model server; if the server is down or restarting, wait and retry for up to wait_total seconds."""
    start = time.time()
    while True:
        try:
            r = requests.post(url, timeout=timeout, json=payload)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            body = e.response.text.lower() if e.response is not None else ""
            if code == 400 and re.search(r"context|too long|exceed|token", body):
                raise  # prompt too long for the model: the caller splits the batch
            err = e  # anything else (e.g. "Model is unloaded", "terminated") is treated as temporary
        except (requests.ConnectionError, requests.Timeout) as e:
            err = e
        if time.time() - start > wait_total:
            raise err
        print(f"  Model server problem ({type(err).__name__}); waiting {pause}s and retrying...",
              file=sys.stderr, flush=True)
        time.sleep(pause)


def ask(a, prompt, temperature):
    payload = {
        "model": a.model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": TOKENS_PER_BLOCK * (a.blocks + (2 if getattr(a, "sentence_batches", False) else 0)),
    }
    if a.top_p is not None:
        payload["top_p"] = a.top_p
    if a.top_k is not None:
        payload["top_k"] = a.top_k
    r = post_with_retry(a.url, a.timeout, payload)
    out = r.json()["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def translate_batch(a, items, before, after, hints, temperature):
    """items: [(n, english)]. Returns {n: slovenian} or None if the reply is unusable."""
    prompt = ""
    if hints:
        prompt += GLOSSARY_NOTE + "\n".join(f"{en} = {sl}" for en, sl in hints) + "\n\n"
    if before:
        prompt += "Previous blocks (context only, do NOT translate):\n" + "\n".join(before) + "\n\n"
    prompt += "Translate these blocks:\n" + "\n".join(f"{n}| {t}" for n, t in items)
    if after:
        prompt += "\n\nFollowing blocks (context only, do NOT translate):\n" + "\n".join(after)
    expected = {n for n, _ in items}
    got = {}
    for line in ask(a, prompt, temperature).split("\n"):
        if not line.strip():
            continue
        m = re.fullmatch(r"\s*(\d+)\s*\|\s*(.*)", line)
        if not m:
            print("  Invalid batch response: unnumbered or malformed line", file=sys.stderr)
            return None
        number = int(m.group(1))
        if number not in expected:
            print(f"  Invalid batch response: unexpected block {number}", file=sys.stderr)
            return None
        if number in got:
            print(f"  Invalid batch response: duplicate block {number}", file=sys.stderr)
            return None
        got[number] = m.group(2).strip()
    missing = sorted(n for n in expected if not got.get(n))
    if missing:
        print(f"  Invalid batch response: missing or empty blocks {missing}", file=sys.stderr)
        return None
    invalid = [n for n, en in items if foreign_script(got[n]) or runaway(en, got[n])]
    if invalid:
        print(f"  Invalid batch response: foreign script or runaway text in blocks {invalid}", file=sys.stderr)
        return None
    return {n: got[n] for n, _ in items}


# ---------- step 1: translate ----------

def translate_blocks(a, src, prog_path, glossary):
    """Translate flattened blocks. Returns ({n: slovenian}, [numbers left in English])."""
    done = {}
    if os.path.exists(prog_path):
        with open(prog_path, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("model") == a.model and saved.get("total") == len(src):
            if saved.get("sentence_batches", False) != getattr(a, "sentence_batches", False):
                sys.exit(f"Progress file {prog_path} uses a different batching mode; "
                         "resume with the original mode or use a separate input file.")
            done = {int(k): v for k, v in saved["done"].items()}
            print(f"Resuming: {len(done)} blocks already translated")

    def save():
        with open(prog_path, "w", encoding="utf-8") as f:
            json.dump({"model": a.model, "total": len(src), "done": done,
                       "sentence_batches": getattr(a, "sentence_batches", False)}, f, ensure_ascii=False)

    failed = []

    def run(lo, hi):
        todo = [(i + 1, src[i]) for i in range(lo, hi) if src[i] and (i + 1) not in done]
        if not todo:
            return
        before = [src[i] for i in range(max(0, lo - a.context), lo) if src[i]]
        after = [src[i] for i in range(hi, min(len(src), hi + a.context)) if src[i]]
        hints = terms_in(glossary, " ".join(before + [t for _, t in todo] + after))
        tr = None
        for attempt in range(2):
            try:
                tr = translate_batch(a, todo, before, after, hints,
                                     a.temperature if attempt == 0 else max(a.temperature, RETRY_TEMPERATURE))
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    # usually the prompt exceeded the model's context: split the batch
                    print(f"  400 from server ({e.response.text[:120]!r}), splitting batch", file=sys.stderr)
                    break
                sys.exit(f"Model server request failed: {e}")
            except requests.RequestException as e:
                sys.exit(f"Model server request failed: {e}")
            if tr:
                break
        if tr:
            done.update(tr)
            save()
        elif hi - lo > 1:
            mid = (lo + hi) // 2
            run(lo, mid)
            run(mid, hi)
        else:
            failed.append(lo + 1)

    t0 = time.time()
    for lo, hi in batch_ranges(src, a.blocks, getattr(a, "sentence_batches", False)):
        run(lo, hi)
        print(f"{hi}/{len(src)} blocks ({time.time() - t0:.0f}s)", flush=True)

    final = {}
    prev_ended = True
    for i in range(len(src)):
        out = done.get(i + 1)
        if out and is_shouting(out):
            out = fix_case(out, glossary, prev_ended)
        if out:
            final[i + 1] = out
            prev_ended = ends_sentence(out)
    return final, failed


# ---------- step 2: layout ----------

def wrap_two_lines(text):
    """Split text into two lines at the space that balances the lines best, preferring punctuation."""
    words = text.split()
    best = None
    for i in range(1, len(words)):
        x, y = " ".join(words[:i]), " ".join(words[i:])
        score = max(len(x), len(y)) + (0 if re.search(r"[,.!?;:–—-]$", x) else 4)
        if best is None or score < best[0]:
            best = (score, [x, y])
    return best[1] if best else [text]


def shorten(a, en_text, sl_text):
    limit = a.max_line * 2 - 4
    if runaway(en_text, sl_text) or len(sl_text) > 4 * max(len(en_text), 20):
        sl_text = ""  # the draft is garbage: translate from the English only
    for attempt in range(2):
        r = post_with_retry(a.url, a.timeout, {
            "model": a.model,
            "messages": [
                {"role": "system", "content": SHORTEN_SYSTEM.format(limit=limit)},
                {"role": "user", "content": f"English: {en_text}\nSlovenian (too long): {sl_text}"
                 if sl_text else f"English: {en_text}\nWrite the Slovenian translation."},
            ],
            "temperature": 0.2 if attempt == 0 else 0.6,
            "max_tokens": 300,
        })
        out = r.json()["choices"][0]["message"]["content"].strip().split("\n")[0].strip().strip('"')
        out = re.sub(r"^(Slovenian|Slovensko)[^:]*:\s*", "", out)
        if out and len(out) <= a.max_line * 2 and not foreign_script(out):
            return out
    return None


def fix_layout(a, blocks, src, final):
    """Return (list of line lists, number re-wrapped, number shortened, review notes)."""
    result, notes = [], []
    wrapped = shortened = 0
    for i, b in enumerate(blocks):
        text_full = final.get(i + 1, src[i])
        lines = [l.strip() for l in text_full.split(" // ") if l.strip()]
        text = " ".join(lines)
        en_text = src[i].replace(" // ", " ")
        broken = runaway(en_text, text) if en_text else False
        if not broken and len(lines) <= 2 and not any(len(l) > a.max_line for l in lines):
            result.append(lines)
            continue
        new = None
        if broken or len(text) > a.max_line * 2:
            new = shorten(a, en_text, text)
            if new:
                text = new
                shortened += 1
            else:
                notes.append(f"block {b['num']}: {len(text)} chars, could not shorten: {text}")
        if broken and not new:
            text = en_text  # better readable English than a 6000-character loop
        result.append(wrap_two_lines(text) if len(text) > a.max_line else [text])
        wrapped += 1
    return result, wrapped, shortened, notes


# ---------- per file ----------

def process_file(a, path, glossary_arg):
    base, ext = os.path.splitext(path)
    out_path = f"{base}{OUT_SUFFIX}{ext}"
    if base.endswith(OUT_SUFFIX) or re.search(r"_SLO(_fixed)?$", base):
        print(f"Skipping {path}: looks like an already translated file")
        return
    if os.path.exists(out_path) and not a.force:
        print(f"Skipping {path}: {out_path} already exists")
        return

    gpath = glossary_arg or os.path.join(os.path.dirname(os.path.abspath(path)), "glossary.txt")
    glossary = load_glossary(gpath) if os.path.exists(gpath) else []
    if glossary_arg is None and not glossary:
        print(f"Note: no glossary.txt found next to {path}", file=sys.stderr)
    glossary = merge_glossaries(glossary, load_glossary(COMMON_GLOSSARY) if os.path.exists(COMMON_GLOSSARY) else [])

    with open(path, encoding="utf-8", errors="replace") as f:
        blocks = parse_srt(f.read())
    if a.limit:
        blocks = blocks[:a.limit]
    if not blocks:
        print(f"No subtitle blocks found in {path}", file=sys.stderr)
        return
    src = [flat(b) for b in blocks]

    d, name = os.path.split(path)
    prog_path = os.path.join(d, f".{name}.progress.json")

    print(f"== {name}: translating {len(blocks)} blocks")
    final, failed = translate_blocks(a, src, prog_path, glossary)

    print(f"== {name}: fixing layout")
    layout, wrapped, shortened, notes = fix_layout(a, blocks, src, final)

    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for b, lines in zip(blocks, layout):
            f.write(f"{b['num']}\n{b['time']}\n" + "\n".join(lines) + "\n\n")
    os.replace(tmp_path, out_path)
    if os.path.exists(prog_path):
        os.remove(prog_path)

    print(f"Wrote {out_path} ({wrapped} re-wrapped, {shortened} shortened by the model)")
    report(blocks, src, final, failed, notes, glossary, layout)


def report(blocks, src, final, failed, too_long, glossary, layout):
    misses = []
    unchanged = []
    repeated = []
    for i in range(len(blocks)):
        out = final.get(i + 1)
        if out:
            for en, sl in terms_in(glossary, src[i]):
                if not term_present(sl, out):
                    misses.append(f"block {blocks[i]['num']}: '{en}' -> '{sl}' not found in: {out}")
            matches = unchanged_english(src[i], " ".join(layout[i]), glossary)
            if matches:
                unchanged.append(
                    f"block {blocks[i]['num']}: {', '.join(matches)}\n"
                    f"      EN: {src[i]}\n      SL: {' '.join(layout[i])}"
                )
        if i and out and final.get(i):
            phrase = repeated_adjacent(src[i - 1], src[i],
                                       " ".join(layout[i - 1]), " ".join(layout[i]))
            if phrase:
                repeated.append(
                    f"blocks {blocks[i - 1]['num']}-{blocks[i]['num']}: '{phrase}'\n"
                    f"      EN: {src[i - 1]} / {src[i]}\n"
                    f"      SL: {' '.join(layout[i - 1])} / {' '.join(layout[i])}"
                )
    sections = [
        ("left in English", [f"block {blocks[n - 1]['num']}: {src[n - 1]}" for n in failed]),
        ("too long for two lines", too_long),
        ("glossary term not found (often a false alarm from inflection)", misses),
        ("unchanged English (may be valid)", unchanged),
        ("repeated adjacent translation (may be intentional)", repeated),
    ]
    if not any(items for _, items in sections):
        print("Nothing to review.")
        return
    print("To review:")
    for title, items in sections:
        if items:
            print(f"  {title} ({len(items)}):")
            for line in items[:50]:
                print(f"    {line}")
            if len(items) > 50:
                print(f"    ... and {len(items) - 50} more")


def main():
    ap = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="+", help="English .srt file(s) to translate")
    ap.add_argument("-f", "--force", action="store_true", help="redo files whose output already exists")
    ap.add_argument("-g", "--glossary", metavar="FILE",
                    help="glossary file 'English = Slovenian' (default: glossary.txt next to each input)")
    ap.add_argument("-n", "--limit", type=int, default=0, metavar="N",
                    help="only translate the first N blocks (for testing)")
    ap.add_argument("--model", default=MODEL, help="model id as listed by the server (default: %(default)s)")
    ap.add_argument("--url", default=URL, help="OpenAI-compatible chat completions URL (default: %(default)s)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per request (default: 600)")
    ap.add_argument("--temperature", type=float, default=TEMPERATURE,
                    help="sampling temperature for translation (default: %(default)s)")
    ap.add_argument("--top-p", type=float, default=None, help="top-p sampling (default: server setting)")
    ap.add_argument("--top-k", type=int, default=None, help="top-k sampling (default: server setting)")
    ap.add_argument("-b", "--blocks", type=int, default=BATCH, metavar="N",
                    help="blocks translated per request (default: %(default)s)")
    ap.add_argument("--sentence-batches", action="store_true",
                    help="experiment: choose sentence endings within two blocks of the target batch size")
    ap.add_argument("-c", "--context", type=int, default=CONTEXT, metavar="N",
                    help="context blocks sent before and after each batch (default: %(default)s)")
    a = ap.parse_args()
    if a.blocks < 1 or a.context < 0:
        ap.error("--blocks must be at least 1 and --context 0 or more")
    a.max_line = MAX_LINE

    if a.model != MODEL:
        print(f"Warning: using {a.model}; the prompt and settings were tuned for {MODEL}.", file=sys.stderr)
    check_model(a.url, a.model)
    for path in a.input:
        process_file(a, path, a.glossary)


if __name__ == "__main__":
    main()
