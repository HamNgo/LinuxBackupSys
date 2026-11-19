# Kiểm thử LinuxBackupSys giữa Ubuntu và Arch qua Tailscale

**Máy A** chạy Ubuntu 24.04 LTS, giữ kho sao lưu và chạy OpenSSH Server. **Máy B** chạy Arch Linux, giữ dữ liệu mẫu và chạy các lệnh backup, verify, restore. Hai máy có thể dùng hai mạng Internet khác nhau. Tailscale tạo đường kết nối riêng để máy Arch truy cập OpenSSH trên Ubuntu qua TCP 22 mà không cần chuyển tiếp cổng trên router.

Chuẩn bị quyền `sudo` trên hai máy, tài khoản có thể tham gia cùng mạng Tailscale (*tailnet*) và cùng một phiên bản mã nguồn LinuxBackupSys. Các lệnh dưới đây dùng Bash. Dùng kho và cấu hình dành riêng cho bài thử để phân biệt snapshot mẫu với dữ liệu vận hành.

## 1. Cài Tailscale và công cụ trên hai máy

### Máy A — Ubuntu 24.04

Cài OpenSSH, Python, rsync và `curl`. Sau đó thêm kho gói Tailscale dành cho Ubuntu 24.04 (`noble`). Nếu Tailscale đã được cài và kết nối, dùng cấu hình tailnet hiện có và chuyển sang phần kiểm tra. [Kho gói chính thức của Tailscale](https://pkgs.tailscale.com/stable/#ubuntu-noble)

```bash
sudo apt update
sudo apt install ca-certificates curl openssh-server python3 rsync
sudo install -d -m 0755 /usr/share/keyrings
(
  set -o pipefail
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg |
    sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
) && (
  set -o pipefail
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list |
    sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
) && sudo apt update && sudo apt install tailscale
```

```bash
sudo systemctl enable --now tailscaled.service
sudo systemctl enable --now ssh.service
sudo tailscale up
tailscale ip -4
```

Mở URL đăng nhập do `tailscale up` in ra, chọn tailnet dùng cho bài thử. Sau khi kết nối, ghi lại địa chỉ IPv4 từ `tailscale ip -4`. Máy B sẽ dùng địa chỉ này làm `SSH_HOST`.

### Máy B — Arch Linux

Lệnh `pacman -Syu` cập nhật hệ thống Arch cùng lúc cài các gói. Đọc danh sách thay đổi mà `pacman` hiển thị trước khi xác nhận. Gói `openssh` cung cấp lệnh `ssh` dùng ở phía máy khách. [Gói Tailscale của Arch](https://archlinux.org/packages/extra/x86_64/tailscale/files/)

```bash
sudo pacman -Syu --needed tailscale openssh python rsync
sudo systemctl enable --now tailscaled.service
sudo tailscale up
tailscale status
```

Đăng nhập để máy B vào cùng tailnet với máy A. Dùng OpenSSH của Ubuntu và xác thực qua `authorized_keys` cho bài thử. Tính năng riêng **Tailscale SSH** có thể tiếp quản cổng 22 trên địa chỉ Tailscale, vì vậy hãy để tính năng đó tắt trên máy A dùng trong bài thử. [OpenSSH qua Tailscale](https://tailscale.com/docs/reference/ssh-over-tailscale)

### Kiểm tra đường kết nối từ Arch

Nhập IPv4 Tailscale của **Ubuntu**. Giữ phiên Bash này khi thực hiện các bước tiếp theo trên Arch.

```bash
read -r -p 'IPv4 Tailscale của Ubuntu: ' ubuntu_ts_ip
tailscale status
tailscale ping "$ubuntu_ts_ip"
```

Kết quả `pong` trực tiếp hoặc qua relay đều cho thấy hai thiết bị liên lạc được qua Tailscale. SSH ở bước 3 sẽ kiểm tra riêng cổng TCP 22. Nếu tailnet dùng chính sách giới hạn truy cập, chính sách phải cho phép máy B kết nối máy A qua cổng đó. [Kết nối giữa các thiết bị Tailscale](https://tailscale.com/docs/how-to/connect-to-devices)

## 2. Chuẩn bị kho thử trên Ubuntu và thư mục thử trên Arch

### Máy A — Ubuntu

Từ thư mục gốc mã nguồn, cài dự án vào `/opt/linux-backup` nếu đây là lần cài đầu. Nếu đã có phiên bản đúng ở đó, dùng bản đã cài. Script cài chỉ nhận một thư mục đích mới.

```bash
sudo bash deploy/install-code.sh /opt/linux-backup
```

Tạo tài khoản `backup` nếu chưa có và chuẩn bị một kho riêng. Ví dụ dùng nhóm `backup` đi cùng tài khoản tạo bằng `adduser`. Nếu dùng tài khoản đã có với nhóm chính khác, thay `backup` ở các vị trí chỉ nhóm bằng kết quả `id -gn backup`.

```bash
if ! id backup >/dev/null 2>&1; then
  sudo adduser --disabled-password --gecos '' backup
fi
sudo install -d -m 0755 /etc/linux-backup
sudo install -d -o backup -g backup -m 0700 /srv/linux-backup-tailnet-test
sudoedit /etc/linux-backup/server-tailnet-test.conf
```

Dùng nội dung TOML sau cho file cấu hình thử trên Ubuntu.

```toml
CLIENT_ID = "arch-tailnet-test"
STORAGE_ROOT = "/srv/linux-backup-tailnet-test"
RETENTION_DAYS = 7
TIMEOUT_SECONDS = 3600
```

Đặt quyền đọc cấu hình cho tài khoản backup rồi khởi tạo kho dưới chính tài khoản đó.

```bash
sudo chown root:backup /etc/linux-backup/server-tailnet-test.conf
sudo chmod 0640 /etc/linux-backup/server-tailnet-test.conf
sudo -u backup python3 /opt/linux-backup/server/agent.py \
  --config /etc/linux-backup/server-tailnet-test.conf init
```

### Máy B — Arch Linux

Từ thư mục gốc mã nguồn, cài cùng phiên bản mã như trên Ubuntu nếu chưa có. Sau đó tiếp tục trong Bash bằng tài khoản thường sẽ chạy bài thử.

```bash
sudo bash deploy/install-code.sh /opt/linux-backup
```

Tạo thư mục thử dưới home của tài khoản, với nguồn, bản đối chiếu, nhật ký và dữ liệu khôi phục ở các vị trí riêng.

```bash
demo_root=$(mktemp -d "$(cd -- "$HOME" && pwd -P)/linux-backup-tailnet.XXXXXX")
mkdir -p "$demo_root/source/reports" "$demo_root/expected" "$demo_root/restore"
printf 'Phien ban 1\n' > "$demo_root/source/reports/bao-cao.txt"
cp "$demo_root/source/reports/bao-cao.txt" "$demo_root/expected/bao-cao-v1.txt"
printf 'Thu muc bai thu: %s\n' "$demo_root"
```

## 3. Thiết lập và kiểm tra OpenSSH

Trên **Arch**, tạo cặp khóa dành riêng cho bài thử nếu tên khóa còn trống. Nếu dùng passphrase, nạp khóa vào SSH agent của phiên Bash này trước khi chạy thử kết nối không tương tác.

```bash
install -d -m 0700 "$HOME/.ssh"
demo_key="$HOME/.ssh/linux-backup-tailnet"
demo_hosts="$HOME/.ssh/known_hosts_linux_backup_tailnet"
if [[ ! -e "$demo_key" && ! -e "$demo_key.pub" ]]; then
  ssh-keygen -t ed25519 -f "$demo_key" -C linux-backup-tailnet-test
fi
```

Chuyển **chỉ file công khai** `linux-backup-tailnet.pub` tới người quản trị Ubuntu để thêm vào `authorized_keys` của tài khoản `backup`. Giữ khóa riêng ở Arch.

Trên **Ubuntu**, tạo file nếu cần, rồi thêm nội dung public key thành một dòng riêng ở cuối file. Ví dụ giả định home của `backup` là `/home/backup`. Kiểm tra bằng `getent passwd backup` nếu tài khoản đã có từ trước.

```bash
sudo -u backup -H bash -c 'umask 077; mkdir -p "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"; chmod 0700 "$HOME/.ssh"; chmod 0600 "$HOME/.ssh/authorized_keys"'
sudoedit /home/backup/.ssh/authorized_keys
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Ghi lại fingerprint từ console Ubuntu hoặc kênh quản trị đáng tin cậy. Trên **Arch**, so sánh fingerprint SSH hiển thị với giá trị đó trước khi chấp nhận. Khóa máy chủ đã xác minh sẽ được lưu vào file `known_hosts` riêng của bài thử.

```bash
ssh -F /dev/null -p 22 -o HostKeyAlgorithms=ssh-ed25519 \
  -o StrictHostKeyChecking=ask -o "UserKnownHostsFile=\"$demo_hosts\"" \
  -o IdentitiesOnly=yes -o PreferredAuthentications=publickey \
  -i "$demo_key" "backup@$ubuntu_ts_ip" true
```

Tiếp tục từ **Arch** với phép thử không tương tác. Lệnh phải in phiên bản Python và rsync trên Ubuntu rồi thoát với mã `0` mà không hỏi mật khẩu hoặc xác nhận fingerprint.

```bash
ssh -F /dev/null -p 22 -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=\"$demo_hosts\"" -o IdentitiesOnly=yes \
  -i "$demo_key" "backup@$ubuntu_ts_ip" 'python3 --version && rsync --version'
```

## 4. Tạo cấu hình thử trên Arch

Từ cùng phiên Bash, xem các giá trị thật rồi tạo cấu hình ở `backup.conf` trong thư mục bài thử.

```bash
printf 'SSH_HOST=%s\nBACKUP_SOURCE=%s/source\nSSH_IDENTITY=%s\nSSH_KNOWN_HOSTS=%s\nLOG_FILE=%s/history.jsonl\nRESTORE_ROOT=%s/restore\n' \
  "$ubuntu_ts_ip" "$demo_root" "$demo_key" "$demo_hosts" "$demo_root" "$demo_root"
bash /opt/linux-backup/backup-manager.sh configure --output "$demo_root/backup.conf"
```

Mở file vừa tạo bằng trình soạn thảo, ví dụ `nano "$demo_root/backup.conf"` nếu đã cài `nano`. Điền các giá trị thật vừa in. Mẫu dưới đây dùng địa chỉ và tên thư mục minh họa. TOML cần đường dẫn tuyệt đối thay cho `$HOME`, `$demo_root` hoặc `~`.

```toml
CLIENT_ID = "arch-tailnet-test"
BACKUP_SOURCE = "/home/ban/linux-backup-tailnet.ABCDEF/source"
SSH_HOST = "100.101.102.103"
SSH_USER = "backup"
SSH_PORT = 22
SSH_IDENTITY = "/home/ban/.ssh/linux-backup-tailnet"
SSH_KNOWN_HOSTS = "/home/ban/.ssh/known_hosts_linux_backup_tailnet"
SERVER_PROGRAM = "/opt/linux-backup/server/agent.py"
SERVER_CONFIG = "/etc/linux-backup/server-tailnet-test.conf"
LOG_FILE = "/home/ban/linux-backup-tailnet.ABCDEF/history.jsonl"
RESTORE_ROOT = "/home/ban/linux-backup-tailnet.ABCDEF/restore"
VERIFY_CHECKSUM = true
COMPRESSION = false
TIMEOUT_SECONDS = 3600
```

`SERVER_PROGRAM` và `SERVER_CONFIG` trỏ tới file trên **Ubuntu**. `SSH_IDENTITY`, `SSH_KNOWN_HOSTS`, `BACKUP_SOURCE`, `LOG_FILE` và `RESTORE_ROOT` trỏ tới file hoặc thư mục trên **Arch**. `CLIENT_ID` phải giống nhau trên hai máy. [Tham số cấu hình](configuration.md)

```bash
backup_cli=(bash /opt/linux-backup/backup-manager.sh --config "$demo_root/backup.conf")
"${backup_cli[@]}" configure --check
"${backup_cli[@]}" status
```

`configure --check` kiểm tra file cấu hình, còn `status` xác nhận CLI truy cập được kho Ubuntu qua SSH. Với kho mới, kết quả có `client_id` là `arch-tailnet-test` và danh sách `snapshots` rỗng.

## 5. Kiểm thử backup, verify và restore qua hai mạng

Chạy các lệnh sau trên **Arch**. Tiếp tục từng bước sau khi lệnh trước thành công. Trường `snapshot_id` trong mỗi kết quả `backup` là ID cần nhập khi được hỏi.

### Tạo hai phiên có nội dung khác nhau

```bash
"${backup_cli[@]}" backup
read -r -p 'Nhập snapshot_id của phiên 1: ' snapshot_v1
"${backup_cli[@]}" verify "$snapshot_v1"
```

Phiên 1 cần có `transfer: complete`, `verification: verified` và `publication: complete` trong JSON. Lệnh `verify` cần trả `"verified": true`.

```bash
printf 'Phien ban 2\n' > "$demo_root/source/reports/bao-cao.txt"
"${backup_cli[@]}" backup
read -r -p 'Nhập snapshot_id của phiên 2: ' snapshot_v2
"${backup_cli[@]}" verify "$snapshot_v2"
"${backup_cli[@]}" status
```

Hai ID phải khác nhau. `status` cần liệt kê cả hai snapshot và báo `latest` là ID của phiên 2.

### Khôi phục phiên 1 và đối chiếu SHA-256

Khôi phục thư mục `reports` từ phiên 1 vào đích mới. Khi chọn một thư mục, CLI đặt **nội dung** của thư mục đó trực tiếp dưới đích.

```bash
restored_v1="$demo_root/restore/phien-1"
"${backup_cli[@]}" restore "$snapshot_v1" --path reports --destination "$restored_v1"
```

Kết quả cần có `"verified": true`. So sánh file khôi phục với bản đối chiếu đã lưu trước lần backup đầu. Kiểm tra thêm rằng file đang dùng ở nguồn vẫn có nội dung phiên 2.

```bash
sha256sum "$demo_root/expected/bao-cao-v1.txt" "$restored_v1/bao-cao.txt"
cmp "$demo_root/expected/bao-cao-v1.txt" "$restored_v1/bao-cao.txt" &&
  printf 'PASS: file khôi phục khớp phiên 1\n'
printf 'Phien ban 2\n' | cmp - "$demo_root/source/reports/bao-cao.txt" &&
  printf 'PASS: file nguồn vẫn là phiên 2\n'
```

Thử thêm một ca bảo vệ dữ liệu bằng cách yêu cầu restore lại vào đích trên. Lệnh phải trả mã khác `0`, báo đích đã tồn tại, và file đã khôi phục vẫn khớp bản đối chiếu.

```bash
if "${backup_cli[@]}" restore "$snapshot_v1" --path reports --destination "$restored_v1"; then
  printf 'FAIL: restore đã chấp nhận đích có sẵn\n' >&2
else
  printf 'Mã thoát của restore: %s\n' "$?"
fi
cmp "$demo_root/expected/bao-cao-v1.txt" "$restored_v1/bao-cao.txt"
```

### Xem nhật ký và xem trước retention

```bash
"${backup_cli[@]}" history --limit 30
"${backup_cli[@]}" history --local --operation restore --limit 10
"${backup_cli[@]}" cleanup --dry-run
```

Đối chiếu ID, trạng thái backup, restore và ca từ chối đích đã có trong lịch sử. Với hai snapshot mới, dry-run phải giữ cả hai và ghi `newest-successful` cho phiên 2. Để thử ngưỡng hết hạn và thao tác xóa trên dữ liệu tạm, chạy lệnh sau từ checkout trên Linux. [Ma trận và kết quả kiểm thử cục bộ](testing.md)

```bash
python3 -m unittest tests.test_core.StoreTests.test_retention_boundary_latest_and_dry_run_apply -v
```

## 6. Ghi kết quả và kiểm tra lỗi

| Hạng mục | Điều kiện đạt |
| --- | --- |
| Kết nối riêng | Arch ping được IPv4 Tailscale của Ubuntu và SSH `BatchMode=yes` thoát mã `0`. |
| Backup | Có hai ID riêng, cả hai kiểm tra SHA-256 thành công và `latest` là phiên mới hơn. |
| Restore | File phục hồi khớp SHA-256 của phiên 1, nguồn vẫn giữ phiên 2. Đích có sẵn bị từ chối với mã khác `0`. |
| History và retention | Tra được thao tác, dry-run giữ hai snapshot mới và không xóa dữ liệu. |

Ghi ngày kiểm thử, hai bản phân phối, phiên bản `rsync`, hai ID và kết quả SHA-256. Kết quả bài thử này xác nhận đường truyền Tailscale và luồng backup/restore thủ công. Nếu cần kiểm thử lịch, dùng mục systemd trong hướng dẫn triển khai, chỉnh `User`, `Group` và đường dẫn `ExecStart` theo máy Arch và file cấu hình thử. Service mẫu thực hiện `cleanup --apply` sau khi backup thành công, nên dùng kho thử đã tạo ở trên. Chỉ ghi lịch chạy đạt sau khi có một lần timer thực sự kích hoạt service và journal xác nhận kết quả. [Hướng dẫn kiểm tra systemd](setup.vi.md#5-bật-lịch-systemd-trên-máy-b)

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| `tailscale status` thiếu máy Ubuntu | Kiểm tra `tailscaled.service`, đăng nhập tailnet và phê duyệt thiết bị nếu tailnet yêu cầu. |
| `tailscale ping` được nhưng SSH timeout hoặc từ chối kết nối | Kiểm tra `systemctl status ssh.service` trên Ubuntu, cổng TCP 22, tường lửa và chính sách truy cập giữa hai thiết bị trong tailnet. |
| `Host key verification failed` | Đối chiếu lại IPv4 Ubuntu, fingerprint qua console và đường dẫn `SSH_KNOWN_HOSTS`. |
| `Permission denied (publickey)` | Kiểm tra public key nằm trong `authorized_keys` của `backup`, quyền file, `SSH_IDENTITY` và SSH agent nếu khóa có passphrase. |
| SSH thành công nhưng `status` báo lỗi | Kiểm tra đường dẫn `SERVER_PROGRAM`, `SERVER_CONFIG`, ID client và kết quả `init` trên Ubuntu. |
| Backup mất phản hồi giữa chừng | Kiểm tra `history --local`, `history` và `status` sau khi kết nối trở lại. Nếu snapshot đã xuất hiện trong `status`, chạy `verify` với ID đó. |
