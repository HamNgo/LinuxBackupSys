# Two-machine Ubuntu setup

[Đọc hướng dẫn bằng tiếng Việt](setup.vi.md)

These are deployment instructions, not actions already executed. Use Ubuntu
24.04 LTS on machine A (server) and machine B (client). Replace example usernames,
hostname and paths with the lab's values. No IP or secret is embedded in the code.
This repository task does not install packages, configure real SSH or enable jobs.

## 1. Install tools and project code

On A, as an administrator:

```bash
sudo apt update
sudo apt install python3 rsync openssh-server
sudo systemctl enable --now ssh
sudo adduser --disabled-password --gecos '' backup
sudo install -d -o backup -g backup -m 0700 /srv/linux-backup
sudo install -d -m 0755 /etc/linux-backup
sudo bash deploy/install-code.sh /opt/linux-backup
```

Create the account only if it does not exist. Keep password/root SSH policy as
configured by your administrator; normal backup jobs never require root SSH.
Code installation only accepts a **new** destination and copies runtime code,
templates and units. It creates no users and enables no service. For updates,
install to a new versioned directory, review it, then update config/unit paths.

On B, use the existing non-root account that can read the selected source. The
examples call this account `backup-client`; substitute the real account name:

```bash
sudo apt update
sudo apt install python3 rsync openssh-client
sudo install -d -m 0755 /etc/linux-backup
sudo bash deploy/install-code.sh /opt/linux-backup
```

As the client job account:

```bash
install -d -m 0700 "$HOME/.ssh" "$HOME/.local/state/linux-backup" "$HOME/Restored"
# Run only if this dedicated key does not already exist. Never overwrite a key.
ssh-keygen -t ed25519 -f "$HOME/.ssh/linux-backup" -C linux-backup-client
```

## 2. Establish SSH identity and trust

Transfer **only** the client's `.pub` file to the administrator on A. Install it
in the backup account's `~/.ssh/authorized_keys`, preserving any existing keys.
Use mode 0700 for `.ssh`, 0600 for `authorized_keys`, and account ownership. The
`restrict` authorized-key option can disable forwarding, PTYs and user rc files
while still permitting the required command execution. Do not install a forced
command unless it explicitly supports this control and rsync protocol.

On A, read the SSH host fingerprint through a trusted console:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

On B, as the job account, make the first connection interactively and compare
the presented fingerprint with A's trusted output before accepting it:

```bash
ssh -i "$HOME/.ssh/linux-backup" backup@YOUR_SERVER_HOST true
```

`ssh-keyscan` alone does not authenticate a host. Do not disable host-key checking.
Then test the unattended settings and remote dependencies:

```bash
ssh -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes \
  -i "$HOME/.ssh/linux-backup" backup@YOUR_SERVER_HOST 'python3 --version; rsync --version'
```

## 3. Configure and initialize A

```bash
sudo cp /opt/linux-backup/server/server.conf.example /etc/linux-backup/server.conf
sudo chown root:backup /etc/linux-backup/server.conf
sudo chmod 0640 /etc/linux-backup/server.conf
sudoedit /etc/linux-backup/server.conf
sudo -u backup python3 /opt/linux-backup/server/agent.py --config /etc/linux-backup/server.conf init
```

Set `CLIENT_ID`, `STORAGE_ROOT`, retention and timeout. Storage and all managed
control directories must remain private, owned by `backup`; never apply recursive
chmod/chown to completed snapshots. Keep source data and server storage separate.

## 4. Configure and test B

```bash
sudo cp /opt/linux-backup/client/client.conf.example /etc/linux-backup/backup.conf
sudo chown root:backup-client /etc/linux-backup/backup.conf
sudo chmod 0640 /etc/linux-backup/backup.conf
sudoedit /etc/linux-backup/backup.conf
```

Set absolute source, identity, known-hosts, local log and restore-root paths; set
the actual server hostname, account, installed program/config paths and matching
client ID. Check [configuration.md](configuration.md) for the exact contract.
Run as the job account, first against disposable source data:

