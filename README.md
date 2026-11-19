# Centralized Linux Backup and Disaster Recovery Service

[Tiếng Việt](README.vi.md)

A lightweight, centralized backup and disaster recovery service for Ubuntu, built with Bash, Python, and standard Linux tools.

> **Status:** The MVP is implemented: rsync/SSH backup, versioned snapshots, SHA-256 verification, file/directory restore, retention dry-run/apply, JSONL history, configuration and systemd units. Local Linux tests use real rsync and server processes; two-machine Ubuntu 24.04 deployment and actual scheduled runs still need validation. The two-week roadmap below is the original delivery plan, not a completed-test claim.

Start with [two-machine setup](docs/setup.md), [configuration and CLI](docs/configuration.md), [architecture](docs/architecture.md), [test evidence](docs/testing.md), and the [demo procedure](docs/demo.md).

[Hướng dẫn triển khai bằng tiếng Việt](docs/setup.vi.md)

```bash
# On Linux, from the checkout:
bash backup-manager.sh --help
bash tests/run.sh
# Generate a NEW configuration template, then edit its placeholders:
bash backup-manager.sh configure --output /absolute/new-backup.conf
```

The runtime requires Python 3.11+, Bash, rsync and OpenSSH. The implementation uses full independent snapshots; hard-link deduplication and SQLite remain optional and are not implemented. Only regular files and directories are supported; symlinks and special files are rejected explicitly. Restore always uses a new directory and never overwrites an existing destination.

## Table of Contents

