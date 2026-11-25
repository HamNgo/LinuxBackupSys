# Tests and observed evidence

## Reproduce

From a Linux checkout with Python 3.11+, Bash and rsync installed:

```bash
bash tests/run.sh
```

The runner validates Bash syntax, runs ShellCheck if installed, then standard
library `unittest`. Fixtures live under a new `tempfile.TemporaryDirectory` on the
Linux filesystem, use isolated configs/storage/keys, and are removed by the test
framework. No production config, service or backup is accessed.

`test_core.py` tests parsing, manifest/path validation, version metadata and
retention. `test_workflow.py` runs actual rsync, server processes, locks and file
verification. Only SSH is replaced by a local shell adapter, so these are **not**
authentication or LAN tests. Assertions compare independent pre-backup manifests
and expected bytes, and check retained snapshots and outside sentinels.

For the desktop tests, use a graphical session with Python Tk, or run
`xvfb-run -a bash tests/run.sh` on a headless Linux host with Tk, Xvfb and
xauth installed. `test_desktop.py` drives native widgets with a fixture
runner. It covers snapshot selection, browsing nested paths, restore and error
handling. `test_desktop_config.py` saves configurations and reads them back
through the CLI parser.

Optional real SSH test, in a disposable root-controlled Ubuntu CI/VM with
`openssh-server` already installed and `/run/sshd` prepared:

```bash
sudo env LINUX_BACKUP_TEST_SSH=1 python3 -m unittest tests.test_ssh -v
```

It generates temporary host/client keys, pins the exact generated host key, starts
a temporary sshd bound to loopback on a dynamic port, runs backup/restore, and
checks unknown-host and wrong-key failures. It does not modify global SSH config,
existing users, trusted hosts or keys. The root login permitted by this isolated
test daemon is test-only; real deployment uses the dedicated non-root account.

GitHub Actions is configured for Ubuntu 24.04, ShellCheck, the local suite under Xvfb and the
optional localhost SSH test. Adding the workflow is not evidence of a CI run.

## Desktop verification (2026-11-25)

On Ubuntu WSL, the native restore dialog was used to browse a nested directory
in an older backup and restore a file with a Vietnamese name. The recovered
bytes matched that version and the source retained the newer bytes. This test
used the real CLI, server processes and rsync with a local adapter for SSH.
A separate run exercised the desktop command runner through a temporary
OpenSSH server on loopback, including backup, listing, verification, restore,
history and retention preview. Testing over Tailscale between separate Arch and
Ubuntu machines remains pending.

## Observed environment (2026-11-17)

- Editing host: Windows, PowerShell.
- Runtime tests: WSL2 Ubuntu **26.04.1**, Linux filesystem `/tmp` (not NTFS).
- Python 3.14.4; rsync 3.4.1, protocol 32.
- WSL runtime users: the complete local suite passed both as root and as the
  existing unprivileged `nobody` account. The latter exercises actual Linux
  ownership and mode enforcement. Target-machine account setup still needs
  validation; explicit deletion/ENOSPC failures are injected with mocks.
- This is not a claim of two-machine Ubuntu 24.04 integration or a scheduled run.

## Baseline verification results (2026-11-17)

| Command/check | Actual result |
| --- | --- |
| `bash tests/run.sh` as root | PASS: 43 discovered, 42 passed, 1 SSH test skipped; exit 0 |
| `runuser -u nobody -- env PYTHONDONTWRITEBYTECODE=1 bash tests/run.sh` | PASS: 43 discovered, 42 passed, 1 SSH test skipped; exit 0 |
| `bash -n` on all four Bash scripts (inside runner) | PASS |
| `python3 -m compileall -q common client server tests` | PASS on WSL |
| `python -m compileall -q common client server tests` | PASS on Windows Python 3.13.5 (syntax only) |
| Installer into a fresh Linux temporary directory | PASS; runtime files/templates present, no bytecode copied, existing target refused |
| `systemd-analyze verify` on the installed temporary service/timer | PASS; exit 0 with Linux file permissions |
| `git diff --check` | PASS |
| ShellCheck | SKIP: not installed locally; required by configured CI workflow |
| Real localhost SSH test | SKIP: `/usr/sbin/sshd` unavailable locally; opt-in fixture supplied |

Direct unit validation on the Windows-mounted checkout initially emitted mode
warnings because DrvFS exposed the source files as executable/world-writable.
Validation of the installer output on the Linux filesystem completed without
those warnings. Neither check enabled a service or timer.

## Coverage and outstanding validation

| Area | Checks | Evidence kind |
| --- | --- | --- |
| Configuration | typed values, unknown keys, literal shell characters, invalid paths, writable config | Local tests |
| Payload | hidden files, empty file/directory, binary, Unicode, spaces, quotes, newlines, wildcard filenames | Real rsync locally |
| Versions | change/delete/add, restore old file/subtree/whole tree, old version unchanged | Real rsync locally |
| Integrity | modified/missing/extra file, mode change, corrupt manifest, changed source during transfer | Local workflows and unit tests |
| Publication | transfer failure, ID collision, metadata write failure, post-publication log failure | Real workflow plus injected failures |
| Locks | busy writer, exclusive cleanup, rsync retains lock after wrapper is killed | Real Linux flock/processes |
| Restore | existing destination/source overlap/symlink/traversal refused, corrupt transfer cannot publish | Local workflows |
| Retention | expiry boundary, newest-only, empty set, dry-run/apply match, staging untouched | Linux filesystem fixtures |
| Cleanup failures | unexpected entries, symlink/sentinel, nested mount detection, deletion failure | Fixtures; mount/deletion error mocked |
| SSH host/auth | backup/restore, unknown host key and wrong client key against temporary localhost sshd | Passed on Ubuntu WSL on 2026-11-25 |
| ShellCheck | optional runner and required CI check | SKIP locally: tool unavailable |
| Ubuntu 24.04 LAN | separate server/client with dedicated account | Pending target environment |
| Timer and reboot | daily schedule, missed run, real job-user environment | Pending target deployment |
| ENOSPC/network interruption | explicit injected failures; no real disk exhaustion | Real constrained filesystem/network validation pending |

Supported limitations: regular files/directories only; no source snapshots,
application quiescing, symlink payloads, ACL/xattr/ownership preservation, hard-link
deduplication, log rotation or automatic abandoned-staging cleanup.
