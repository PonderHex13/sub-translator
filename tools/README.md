# Tools

## `glossary_candidates.py`

Finds frequent English words and short phrases in subtitle files that are not
already in the show or common glossary. It writes candidate lists with example
lines for manual review; it does not translate subtitles or update glossaries.

```bash
python3 tools/glossary_candidates.py subs/Boston_Legal_S01E*.srt
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

## Tests

The `test_translate_*.py` files are unit tests for batching and resume
validation, translation review checks, and model-response validation and retry
behavior. They use mocked model responses, so no LM Studio server is needed.
Run all tests from the project root:

```bash
python3 -m unittest discover -s tools -v
```