1. [Overview](#1-overview)
2. [Objectives](#2-objectives)
3. [System Architecture](#3-system-architecture)
4. [Features](#4-features)
5. [Technology Stack](#5-technology-stack)
6. [Project Structure](#6-project-structure)
7. [Management Commands](#7-management-commands)
8. [Team Responsibilities](#8-team-responsibilities)
9. [Two-Week Roadmap](#9-two-week-roadmap)
10. [Key Milestones](#10-key-milestones)
11. [Demonstration Plan](#11-demonstration-plan)
12. [Security and Reliability](#12-security-and-reliability)
13. [Scope Control and Future Work](#13-scope-control-and-future-work)
14. [Setup Checklist](#14-setup-checklist)

---

## 1. Overview

A client computer sends selected files and directories to a separate backup server over the local network. The system creates versioned backups, runs scheduled jobs, verifies file integrity, applies retention rules, and lets users restore files or directories from earlier versions.

The project demonstrates practical Linux server administration, automation, remote communication, backup management, and disaster recovery.

## 2. Objectives

- Build a centralized backup server that receives backups from Linux clients.
- Transfer files securely between two Ubuntu computers.
- Create versioned backups so earlier copies of files can be recovered.
- Automate backup jobs with Cron or systemd timers.
- Restore individual files or complete directories.
- Verify backup integrity with SHA-256 checksums.
- Apply configurable retention policies to remove expired backups.
- Record backup operations and history.
- Provide shell scripts to configure and manage the service.

## 3. System Architecture

Two Ubuntu computers are connected over the same local network.

```text
┌───────────────────────────────┐            ┌───────────────────────────────┐
│ Computer B: Backup Client     │            │ Computer A: Backup Server     │
│                               │            │                               │
│ • Selected files/directories  │   SSH      │ • OpenSSH server              │
│ • Client backup scripts       │ ───────►   │ • Central backup storage      │
│ • Restore requests            │   rsync    │ • Versioned snapshots         │
│ • Checksum verification       │ ◄───────►  │ • Retention management        │
│                               │            │ • Logs and backup history     │
└───────────────────────────────┘            └───────────────────────────────┘
```

### Computer A: Backup Server

- Runs the OpenSSH server.
- Receives backup data from clients.
- Stores snapshots in a dedicated storage directory.
- Manages backup versions and retention.
- Keeps logs and backup history.
- Provides the files required for recovery.

### Computer B: Backup Client

- Defines which files and directories are backed up.
- Connects to the server over SSH.
- Transfers files with rsync.
- Requests restoration of selected files or directories.
- Verifies recovered files using checksums.

### Communication

The initial implementation uses SSH and rsync over the local network. SSH provides authenticated communication, and rsync transfers files efficiently.

## 4. Features

### 4.1 Secure Remote Communication

- SSH key authentication between client and server.
- A dedicated backup account instead of unrestricted root SSH access.

### 4.2 Centralized Backup Storage

- Client backups are stored on the server.
- Backups are organized by client and date.
- Backup data is kept separate from normal server files.

### 4.3 Versioned and Incremental Backups

- Each backup run creates a new snapshot.
- Previous versions are preserved for recovery.
- _(Optional, not implemented)_ rsync `--link-dest` with hard links can avoid duplicating unchanged files when snapshots share a filesystem. The current MVP stores full independent copies.

### 4.4 Automated Scheduling

- Recurring backups via the supplied systemd service/timer (installation and enablement are explicit deployment steps).
- Configurable backup frequency.
- The result of each run is recorded.

### 4.5 Restore and Disaster Recovery

- Restore a file or directory from a chosen snapshot.
- Recover earlier versions of data.
- Restore to a separate destination by default to avoid overwriting originals during testing.

### 4.6 Integrity Verification

- Generate and compare SHA-256 checksums.
- Detect missing or modified files.
- Report whether a backup or restored copy passes verification.

### 4.7 Retention Management

- Configurable snapshot retention period.
- Automatic removal of expired snapshots.
- Protection of recent backups from accidental cleanup.

### 4.8 Logs and Backup History

- Record backup start and completion times.
- Record success and failure details.
- Maintain a searchable history of operations.
- _(Optional)_ Use SQLite for structured metadata if time permits.

### 4.9 Configuration and Management Scripts

Scripts let users configure and operate the service without hand-editing many files.

Example configuration file: `/etc/linux-backup/backup.conf`

```toml
CLIENT_ID = "client-b"
BACKUP_SOURCE = "/home/backup-client/Documents"
SSH_HOST = "backup-server.example"
SSH_USER = "backup"
SSH_IDENTITY = "/home/backup-client/.ssh/linux-backup"
SSH_KNOWN_HOSTS = "/home/backup-client/.ssh/known_hosts"
SERVER_PROGRAM = "/opt/linux-backup/server/agent.py"
SERVER_CONFIG = "/etc/linux-backup/server.conf"
LOG_FILE = "/home/backup-client/.local/state/linux-backup/history.jsonl"
RESTORE_ROOT = "/home/backup-client/Restored"
COMPRESSION = false
VERIFY_CHECKSUM = true
```

This is TOML data, never a sourced shell script. Adjust paths, account names and values for the two computers. Server storage and retention are in [server.conf.example](server/server.conf.example); scheduling is in [linux-backup.timer](deploy/linux-backup.timer). See the [complete client template](client/client.conf.example).

## 5. Technology Stack

| Technology            | Purpose                                             |
| --------------------- | --------------------------------------------------- |
| Ubuntu 24.04 LTS      | Operating system on both computers                  |
| OpenSSH Server        | Secure remote access                                |
| SSH                   | Client-server authentication and communication      |
| rsync                 | Efficient file transfer and snapshot creation       |
| Bash                  | Backup, restore, cleanup, and configuration scripts |
| Python 3.11+          | Standard-library management, manifest and path validation |
| JSON / JSONL          | Snapshot metadata and operation history             |
| systemd timer         | Automatic scheduling (supplied, not auto-enabled)    |
| SHA-256 / hashlib     | File integrity verification; sha256sum for manual demo |
| Git                   | Source code version control                         |

The project stays lightweight. Docker, Kubernetes, and a web dashboard are not required for the core implementation.

## 6. Project Structure

Implemented layout (runtime backups and history stay outside Git):

```text
LinuxBackupSys/
├── backup-manager.sh          # unified Bash entrypoint
├── client/                    # SSH/rsync workflows and client config template
├── server/                    # SSH agent, storage, retention and server template
├── common/                    # CLI, safe config/path handling, manifest, protocol
├── deploy/                    # explicit code installer and systemd units
├── tests/                     # unittest fixtures, real rsync, optional real SSH
├── docs/                      # architecture, config, setup, tests and demo
├── .github/workflows/test.yml # Ubuntu 24.04 CI definition
└── README.md
```

## 7. Management Commands

A unified management script provides a simple command-line interface.

```bash
bash backup-manager.sh --config /etc/linux-backup/backup.conf status
bash backup-manager.sh --config /etc/linux-backup/backup.conf backup
bash backup-manager.sh --config /etc/linux-backup/backup.conf restore SNAPSHOT_ID --path 'reports/report.txt'
bash backup-manager.sh --config /etc/linux-backup/backup.conf configure --check
```

Additional operations:

```bash
bash backup-manager.sh --config /etc/linux-backup/backup.conf history --limit 20
bash backup-manager.sh --config /etc/linux-backup/backup.conf verify SNAPSHOT_ID
bash backup-manager.sh --config /etc/linux-backup/backup.conf cleanup --dry-run
# Only after reviewing candidates:
bash backup-manager.sh --config /etc/linux-backup/backup.conf cleanup --apply
```

Commands print JSON and return nonzero on failures. Restore requires a completed snapshot ID; its destination must be new. Cleanup retains the newest successful snapshot and only expires others older than the configured number of 24-hour periods. See [configuration.md](docs/configuration.md) for paths, exit codes and exact semantics.

## 8. Team Responsibilities

Both members should understand the overall architecture and take part in integration, testing, documentation, and the final demonstration.

### Member 1: Server and Infrastructure

- Prepare the Ubuntu backup server.
- Configure OpenSSH and the dedicated backup account.
- Set up backup storage and permissions.
- Implement server-side snapshot management.
- Implement retention and cleanup.
- Maintain server configuration and backup logs.
- Help integrate the client with the server.

### Member 2: Client and Recovery

- Prepare the Ubuntu client.
- Configure SSH key authentication to the server.
- Implement client-side backup and transfer scripts.
- Implement restore operations.
- Implement SHA-256 integrity verification.
- Implement backup history queries and client configuration.
- Help integrate and test the complete system.

### Shared

- Agree on script interfaces and configuration formats.
- Test the system on both computers.
- Test failure and recovery scenarios.
- Write the English report and prepare presentation slides.
- Rehearse the demonstration together.

## 9. Two-Week Roadmap

The target is a working end-to-end backup and restore system by **Day 10**. The remaining days are reserved for reliability testing, documentation, and demonstration preparation.

### Week 1: Build the Core Backup System

#### Day 1: Project Setup and Architecture

- Confirm the roles of the two Ubuntu computers.
- Agree on the backup directory structure and naming convention.
- Check required tools: SSH, rsync, Python, and SQLite.
- Create a shared Git repository and initial project folders.
- Document the system architecture.

**Deliverable:** Project repository and agreed architecture.

#### Day 2: SSH Client-Server Setup

- Install and enable OpenSSH Server on Computer A.
- Create a dedicated backup account and storage directory on the server.
- Configure SSH key authentication from Computer B.
- Test SSH connectivity.

**Deliverable:** The client can securely connect to the backup server.

#### Day 3: Basic Backup Transfer

- Select a small test directory on the client.
- Transfer it to the server with rsync over SSH.
- Create a basic backup script.
- Check that transferred files match the originals.
- Handle basic transfer errors.

**Deliverable:** A working manual backup from client to server.

#### Day 4: Versioned Backups

- Create a separate snapshot directory for each backup run.
- Add date/time-based snapshot naming.
- Investigate rsync `--link-dest` to reuse unchanged files through hard links.
- Modify files and create another snapshot to test.

**Deliverable:** Multiple backup versions can be stored and distinguished.

#### Day 5: Configuration and Scheduling

- Create client and server configuration files.
- Implement a configuration script for key parameters.
- Add backup logging.
- Configure and test a recurring backup with Cron or a systemd timer.

**Deliverable:** Configurable, scheduled backups with logs.

#### Day 6: Retention and Integrity Verification

- Implement a configurable retention period and cleanup of expired snapshots.
- Generate and compare SHA-256 checksums.
- Test cleanup and verification with sample data.

**Deliverable:** Automatic retention management and integrity checking.

#### Day 7: Restore Implementation

- Restore a selected file or directory from a chosen snapshot.
- Restore to a separate test destination.
- Compare restored files with the expected originals.
- Test recovery from an older snapshot.

**Deliverable:** Basic recovery from a selected backup version.

### Week 2: Integrate, Test, and Prepare the Demonstration

#### Day 8: Backup History

- Decide which metadata to record.
- Add SQLite storage for backup history if feasible.
- Record snapshot identifiers, timestamps, results, and relevant paths.
- Implement a command to display backup history.

**Deliverable:** A usable record of previous backup operations.

#### Day 9: Unified Command-Line Interface

- Combine the scripts behind a single management command.
- Add status, backup, restore, configure, history, verify, and cleanup operations as implemented.
- Improve error messages and input validation.
- Check configuration handling and permissions.

**Deliverable:** A consistent command-line interface for managing the service.

#### Day 10: Full System Integration

- Connect the client and server scripts.
- Run the complete backup workflow.
- Modify and delete sample files, then restore from an earlier snapshot.
- Verify the restored data and fix integration problems.

**Milestone:** The complete core system works on both computers by the end of this day.

#### Day 11: Failure and Reliability Testing

Test scenarios:

- A file is modified after a backup.
- A file or directory is deleted from the client.
- The client temporarily loses network connectivity.
- SSH authentication fails.
- The configuration contains an invalid path.
- A checksum does not match.
- An expired snapshot is eligible for cleanup.
- A restore is attempted from a selected older snapshot.

Record expected results, actual results, and any limitations.

**Deliverable:** Test results and a list of resolved and known issues.

#### Day 12: Report and Presentation

Prepare the English report and slides.

Suggested report sections:

1. Introduction and project objectives
2. Background and related Linux tools
3. System requirements and architecture
4. Implementation and configuration
5. Backup and snapshot mechanism
6. Restore and disaster recovery mechanism
7. Integrity verification and retention policy
8. Testing and results
9. Limitations and future improvements
10. Conclusion

Suggested presentation split:

- **Member 1:** architecture, server setup, SSH, storage, and snapshot management.
- **Member 2:** client scripts, restore process, integrity verification, and testing.
- **Both:** live demonstration and questions.

**Deliverable:** Draft report and presentation slides.

#### Day 13: Demonstration Rehearsal

- Reboot both computers and verify the setup starts correctly.
- Prepare predictable sample files and directories.
- Rehearse the demonstration from the beginning.
- Check network connectivity, SSH access, and scheduled jobs.
- Capture screenshots for the report.
- Fix problems that could interrupt the live demonstration.

**Deliverable:** A repeatable demonstration procedure.

#### Day 14: Final Demonstration

- Present the architecture and the two-computer setup.
- Demonstrate backup, version creation, recovery, and integrity verification.
- Show backup history, logs, and retention configuration.
- Explain test results and limitations.
- Submit the report and slides.

**Deliverable:** Completed project presentation.

## 10. Key Milestones

| Deadline      | Expected result                                                   |
| ------------- | ----------------------------------------------------------------- |
| End of Day 3  | Client and server communicate; basic backup works                 |
| End of Day 7  | Versioned backup, retention, verification, and basic restore work |
| End of Day 10 | Integrated end-to-end system works                                |
| End of Day 11 | Reliability and failure tests completed                           |
| End of Day 13 | Report and live demonstration ready                               |
| Day 14        | Final presentation                                                |

## 11. Demonstration Plan

A focused 10–15 minute demonstration:

1. Show the client computer and the selected test directory.
2. Run the first backup and show the snapshot on the server.
3. Modify a file on the client.
4. Run a second backup and show that a new version is created.
5. Delete a test directory from the client.
6. Restore the deleted directory from an earlier snapshot.
7. Compare the restored files using SHA-256 checksums.
8. Show the backup history and logs.
9. Show the retention configuration and, if practical, clean up an expired test snapshot.

> Use disposable test data for destructive demonstrations. Do not experiment with deletion or restoration on important personal files.

## 12. Security and Reliability

- Use a dedicated backup account on the server.
- Prefer SSH key authentication and avoid unrestricted root SSH login.
- Restrict write access to the backup storage directory.
- Validate paths and user input in shell scripts.
- Never automatically overwrite original files during restore tests.
- Log backup and restore failures.
- Test recovery regularly; a backup is only useful if it can be restored.
- Keep client and server clocks synchronized so snapshot names and logs are consistent.

## 13. Scope Control and Future Work

Complete the core backup and restore workflow before attempting optional features. Possible future improvements:

- A lightweight web dashboard.
- Email or desktop notifications after backup failures.
- Multiple client computers.
- Backup encryption at rest.
- Remote backup beyond the local LAN.
- Advanced access controls and audit logging.

These are optional and must not delay the core demonstration.

## 14. Setup Checklist

### Infrastructure

- [ ] Identify Computer A as the backup server.
- [ ] Identify Computer B as the backup client.
- [ ] Confirm both computers run Ubuntu.
- [ ] Confirm both computers can reach each other over the network.
- [ ] Install and test SSH.
- [ ] Install and test rsync.
- [x] Create the Git repository and project folders.

### Backup Functionality

- [ ] Configure SSH key authentication.
- [ ] Create the server backup storage directory.
- [x] Implement basic backup transfer.
- [x] Implement versioned snapshots.
- [ ] Configure automatic scheduling.
- [x] Implement backup logs.
- [x] Implement backup history.

### Recovery and Reliability

- [x] Implement file restoration.
- [x] Implement directory restoration.
- [x] Implement SHA-256 verification.
- [x] Implement retention and cleanup.
- [x] Test recovery from an older snapshot (local Linux fixture).
- [ ] Test network and authentication failures.
- [x] Confirm restore tests refuse existing destinations and preserve fixture sources.

### Customization and Submission

- [x] Implement configuration templates and strict parser.
- [x] Implement configuration generation and validation.
- [x] Implement a unified command-line interface.
- [ ] Complete integration testing on both computers.
- [ ] Prepare screenshots and test results.
- [ ] Complete the English report.
- [ ] Complete the presentation slides.
- [ ] Rehearse the live demonstration.

---

_Update the architecture, commands, configuration examples, and feature list as the implementation develops, and clearly distinguish completed features from planned or optional ones in the final report._
