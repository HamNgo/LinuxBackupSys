# Implementation architecture

The MVP targets one Ubuntu client and one Ubuntu server. Python 3.11+ standard
library implements the state machine; Bash exposes the CLI and scheduled job;
rsync performs transfers over OpenSSH. There is no database or daemon to run.

## Entrypoints

- Client: `bash backup-manager.sh --config /absolute/backup.conf COMMAND`.
- Server initialization: `python3 server/agent.py --config /absolute/server.conf init`.
- `server/agent.py session` and `rsync` are internal SSH protocol commands.
- `client/scheduled-backup.sh CONFIG` runs backup, then retention only on success.

## Managed layout

```text
STORAGE_ROOT/                        # service-owned, mode 0700
  CLIENT_ID/                        # service-owned, mode 0700
    owner.json
    usage.lock                      # shared backup/restore; exclusive cleanup
    writer.lock                     # exclusive backup control session
    history.jsonl                   # append-only operation events
    history.jsonl.lock
    .staging/
      SNAPSHOT_ID/
        run.json
        payload/                    # only source data
    snapshots/
      SNAPSHOT_ID/
        run.json                    # original transfer identity
        metadata.json               # completion record
        manifest.json
        payload/
```

Snapshot IDs use UTC `YYYYMMDDTHHMMSSffffffZ-12hex`. They are generated on the
server, validated before path use, and never reused. `latest` is derived from
completion metadata rather than a mutable symlink. Names alone are insufficient
to recognize completed snapshots. Unknown entries stop retention for inspection.

## Backup transaction

1. Validate config, source, key paths, and local log/source separation.
2. Scan source files and directories into a SHA-256 manifest. Reject symlinks,
   devices, FIFOs and sockets. A directory contributes its **contents**, including
   hidden files and empty directories; a single file keeps its basename.
3. Open a strict, noninteractive SSH control session. The server verifies client
   identity and takes a shared usage lock and exclusive writer lock.
4. Create a unique staging directory. Return its ID, never a client-chosen server
   destination. A separate SSH rsync process takes its own shared usage lock.
5. Transfer with rsync `-rpt`, without in-place writes, append, delete, or hard links.
   Any nonzero rsync exit (including partial/vanished-source) fails the operation.
6. Compare received content, modes and directory inventory against the source
   manifest when `VERIFY_CHECKSUM=true`. Otherwise record source verification as
   `skipped`; a received-data baseline is still stored for future verification.
7. Flush payload and metadata, then rename staging into `snapshots/` on the same
   filesystem. The server writes a success audit event and returns the result.

The data wrapper passes a shared lock descriptor to its rsync child. This keeps
cleanup excluded even if the wrapper/control connection disappears while the
data process is alive. An interrupted upload can only affect its own staging.
Staging is retained, never presented as a successful snapshot or removed by
normal retention. Stop/reconcile abandoned transfers before manually managing
staging; automatic staging garbage collection is not implemented.

Full copies are intentional in this version. `--link-dest` and SQLite remain
optional future improvements. Completed snapshots are never modified by backup,
restore or verify. Cleanup can add owner directory permissions only inside the
specific snapshot being deleted, so read-only source directories can be removed.

## Manifest and recovery

The manifest is JSON: `schema=1`, `algorithm="sha256"`, and an `entries` object
mapping payload-relative POSIX paths to typed entries. Files have type, size,
mode and SHA-256; directories have type and mode. Empty directories are recorded.
JSON escaping supports spaces, Unicode, newlines, quotes and shell characters in
valid UTF-8 data filenames. Duplicate keys, absolute paths, traversal and missing parents are
rejected. The manifest and control protocol have a 64 MiB message limit.

Restore first verifies the existing server baseline while holding a shared lock.
The selected file or directory is transferred into a new sibling staging folder
on the client and checked against the selected portion of that same manifest.
Selecting `a/` never selects `ab/`. A file is restored by basename; a directory
restores its contents. File selection uses a NUL-delimited rsync file list rather
than inserting its name into the remote shell.

Only after verification does the client exclusively create the requested new
destination and move the verified entries into it. Existing destinations are
always refused. If publication is interrupted, a partial new destination and/or
`.restore-*` folder can remain; the operation returns failure and records paths.
No overwrite mode is implemented. Cleanup stays locked out until both control
and data processes release their locks.

The restored container directory is private (0700). Nested directory/file modes
and modification times are transferred; SHA-256 plus the manifest validates
content, file size, file modes and directory inventory. Timestamps are transferred
but not checksum-verified. Ownership, ACLs, xattrs, sparse allocation, hard-link
relationships and the selected root directory's original mode are not restored.

## Retention

Server configuration owns retention, not the requesting client. A snapshot is
expired when `completed_at < now_UTC - RETENTION_DAYS * 24 hours`. Equality is
retained. Allowed days: 1–36500. At least the newest completed successful snapshot
is always retained, even if expired. Source-comparison-skipped snapshots still
count as completed; their verification status remains visible.

Cleanup defaults to dry-run and reports IDs, paths, times and reasons. `--apply`
recalculates the same decisions under an exclusive usage lock, validates every
candidate, then rechecks containment, ownership and mount boundaries immediately
before deleting each one. Staging and unknown data are not deletion candidates.
Each successful deletion is logged separately; failures are nonzero and can leave
a partially removed expired snapshot for operator inspection.

## History, failure and trust boundaries

JSONL events contain UTC time, run ID, operation, client ID, status and relevant
snapshot/result/error information. Client and server logs have independent locks
and fsync. `history --local` works without connecting to the server. No secrets or
file contents are logged, though paths and filenames can appear in error details.

Filesystem publication and history are not one transaction. A crash or audit
failure after rename can leave a valid snapshot despite a failed command. Consult
`status`, `verify ID`, completion metadata and both histories before retrying.
Unmatched `started` events indicate interruption, not success. A lost SSH response
also leaves the outcome uncertain: the client records `published="unknown"` after
requesting a commit until the server confirms it. Never infer absence from a timeout.

Storage and its parent directories must exclude untrusted writers. The dedicated
SSH backup account is trusted: the helper is not a sandbox or a forced-command
authentication boundary. A compromised backup key can modify that account's data.
SHA-256 does not protect against alteration of both payload and manifest. Mounted
remote storage inside the source must be excluded by the operator; same-host
source/destination overlap is checked using the Linux boot ID and canonical paths.

A file changing during hashing is rejected, and transfer data must match the
pre-transfer manifest. This does not establish application-consistent state across
multiple changing files. Quiesce applications or prepare a consistent export first.
Recovery is for files/directories, not bare-metal or live database recovery.

## References

Transport flags follow the [Ubuntu 24.04 rsync manual](https://manpages.ubuntu.com/manpages/noble/man1/rsync.1.html).
Host-key and noninteractive settings follow [OpenSSH ssh_config](https://man.openbsd.org/ssh_config).
