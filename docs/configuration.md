# Configuration and CLI

Configuration files use **TOML**, parsed as data, never sourced as shell. Python
3.11+ is required. Unknown keys, duplicate TOML keys, missing required values and
wrong types fail before starting operations. Strings are quoted, integers are not,
and booleans are lowercase `true`/`false`. No environment expansion/interpolation
or environment overrides are supported. `--config` selects the file; operation
flags control only their documented operation.

```bash
bash backup-manager.sh configure --role client --output /absolute/new-backup.conf
bash backup-manager.sh configure --role server --output /absolute/new-server.conf
bash backup-manager.sh --config /absolute/backup.conf configure --check
bash backup-manager.sh --config /absolute/server.conf configure --role server --check
```

Generation never overwrites a file. Edit the placeholders, then validate. Validation
checks syntax/types/canonical paths, not connectivity or source readability.
Config files must be owned by root or the runtime account and not writable by
group/others (0640 or 0600 is suitable). Paths must be absolute and contain no
symlink components or `..`. Source filenames may contain newlines, but configured
paths are single-line values.

## Client settings

See [client.conf.example](../client/client.conf.example).

| Key | Meaning | Default |
| --- | --- | --- |
| `CLIENT_ID` | 1–64 letters/digits/underscore/hyphen, first character alphanumeric; must match server | Required |
| `BACKUP_SOURCE` | Local directory contents or one regular file | Required |
| `SSH_HOST` | Server IPv4 or DNS name, not SSH config alias requiring custom options | Required |
| `SSH_USER` | Dedicated server account | Required |
| `SSH_PORT` | Integer 1–65535 | 22 |
| `SSH_IDENTITY` | Existing private key, readable only by the job account | Required |
| `SSH_KNOWN_HOSTS` | Existing known-hosts file with verified server identity | Required |
| `SERVER_PROGRAM` | Server's absolute installed `server/agent.py` | Required |
| `SERVER_CONFIG` | Server's absolute TOML configuration file | Required |
| `LOG_FILE` | Local JSONL log; parent must already exist | Required |
| `RESTORE_ROOT` | Existing parent for automatic new restore directories | Required |
| `VERIFY_CHECKSUM` | Compare received data with pre-transfer source SHA-256 manifest | true |
| `COMPRESSION` | rsync wire compression only; snapshots remain ordinary files | false |
| `TIMEOUT_SECONDS` | Integer 1–86400; control message, transfer and inactivity limits | 300 |

Templates use a one-hour timeout. Set a value larger than the longest expected
transfer/hash phase on **both** hosts. The timeout is a bound per phase, not a
guarantee that a remote operation did not finish after an SSH response was lost.

Source must be separate from key, known-hosts, logs and restore root. Source may
not overlap server storage when both roles run on the same Linux instance. Use a
dedicated subtree; backing up `/` or the service account's entire home is unsuitable.

SSH uses `-F /dev/null`, strict host-key checking, batch mode and identities-only
authentication. It does not load personal SSH configuration, ProxyCommand or jump
host settings. Prepare keys/known-hosts for the exact account running the timer.
Passphrase-protected keys need an explicitly available SSH agent; the simplest
unattended lab setup is a dedicated restricted-use key with mode 0600.

`VERIFY_CHECKSUM=false` skips source-to-server comparison only. Source scanning
and received-baseline creation still hash files; disabling comparison is not a
hashing-performance optimization. `verify` and `restore` always verify the stored
manifest and report the original source-verification status independently.

## Server settings

See [server.conf.example](../server/server.conf.example).

| Key | Meaning | Default |
| --- | --- | --- |
| `CLIENT_ID` | Single authorized logical client | Required |
| `STORAGE_ROOT` | Dedicated server-owned directory, 0700, at least two levels below `/` | Required |
| `RETENTION_DAYS` | Whole 24-hour periods from UTC completion; 1–36500 | 7 |
| `TIMEOUT_SECONDS` | Control-session timeout, 1–86400 seconds | 300 |

Initialize explicitly as the backup account. `init` is idempotent for a valid
managed layout and does not adopt unknown existing client directories. No account,
package, SSH key or system service is created by the runtime.

## Management commands

All commands print JSON results to stdout; errors and rsync output go to stderr.
Put the global `--config` option **before** the command.

```bash
bash backup-manager.sh --config /etc/linux-backup/backup.conf status
bash backup-manager.sh --config /etc/linux-backup/backup.conf backup
bash backup-manager.sh --config /etc/linux-backup/backup.conf verify SNAPSHOT_ID
bash backup-manager.sh --config /etc/linux-backup/backup.conf list-files SNAPSHOT_ID --path 'reports'
bash backup-manager.sh --config /etc/linux-backup/backup.conf restore SNAPSHOT_ID
bash backup-manager.sh --config /etc/linux-backup/backup.conf restore SNAPSHOT_ID --path 'reports/annual.txt' --destination /home/backup-client/Restored/annual
bash backup-manager.sh --config /etc/linux-backup/backup.conf history --limit 20 --operation backup
bash backup-manager.sh --config /etc/linux-backup/backup.conf history --local --limit 20
bash backup-manager.sh --config /etc/linux-backup/backup.conf cleanup --dry-run
bash backup-manager.sh --config /etc/linux-backup/backup.conf cleanup --apply
```

The selected restore destination must not exist; its parent must exist. Without
`--destination`, a unique directory is created inside `RESTORE_ROOT`. No overwrite
flag exists in the MVP. File restore yields `DESTINATION/basename`; directory
restore yields the directory's contents under `DESTINATION`.

| Exit | Meaning |
| --- | --- |
| 0 | Requested operation completed, required audit write succeeded |
| 1 | Filesystem, metadata, history or other runtime failure |
| 2 | Invalid input/config/path/unsupported object |
| 3 | Lock busy; retry later |
| 4 | SSH, rsync, control disconnect or timeout |
| 5 | Integrity/manifest verification failure |
| 130 | User interruption |

An interrupted or failed command can still have published data if the failure
occurred after publication. Always inspect `status` and history before retrying.
