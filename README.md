# Subtitle translator

`translate.py` translates English SRT subtitles into Slovenian using a model
served by any OpenAI-compatible server (for example LM Studio or Lemonade). It
calls the `/v1/chat/completions` endpoint and the matching `/models` endpoint
of the URL you give it; it does not call OpenAI's hosted API.

The tool can be adapted to other target languages by changing the prompts, the
output suffix, the script check, the glossaries and the model. Slovenian is
currently built into `translate.py`.

## Setup

- Python 3
- `requests` (`python3 -m pip install requests`)
- An OpenAI-compatible server running locally with the model available
  (default: LM Studio at `http://localhost:1234`; Lemonade, for example, uses
  `http://localhost:13305/api/v1/chat/completions`)

## Usage

Translate one file:

```bash
python3 translate.py subs/Show.S01E01.srt
```

Translate matching files in order:

```bash
python3 translate.py subs/Show.S01E*.srt
```

Each input `NAME.srt` produces `NAME.sl.srt` beside it. Existing outputs are
skipped unless `--force` is used. Use `-n N` to translate only the first N
subtitle blocks.

Defaults are tuned for the GaMS3 12B model (Q6_K) on a 16 GB Radeon RX 7800 XT
with 4 parallel slots and flash attention on. Other hardware may prefer other
values; see "Parallel requests" below.

| Option | Default |
| --- | --- |
| `--model` | `gams3-12b-instruct@q6_k` |
| `--url` | `http://localhost:1234/v1/chat/completions` |
| `--timeout` | 600 seconds |
| `--temperature` | 0 |
| `--top-p`, `--top-k` | Server settings (not sent unless specified) |
| `-b`, `--blocks` | 10 blocks per request |
| `-c`, `--context` | 2 neighboring blocks before and after each batch |
| `-n`, `--limit` | 0 (all blocks) |
| `-g`, `--glossary` | `glossary.txt` beside each input |
| `-f`, `--force` | Off (existing outputs are skipped) |
| `-j`, `--jobs` | 1 (parallel requests per file) |
| `--sentence-batches` | Off |

## Parallel requests

`-j N` sends up to N batches of the same file to the server at once, which
speeds up a file when the server can serve several requests in parallel. The
server must have at least N slots, otherwise the extra requests just wait.
For example, with llama.cpp or Lemonade, load the model with 4 slots and run:

```bash
lemonade load MODEL --ctx-size 12288 --llamacpp-args "--parallel 4 -fa on"
python3 translate.py -j 4 subs/Show.S01E01.srt
```

Keep flash attention on (`-fa on`, or the server's automatic setting, which is
on in recent llama.cpp builds). Switching it off (`-fa off`) made the test card
about 7 times slower.

The server's context window is shared between its slots, so scale it with the
slot count: about 3,000 tokens per slot is enough for the default batch size.
More slots use more VRAM, and speed gains flatten once the GPU is fully busy.
On one test card (16 GB), 4 streams were about 2.3 times as fast as one on real
episodes, more than 5 gave nothing, and 8 slots were slower. Use
`tools/tune_streams.py` to find the best setting for your hardware.
Each batch is translated independently, so `-j` does not change the approach, but
the wording of a few lines can differ slightly from a `-j 1` run, because
parallel requests change how the server computes them. An interrupted run still
resumes from its progress file.

To use another model or server, pass its model ID (as listed by the server's
`/models` endpoint) and chat-completions URL:

```bash
python3 translate.py --model MODEL --url http://localhost:1234/v1/chat/completions input.srt
```

Progress files record the model ID, so an interrupted episode resumes only
with the same `--model`.

Run `python3 translate.py --help` for all options, including batching and
generation settings.

## Glossaries

The script combines `glossary_common.txt` in the project directory with
`glossary.txt` beside each subtitle file. Show-specific entries take
precedence. Entries use one `English term = Slovenian translation` pair per
line. Use `-g FILE` to specify a show glossary.

## Other tools and tests

`tools/glossary_candidates.py` finds frequent terms missing from the glossaries
for manual review:

```bash
python3 tools/glossary_candidates.py subs/Show.S01E*.srt
```

Run the tests with:

```bash
python3 -m unittest discover -s tools/tests -v
```

## AI use

AI tools were used in creating this project.
