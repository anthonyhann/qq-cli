# Contributing

Thanks for your interest in QQ CLI.

## Ground rules

This project reads **private chat data** with a **database key**. Two rules are absolute:

1. **Never commit real data.** No databases, no decrypted artifacts, no keys, no chat
   exports, no screenshots containing message content. `.gitignore` covers the common
   cases, but check `git status` before every commit.
2. **Never commit a key.** Even a test key must be fabricated. If you accidentally commit
   one, rotate it — the key is trivial to extract again, but assume it is burned.

## Development setup

```bash
git clone https://github.com/anthonyhann/qq-cli.git
cd qq-cli

uv venv --python 3.10 .venv
export UV_INDEX_URL=https://pypi.org/simple/
uv pip install --python .venv/bin/python click sqlcipher3
uv pip install --python .venv/bin/python -e .
```

Python 3.10 is required: `sqlcipher3` only publishes prebuilt wheels for cp310.

## Testing

There is no offline test suite, because the whole point is reading a real local database.
The practical loop is:

```bash
qq-cli keys verify          # keys parse and open the databases
qq-cli sessions --limit 5   # decryption + session aggregation
qq-cli history <group> -n 5 # message query + Protobuf parsing
qq-cli search <term>        # cross-conversation search
```

Before opening a PR, run the smoke script against your own data:

```bash
python tests/smoke.py
```

For changes to decryption or the cache, also clear the cache and re-run end to end:

```bash
rm -rf ~/.cache/qq-cli

```

## What to work on

Good first contributions:

- **Additional message types** in `qq_cli/core/proto.py` — extend the wire scanner to cover
  transfer cards, replies, and system notices.
- **Field documentation** in `qq_cli/core/fields.py` — many numbered columns still lack a
  confirmed meaning. Add a report with sample evidence rather than a guess.
- **Linux / Windows support** — the extraction path is macOS-only today.

## Pull requests

- One logical change per PR
- Explain *how you verified it* — which command, on what data shape, and what you expected
- If behaviour changes, update both `README.md` and `README_ZH.md`
- Expect review to ask for evidence: this project deals with data that cannot be shared,
  so reproducible reasoning matters more than a test fixture

## Reporting issues

Include: macOS version, QQ version, the exact command, and the observed vs expected output.

**Redact message content.** Paste structure and error text, not people's conversations.
Never paste a key.

## Security issues

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