```bash
bash /opt/linux-backup/backup-manager.sh --config /etc/linux-backup/backup.conf configure --check
bash /opt/linux-backup/backup-manager.sh --config /etc/linux-backup/backup.conf status
bash /opt/linux-backup/backup-manager.sh --config /etc/linux-backup/backup.conf backup
bash /opt/linux-backup/backup-manager.sh --config /etc/linux-backup/backup.conf history
```

Verify and restore the returned snapshot ID before trusting the installation.
Check that storage is on a local Linux filesystem, both hosts have correct UTC
time, and free space is sufficient for full copies.

### Desktop client

On machine B, sign in to the graphical desktop as the account that owns the backup SSH key. Install Tk support once using the package for your distribution.

| Client system | Command |
| --- | --- |
| Ubuntu | `sudo apt install python3-tk` |
| Arch Linux | `sudo pacman -S --needed tk` |

From the checkout or the installed project directory, run the following as your ordinary desktop user.

```bash
python3 deploy/install-desktop.py
```

Open the applications menu and search for **LinuxBackupSys**. Choose your client TOML file, for example `/etc/linux-backup/backup.conf`. To make the menu open a specific config every time, run the installer with `--config /absolute/path/backup.conf`. The entry points to this copy of the project. If you move the checkout, rerun the installer from its new location. To open the window directly from the project's root directory, run `bash backup-manager.sh --config /absolute/path/backup.conf gui`.

The window uses Vietnamese labels. You can open an existing client configuration or fill in the configuration form and save a new copy. Use the same SSH identity, verified known-hosts file and initialized server storage as above. Refresh the snapshot list, start a backup, then select a completed snapshot to verify or restore. The result identifies the new restore destination. History includes local and server events. The retention view previews the cleanup policy. Use the systemd setup below to manage the schedule.

In the restore dialog, choose **Duyệt phiên…** to browse the selected snapshot, including files that have since disappeared from the source. Select a file or directory, or leave the selection empty to restore the whole snapshot. Browsing requires a server version that supports `list-files`. With an older agent you can still type the relative path.

## 5. Enable the chosen scheduler on B

The project implements **systemd timer only**. Review `User`, `Group`, program and
config paths in the service. The example runs daily at 02:00 UTC (09:00 Vietnam),
with up to five minutes of random delay; `Persistent=true` catches a missed run
after reboot. The service runs retention **only after a successful backup**. Review
the dry-run output and server retention value before enabling automatic deletion.

```bash
sudo cp /opt/linux-backup/deploy/linux-backup.service /etc/systemd/system/
sudo cp /opt/linux-backup/deploy/linux-backup.timer /etc/systemd/system/
sudoedit /etc/systemd/system/linux-backup.service
sudo systemd-analyze verify /etc/systemd/system/linux-backup.service /etc/systemd/system/linux-backup.timer
sudo systemctl daemon-reload
# Test the exact service environment before enabling recurrence.
sudo systemctl start linux-backup.service
sudo systemctl status linux-backup.service
sudo journalctl -u linux-backup.service --no-pager -n 50
sudo systemctl enable --now linux-backup.timer
systemctl list-timers linux-backup.timer
```

Disable recurrence with `sudo systemctl disable --now linux-backup.timer`. A timer
disable does not interrupt an already running backup; inspect its service first.
Do not also configure Cron for the same job. Record actual scheduled executions
on the two target machines; syntax validation alone is not scheduler evidence.

The service uses `PrivateTmp=true`; keep scheduled sources, restore roots, keys
and configuration outside `/tmp` and `/var/tmp` so the private namespace does not
hide them from the job.

## Operational recovery

- Nonzero backup: inspect local/server history and `status`. An unfinished staging
  ID is not a completed snapshot. A published ID may still exist after a log or
  connection failure; `verify ID` before retrying.
- Nonzero restore: inspect the reported `.restore-*` and destination paths. The
  source was not overwritten. Choose a new destination for a retry.
- Busy lock (3): wait for the active operation, then retry; never delete lock files
  to bypass a running process.
- Retention failure: keep unexpected entries for investigation. Do not run broad
  recursive delete commands on the storage root.
- Log growth: JSONL rotation and automatic orphan-staging cleanup are not included.
  Archive logs only during a maintenance window with jobs stopped.
