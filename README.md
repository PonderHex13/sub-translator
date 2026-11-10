# Subtitle translator

`translate.py` translates English SRT subtitles into Slovenian using a model
served by LM Studio. It calls LM Studio's local API using the OpenAI-compatible
`/v1/chat/completions` endpoint; it does not call OpenAI's hosted API.

## Setup

- Python 3
- `requests` (`python3 -m pip install requests`)
- LM Studio running locally with a model loaded and its local API enabled
  (default address: `http://localhost:1234`)

## Usage

Translate one file:

```bash
python3 translate.py subs/Boston_Legal_S01E01.srt
```

Translate matching files in order:

```bash
python3 translate.py subs/Boston_Legal_S01E*.srt
```

Each input `NAME.srt` produces `NAME.sl.srt` beside it. Existing outputs are
skipped unless `--force` is used. Use `-n N` to translate only the first N
subtitle blocks.

Defaults:

| Option | Default |
| --- | --- |
| `--model` | `gams3-12b-instruct@q6_k` |
| `--url` | `http://localhost:1234/v1/chat/completions` |
| `--timeout` | 600 seconds |
| `--temperature` | 0 |
| `--top-p`, `--top-k` | Server settings (not sent unless specified) |
| `-b`, `--blocks` | 5 blocks per request |
| `-c`, `--context` | 2 neighboring blocks before and after each batch |
| `-n`, `--limit` | 0 (all blocks) |
| `-g`, `--glossary` | `glossary.txt` beside each input |
| `-f`, `--force` | Off (existing outputs are skipped) |
| `--sentence-batches` | Off |

To use another model or OpenAI-compatible server, pass its model ID and
chat-completions URL:

```bash
python3 translate.py --model MODEL --url http://localhost:1234/v1/chat/completions input.srt
```

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
python3 tools/glossary_candidates.py subs/Boston_Legal_S01E*.srt
```

Run the tests with:

```bash
python3 -m unittest discover -s tools -v
```

## AI use

AI tools assisted in creating this project. The maintainer is responsible for
its contents and ongoing maintenance.
