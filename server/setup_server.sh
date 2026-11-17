#!/usr/bin/env bash
# setup_server.sh - Prepare Computer A (Ubuntu) as the backup server.
#
# Usage:
#   sudo ./setup_server.sh                       # install, create user + storage
#   sudo ./setup_server.sh --client-key FILE --client-name NAME
#                                                # also authorize a client's public key
#   sudo ./setup_server.sh --disable-password-auth
#                                                # only after key login is confirmed working
#
# Safe to re-run: every step checks the current state first.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_SRC="$SCRIPT_DIR/server.conf"
CONF_DST="/etc/linux-backup/server.conf"

CLIENT_KEY_FILE=""
CLIENT_NAME=""
DISABLE_PASSWORD_AUTH=false

log()  { printf '[setup] %s\n' "$*"; }
die()  { printf '[setup] ERROR: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --client-key)            CLIENT_KEY_FILE="${2:-}"; shift 2 ;;
        --client-name)           CLIENT_NAME="${2:-}";     shift 2 ;;
        --disable-password-auth) DISABLE_PASSWORD_AUTH=true; shift ;;
        -h|--help)               sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ $EUID -eq 0 ]] || die "Run as root (use sudo)."
[[ -f "$CONF_SRC" ]] || die "Missing $CONF_SRC"

# --- 1. Config ---------------------------------------------------------------
install -d -m 755 /etc/linux-backup
if [[ ! -f "$CONF_DST" ]]; then
    install -m 644 "$CONF_SRC" "$CONF_DST"
    log "Installed config to $CONF_DST"
else
    log "Config already exists at $CONF_DST (left unchanged)"
fi
# shellcheck disable=SC1090
source "$CONF_DST"

# --- 2. Packages -------------------------------------------------------------
log "Installing packages (openssh-server, rsync, sqlite3, python3)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openssh-server rsync sqlite3 python3 >/dev/null
systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd

# --- 3. Dedicated backup account ---------------------------------------------
if id "$BACKUP_USER" &>/dev/null; then
    log "User '$BACKUP_USER' already exists"
else
    adduser --disabled-password --gecos "Backup service account" "$BACKUP_USER" >/dev/null
    log "Created user '$BACKUP_USER' (no password, key login only)"
fi

# --- 4. Storage and log directories ------------------------------------------
install -d -m 750 -o "$BACKUP_USER" -g "$BACKUP_USER" "$STORAGE_ROOT"
install -d -m 750 -o "$BACKUP_USER" -g "$BACKUP_USER" "$LOG_DIR"
log "Storage: $STORAGE_ROOT   Logs: $LOG_DIR"

# --- 5. Authorize a client key (optional) ------------------------------------
if [[ -n "$CLIENT_KEY_FILE" ]]; then
    [[ -f "$CLIENT_KEY_FILE" ]] || die "Key file not found: $CLIENT_KEY_FILE"
    [[ "$CLIENT_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || die "--client-name must match [A-Za-z0-9_-]+"

    ssh-keygen -l -f "$CLIENT_KEY_FILE" >/dev/null 2>&1 \
        || die "$CLIENT_KEY_FILE is not a valid public key"

    SSH_DIR="/home/$BACKUP_USER/.ssh"
    AUTH="$SSH_DIR/authorized_keys"
    install -d -m 700 -o "$BACKUP_USER" -g "$BACKUP_USER" "$SSH_DIR"
    touch "$AUTH"; chmod 600 "$AUTH"; chown "$BACKUP_USER:$BACKUP_USER" "$AUTH"

    # Disable forwarding features the backup job never needs.
    OPTIONS="no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty"
    KEY_BODY="$(awk '{print $1" "$2}' "$CLIENT_KEY_FILE")"
    if grep -qF "$KEY_BODY" "$AUTH"; then
        log "Key for '$CLIENT_NAME' already authorized"
    else
        echo "$OPTIONS $KEY_BODY backup-client-$CLIENT_NAME" >> "$AUTH"
        log "Authorized key for client '$CLIENT_NAME'"
    fi

    install -d -m 750 -o "$BACKUP_USER" -g "$BACKUP_USER" "$STORAGE_ROOT/$CLIENT_NAME"
    log "Client storage: $STORAGE_ROOT/$CLIENT_NAME"
fi

# --- 6. SSH hardening --------------------------------------------------------
HARDEN="/etc/ssh/sshd_config.d/50-linux-backup.conf"
{
    echo "# Managed by linux-backup setup_server.sh"
    echo "PermitRootLogin no"
    if $DISABLE_PASSWORD_AUTH; then
        echo "PasswordAuthentication no"
    fi
} > "$HARDEN"

if sshd -t; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd
    log "SSH hardened (root login off$($DISABLE_PASSWORD_AUTH && echo ', password auth off'))"
else
    rm -f "$HARDEN"
    die "sshd config test failed; hardening reverted"
fi

# --- Summary -----------------------------------------------------------------
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
log "Done. Server address: ${IP:-unknown}"
log "From the client, test with:  ssh $BACKUP_USER@${IP:-<server-ip>} 'echo ok'"
