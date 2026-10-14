## What

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- The problem this solves. -->

## How verified

<!--
This project reads data that cannot be shared, so describe the evidence:
which command, on what data shape, and what you expected vs got.
-->

```bash
qq-cli ...
```

## Checklist

- [ ] No databases, keys, or decrypted artifacts are included
- [ ] `python -m compileall -q qq_cli` passes
- [ ] `qq-cli keys verify` and one query command still work
- [ ] Updated `README.md` and `README_ZH.md` if behaviour changed
