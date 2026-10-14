# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue.

Report privately through GitHub's [Security Advisory](https://github.com/anthonyhann/qq-cli/security/advisories/new)
flow, or email the maintainer listed on the GitHub profile.

Include the version, macOS version, and a description of the impact. Never include a real
database key, chat content, or a database file.

## Threat model

QQ CLI runs locally against databases it does not own. The relevant risks:

| Risk | Mitigation |
|---|---|
| Key leaks into shell history / logs | Key is passed via a `0600` file, not the command line; the tool never prints it |
| Key leaks into world-readable files | `~/.qq-cli/` is `0700`, key file `0600`, written atomically |
| Decrypted data lands somewhere shared | Cache is `0700` and namespaced by account path + key fingerprint |
| Symlink attack on key/cache paths | Symlinked key files, cache dirs, and WAL paths are refused |
| Path traversal via database name | Relative-path validation; absolute paths and `..` rejected |
| Silent corruption when QQ is writing | File stamps (device/inode/size/mtime/ctime) are compared around decryption |
| Modifying the user's QQ install | The tool never writes to `/Applications`; extraction works on a copy |

## What this tool does not protect against

- **A compromised local account.** Anyone who can run code as you can read `~/.qq-cli/`.
- **An attacker with the key.** The key grants full read access to the databases.
- **Third-party mirrors.** Install dependencies from `pypi.org`; a malicious mirror could
  serve a tampered `sqlcipher3`.

## Scope

In scope: key handling, cache isolation, path validation, decryption correctness, and any
way the tool could write to or corrupt QQ's data.

Out of scope: the fact that QQ stores data locally in a recoverable form, and the
extraction technique itself — that is the documented purpose of the project.
