# Repeatable 10–15 minute demo

Use disposable data and a dedicated demonstration config and storage directory.
For **one Arch Linux VM**, follow the [local desktop demo (Vietnamese)](setup-arch-local.vi.md)
from setup through recovery. It creates its own test file and shows how to reopen
the same profile in a new terminal. For **two machines**, complete the
[two-machine setup](setup.md) and verify noninteractive SSH as the job account
before running the example below.

1. Create an isolated client directory and set `BACKUP_SOURCE` to that exact path:

   ```bash
   demo_root=$(mktemp -d "$HOME/linux-backup-demo.XXXXXX")
   mkdir -p "$demo_root/source/reports" "$demo_root/source/empty dir" "$demo_root/restore"
   printf 'version one\n' > "$demo_root/source/reports/report.txt"
   printf 'hidden\n' > "$demo_root/source/.hidden"
   cp "$demo_root/source/reports/report.txt" "$demo_root/expected-v1.txt"
   sha256sum "$demo_root/expected-v1.txt"
   printf 'Use BACKUP_SOURCE=%s and RESTORE_ROOT=%s in the demo config.\n' "$demo_root/source" "$demo_root/restore"
   ```

2. Validate the config, run `status`, then `backup`. Record the returned
   `snapshot_id` as `V1`. Inspect verification/transfer/publication states.
3. Change `report.txt` to `version two`, add another file, and run a second backup.
   Record `V2`; `status` must show two completed snapshots.
4. Remove only the disposable `source/reports/report.txt`. Restore `V1 --path
   reports/report.txt` into a **new** directory under the demo restore root.
5. Compare independently saved expected data with the restored version:

   ```bash
   cmp "$demo_root/expected-v1.txt" /absolute/returned/destination/report.txt
   sha256sum "$demo_root/expected-v1.txt" /absolute/returned/destination/report.txt
   ```

6. Restore `V1 --path reports` into another new directory; show that its contents
   match v1. Run `verify V1` and `verify V2`. The snapshots remain independent.
7. Show `history --operation backup`, `history --operation restore`, local history,
   and `cleanup --dry-run`. Explain newest-snapshot protection and UTC age.
8. Demonstrate expired-retention boundaries through the isolated automated test,
   not by editing a real backup's metadata or the machine clock:

   ```bash
   python3 -m unittest tests.test_core.StoreTests.test_retention_boundary_latest_and_dry_run_apply -v
   ```

9. If the timer has been configured, show its next run and the journal entry for
   an actual scheduled job on B. For a manual run, record the two snapshot IDs
   and the restored checksum. Label a run over `127.0.0.1` as local integration.

To reset, create a fresh temporary demo root and config. Review the previous root
manually before removing it; the demo does not issue recursive deletion commands.
