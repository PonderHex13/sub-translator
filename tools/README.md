# Tools

## `glossary_candidates.py`

Finds frequent English words and short phrases in subtitle files that are not
already in the show or common glossary. It writes candidate lists with example
lines for manual review; it does not translate subtitles or update glossaries.

```bash
python3 tools/glossary_candidates.py subs/Show.S01E*.srt
```

Options and defaults:

| Option | Default | Description |
| --- | --- | --- |
| `-s`, `--show SHOW` | `the series` | Show or series name included in the instructions in the candidate files. |
| `-g`, `--glossary FILE` | `glossary.txt` beside the first input | Show glossary to exclude from candidates. The common glossary is also checked. |
| `-o`, `--out DIR` | `glossary_paste` | Folder for output files. Existing `candidates_*.txt` files in this folder are replaced. |
| `--min-count N` | `5` | Minimum occurrences for a candidate. |
| `--min-episodes N` | `2` | Minimum input files in which a candidate appears; capped at the number of input files. |
| `--top N` | `300` | Maximum number of candidates. |
| `--chunk N` | `100` | Candidates per output file. |
| `--keep-refs` | Off | Include reference blocks listed in `Tests/ref_E*.txt`; by default, these blocks are excluded when matching files exist. |

Use `--help` to see the full command usage.

## `tune_streams.py`

Finds how many parallel streams (`translate.py -j N`) give the best speed on
your server and GPU. For each N it translates `tools/sample_tune.srt` (100
synthetic English blocks, so no subtitle files are needed) with
`translate.py -j N`, times it, and prints a table with blocks per second, speed
per stream, speedup over one stream and the number of rejected batches. It then
recommends the smallest N within 10% of the best rate. Run it while the GPU is
otherwise idle.

```bash
python3 tools/tune_streams.py --url http://localhost:13305/api/v1/chat/completions --model MODEL
```

Options and defaults:

| Option | Default | Description |
| --- | --- | --- |
| `--streams LIST` | `1-4` | Stream counts to test, a range or a list such as `1,2,4`. |
| `--blocks N` | `100` | Blocks translated per timed run (at most the sample size). Each count also gets an untimed 20-block warm-up. |
| `--runs N` | `1` | Timed runs per stream count; the mean is used. |
| `--tolerance X` | `0.10` | Recommend the smallest N within this fraction of the best rate. |
| `--sample FILE` | `tools/sample_tune.srt` | English `.srt` used for the test. |
| `--slots-cmd CMD` | Off | Shell command run before each N to set the server's slot count; `{n}` is the number of streams and `{ctx}` a context size of about 3,000 tokens per slot. |
| `--url`, `--model` | `translate.py` defaults | Passed on to `translate.py`; other unknown options are passed on too. |

Without `--slots-cmd` the tool does not touch the server, so load the model
with at least as many slots as the largest N first. Results above the server's
slot count are meaningless because the extra requests just queue. A model loaded
with many slots can also be slower per stream (8 slots halved the speed of one
stream on one test card), so `--slots-cmd` gives the most reliable numbers. For
Lemonade:

```bash
python3 tools/tune_streams.py --url http://localhost:13305/api/v1/chat/completions \
  --model GaMS3-12B-Instruct.Q6_K \
  --slots-cmd "lemonade load GaMS3-12B-Instruct.Q6_K --ctx-size {ctx} --llamacpp-args '--parallel {n}'"
```

## Tests

The unit tests are in `tools/tests/`. The `test_translate_*.py` files cover
batching and resume validation, translation review checks, model-response
validation and retry behavior, and parallel requests (`--jobs`);
`test_tune_streams.py` covers `tune_streams.py`. They use mocked model
responses, so no model server is needed. Run all tests from the project root:

```bash
python3 -m unittest discover -s tools/tests -v
```
