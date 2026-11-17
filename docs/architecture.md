# Architecture (Day 1 decisions)

Draft for both members to review and confirm.

## Roles

| Computer | Role | Owner |
|---|---|---|
| A | Backup server (OpenSSH, storage, retention, logs) | Member 1 |
| B | Backup client (backup/restore scripts, checksums) | Member 2 |

## Server storage layout

```text
/srv/backups/
└── <client-name>/
    ├── 2026-11-17_19-30-00/     # one directory per backup run
    ├── 2026-11-18_19-30-00/     # unchanged files hard-linked via --link-dest
    └── latest -> 2026-11-18_19-30-00
```

- **Snapshot name:** `YYYY-MM-DD_HH-MM-SS` (sortable, so the oldest/newest is obvious).
- **One snapshot = one full-looking tree.** Unchanged files share disk blocks through hard links.
- All snapshots for a client must stay on the same filesystem for `--link-dest` to work.
- Partial or failed runs are written to a temporary name (e.g. `.incomplete-<timestamp>`) and renamed only on success, so `latest` always points at a complete snapshot.

## Accounts and access

- Server account: `backupuser` (no password, SSH key only).
- Root SSH login disabled.
- Client key options: no port/X11/agent forwarding, no PTY.
- Possible later hardening: restrict the key to a forced command (e.g. `rrsync`) once the server-side scripts are stable.

## Config files

| File | Location | Used by |
|---|---|---|
| `server/server.conf` | `/etc/linux-backup/server.conf` | server scripts |
| `client/client.conf` | `/etc/linux-backup/client.conf` | client scripts |

Both are Bash-sourceable `KEY="value"` files.

## Interfaces to agree with Member 2

1. **Client name:** short identifier matching `[A-Za-z0-9_-]+`. It becomes the directory name on the server.
2. **Snapshot creation:** who creates the directory and runs `--link-dest`? Proposal: the client runs rsync directly into `.incomplete-<ts>` and then calls a server script (`manage_snapshots.sh finalize <client> <ts>`) over SSH to rename it and update `latest`.
3. **Log format:** one line per event, `ISO-8601 timestamp | level | client | message`.
4. **Exit codes:** `0` success, non-zero failure, so history can record the result.

## Open questions

- Are both computers physical machines or VMs? (Affects the network setup and the reboot test on Day 13.)
- Which hostname or IP will the server use? A static IP or DHCP reservation avoids surprises.
- Is `/srv/backups` on a separate disk or partition? If not, make sure there is enough free space for the demo.
