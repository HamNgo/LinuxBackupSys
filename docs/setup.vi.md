# Hướng dẫn triển khai LinuxBackupSys trên hai máy Ubuntu

[English version](setup.md)

Nếu máy Ubuntu và máy Arch Linux ở hai mạng Internet khác nhau, xem [hướng dẫn triển khai và kiểm thử qua Tailscale](setup-tailscale.vi.md).

Hướng dẫn dùng hai máy Ubuntu 24.04 LTS trong cùng mạng LAN. Chép cùng một phiên bản mã nguồn lên cả hai máy và chạy các lệnh cài mã từ thư mục gốc của dự án.

| Máy | Vai trò | Tài khoản và đường dẫn trong ví dụ |
| --- | --- | --- |
| A | Nhận dữ liệu qua SSH và quản lý snapshot | Tài khoản `backup`, kho `/srv/linux-backup`, cấu hình `/etc/linux-backup/server.conf` |
| B | Gửi dữ liệu, yêu cầu khôi phục và chạy lịch | Tài khoản `backup-client`, cấu hình `/etc/linux-backup/backup.conf` |

`backup-client` là tên minh họa cho tài khoản thường có quyền đọc nguồn trên máy B. Thay tên, nhóm và đường dẫn home tương ứng trong cấu hình và systemd unit. Thay `MAY_A` trong các lệnh bằng IP LAN hoặc tên DNS của máy A. Ví dụ dùng cổng SSH 22. Nếu dùng cổng khác, thêm `-p CỔNG` vào cả hai lệnh `ssh` và đặt `SSH_PORT` tương ứng trên máy B.

## 1. Chuẩn bị máy A (server)

Chạy bằng tài khoản quản trị trên máy A. Lệnh `sudo adduser` chỉ chạy khi chưa có tài khoản `backup` chuyên dùng cho dự án.

```bash
sudo apt update
sudo apt install python3 rsync openssh-server
sudo systemctl enable --now ssh
if ! id backup >/dev/null 2>&1; then
    sudo adduser --disabled-password --gecos '' backup
fi
sudo install -d -o backup -g backup -m 0700 /srv/linux-backup
sudo install -d -m 0755 /etc/linux-backup
sudo bash deploy/install-code.sh /opt/linux-backup
```

Script yêu cầu thư mục cài mã chưa tồn tại. Khi nâng cấp, cài vào một thư mục mới rồi cập nhật `SERVER_PROGRAM` trên máy B và các đường dẫn trong service nếu vị trí cài trên máy B thay đổi. Dùng filesystem Linux cho kho snapshot và dành đủ dung lượng vì mỗi phiên lưu một bản đầy đủ.

Lần thiết lập đầu, tạo cấu hình server từ mẫu. Nếu file đã có, chỉnh file hiện tại bằng `sudoedit`.

```bash
sudo cp -n /opt/linux-backup/server/server.conf.example /etc/linux-backup/server.conf
sudo chown root:backup /etc/linux-backup/server.conf
sudo chmod 0640 /etc/linux-backup/server.conf
sudoedit /etc/linux-backup/server.conf
```

Giữ `CLIENT_ID = "client-b"` hoặc đặt một mã khác rồi dùng cùng giá trị ở máy B. `STORAGE_ROOT` phải là đường dẫn tuyệt đối tới thư mục kho do tài khoản `backup` sở hữu với quyền `0700`. `RETENTION_DAYS = 7` giữ các bản trong 7 khoảng 24 giờ tính từ lúc hoàn tất theo UTC và luôn giữ bản thành công mới nhất. Khởi tạo kho dưới đúng tài khoản dịch vụ.

```bash
sudo -u backup python3 /opt/linux-backup/server/agent.py \
  --config /etc/linux-backup/server.conf init
```

## 2. Chuẩn bị máy B (client)

Từ thư mục gốc dự án trên máy B, cài công cụ và mã nguồn.

```bash
sudo apt update
sudo apt install python3 rsync openssh-client
sudo install -d -m 0755 /etc/linux-backup
sudo bash deploy/install-code.sh /opt/linux-backup
```

Đăng nhập bằng tài khoản sẽ chạy backup trên máy B. Chuẩn bị thư mục lưu khóa, nhật ký và bản khôi phục. Tạo khóa riêng cho dự án nếu chưa có cặp khóa phù hợp.

```bash
install -d -m 0700 "$HOME/.ssh" "$HOME/.local/state/linux-backup" "$HOME/Restored"
if [[ ! -e "$HOME/.ssh/linux-backup" && ! -e "$HOME/.ssh/linux-backup.pub" ]]; then
    ssh-keygen -t ed25519 -f "$HOME/.ssh/linux-backup" -C linux-backup-client
fi
```

Chuyển file `~/.ssh/linux-backup.pub` cho người quản trị máy A và giữ khóa riêng trên máy B. Nếu khóa có mật khẩu, job systemd cần truy cập SSH agent đã nạp khóa. Phép thử với `BatchMode=yes` và lần chạy service ở các bước sau sẽ kiểm tra khả năng chạy tự động.

## 3. Thiết lập SSH giữa hai máy

Trên máy A, tạo `.ssh` và `authorized_keys` dưới tài khoản `backup`, rồi thêm **một dòng khóa công khai** từ máy B vào cuối file. Giữ các khóa đã có. Ví dụ dưới đây giả định home của `backup` là `/home/backup`, có thể tra bằng `getent passwd backup`.

```bash
sudo -u backup -H bash -c 'umask 077; mkdir -p "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"; chmod 0700 "$HOME/.ssh"; chmod 0600 "$HOME/.ssh/authorized_keys"'
sudoedit /home/backup/.ssh/authorized_keys
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Lệnh cuối hiển thị fingerprint khóa máy chủ. Lấy kết quả từ console hoặc kênh quản trị đáng tin cậy của máy A. Trên máy B, chạy lệnh sau bằng tài khoản backup và đối chiếu fingerprint mà SSH hiển thị trước khi chấp nhận. Nếu hai giá trị khác nhau, dừng và kiểm tra lại IP hoặc tên máy.

```bash
ssh -F /dev/null -o HostKeyAlgorithms=ssh-ed25519 \
  -o IdentitiesOnly=yes -o "UserKnownHostsFile=$HOME/.ssh/known_hosts" \
  -i "$HOME/.ssh/linux-backup" backup@MAY_A true
```

Kiểm tra kết nối không tương tác và các công cụ trên máy A. Lệnh cần in phiên bản Python, rsync và kết thúc mà không hỏi mật khẩu hay xác nhận máy chủ.

```bash
ssh -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o IdentitiesOnly=yes -o "UserKnownHostsFile=$HOME/.ssh/known_hosts" \
  -i "$HOME/.ssh/linux-backup" backup@MAY_A 'python3 --version && rsync --version'
```

## 4. Cấu hình máy B và thử backup, restore

Trên máy B, tạo thư mục dữ liệu thử dưới home của tài khoản chạy backup. Dùng đường dẫn được in ra làm `BACKUP_SOURCE` cho lần chạy thử.

```bash
demo_source=$(mktemp -d "$HOME/linux-backup-demo.XXXXXX")
printf 'Du lieu thu nghiem LinuxBackupSys\n' > "$demo_source/thu-nghiem.txt"
printf '%s\n' "$demo_source"
```

Tạo cấu hình từ mẫu. Thay `backup-client` trong lệnh `chown` bằng nhóm chính của tài khoản chạy backup. Dùng `id -gn` trong phiên đăng nhập của tài khoản đó để xem tên nhóm.

```bash
sudo cp -n /opt/linux-backup/client/client.conf.example /etc/linux-backup/backup.conf
sudo chown root:backup-client /etc/linux-backup/backup.conf
sudo chmod 0640 /etc/linux-backup/backup.conf
sudoedit /etc/linux-backup/backup.conf
```

File cấu hình dùng TOML. Điền các giá trị sau trước khi chạy thử.

| Khóa | Giá trị cần điền |
| --- | --- |
| `CLIENT_ID` | Giống giá trị trên máy A, ví dụ `"client-b"` |
| `BACKUP_SOURCE` | Đường dẫn tuyệt đối đến file thường hoặc thư mục đọc được trên máy B. Thử với thư mục chứa `thu-nghiem.txt` trước khi chọn dữ liệu thật |
| `SSH_HOST`, `SSH_USER`, `SSH_PORT` | Địa chỉ máy A, `"backup"` và `22` theo ví dụ |
| `SSH_IDENTITY`, `SSH_KNOWN_HOSTS` | Đường dẫn tuyệt đối tới khóa riêng và file `known_hosts` của tài khoản chạy backup trên máy B |
| `SERVER_PROGRAM`, `SERVER_CONFIG` | `"/opt/linux-backup/server/agent.py"` và `"/etc/linux-backup/server.conf"` trên máy A |
| `LOG_FILE`, `RESTORE_ROOT` | Đường dẫn tuyệt đối tới file `history.jsonl` trong thư mục nhật ký và tới thư mục `Restored` đã tạo trên máy B |
| `VERIFY_CHECKSUM` | `true` để đối chiếu SHA-256 của dữ liệu đã nhận với nguồn trước khi công bố snapshot |

Viết đường dẫn home đầy đủ trong TOML, ví dụ `/home/backup-client/Restored`. Thư mục nguồn cần tách khỏi khóa SSH, nhật ký và thư mục khôi phục. Xem thêm giá trị mặc định và mã thoát trong [tài liệu cấu hình và CLI](configuration.md).

Chạy trong Bash trên máy B bằng tài khoản backup. `configure --check` kiểm tra file cấu hình, còn `status` xác nhận client truy cập được kho trên máy A.

```bash
backup_cli=(bash /opt/linux-backup/backup-manager.sh --config /etc/linux-backup/backup.conf)
"${backup_cli[@]}" configure --check
"${backup_cli[@]}" status
"${backup_cli[@]}" backup
```

Sao chép `snapshot_id` từ kết quả backup. Dùng ID đó để kiểm tra snapshot và khôi phục file thử. Lệnh restore trả về `destination`, là một thư mục mới dưới `RESTORE_ROOT`.

```bash
read -r -p 'Nhập snapshot_id vừa tạo: ' snapshot_id
"${backup_cli[@]}" verify "$snapshot_id"
"${backup_cli[@]}" restore "$snapshot_id" --path 'thu-nghiem.txt'
read -r -p 'Nhập đường dẫn destination từ kết quả restore: ' restored_dir
sha256sum "$demo_source/thu-nghiem.txt" "$restored_dir/thu-nghiem.txt"
"${backup_cli[@]}" history --limit 10
"${backup_cli[@]}" cleanup --dry-run
```

Hai mã SHA-256 phải giống nhau. Bỏ `--path` để khôi phục toàn bộ snapshot. Nếu dùng `--destination`, chọn một đường dẫn tuyệt đối chưa tồn tại và có thư mục cha sẵn. `cleanup --dry-run` cho xem ứng viên và lý do giữ hoặc xóa để bạn kiểm tra chính sách trước khi bật lịch.

## 5. Bật lịch systemd trên máy B

Sau khi thử thành công, cập nhật `BACKUP_SOURCE` trong `/etc/linux-backup/backup.conf` thành đường dẫn cần sao lưu định kỳ. Service mẫu chạy backup, rồi áp dụng retention nếu backup thành công. Kiểm tra kết quả dry-run ở bước trước vì chạy thử service cũng có thể xóa snapshot hết hạn. Timer chạy lúc **09:00 giờ Việt Nam** mỗi ngày (`02:00 UTC`), với độ trễ ngẫu nhiên tối đa 5 phút. `Persistent=true` cho phép chạy bù khi timer hoạt động lại sau một lịch bị lỡ.

Trong file service, đối chiếu `User`, `Group`, `WorkingDirectory` và `ExecStart` với máy B. Service đặt `PrivateTmp=true`, vì vậy giữ nguồn, cấu hình, khóa và dữ liệu khôi phục ngoài `/tmp` và `/var/tmp`.

```bash
sudo cp -n /opt/linux-backup/deploy/linux-backup.service /etc/systemd/system/
sudo cp -n /opt/linux-backup/deploy/linux-backup.timer /etc/systemd/system/
sudoedit /etc/systemd/system/linux-backup.service
sudo systemd-analyze verify /etc/systemd/system/linux-backup.service /etc/systemd/system/linux-backup.timer
sudo systemctl daemon-reload
sudo systemctl start linux-backup.service
sudo journalctl -u linux-backup.service --no-pager -n 50
```

Sau khi lần chạy service thành công, bật timer và xem giờ chạy tiếp theo. Nếu chuyển từ Cron sang systemd, tắt mục Cron cũ cho cùng job để tránh chạy trùng.

```bash
sudo systemctl enable --now linux-backup.timer
systemctl list-timers --all linux-backup.timer
```

Để dừng lịch, dùng `sudo systemctl disable --now linux-backup.timer`. Lệnh này dừng các lần kích hoạt tiếp theo. Nếu service đang chạy, theo dõi lần chạy đó trong journal.

## Xử lý lỗi thường gặp

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| SSH báo `Permission denied (publickey)` | Chạy lại phép thử SSH bằng đúng tài khoản ở máy B. Kiểm tra quyền khóa riêng `0600` và chủ sở hữu `authorized_keys` trên máy A |
| SSH báo `Host key verification failed` | Đối chiếu địa chỉ, cổng, file `SSH_KNOWN_HOSTS` và fingerprint lấy từ máy A trước khi cập nhật khóa tin cậy |
| Backup thất bại hoặc mất kết nối | Xem `history --local`, `history` và `status`. Một snapshot có thể đã được công bố trước khi mất phản hồi. Nếu `status` có ID đó, chạy `verify` trước khi thử lại |
| Restore thất bại | Kiểm tra đường dẫn `.restore-*` hoặc đích mà lệnh báo, rồi chọn một thư mục đích mới khi chạy lại |
| Lệnh trả mã `3` | Một tiến trình đang giữ khóa trên server. Đợi tiến trình kết thúc rồi thử lại |
| Timer có lịch nhưng không thấy snapshot mới | Xem `journalctl -u linux-backup.service`, kiểm tra cấu hình và thử chạy service để kiểm chứng quyền đọc nguồn, SSH và đường dẫn log của tài khoản systemd |

Tham khảo [quy trình demo](demo.md) để kiểm tra khôi phục từ phiên bản cũ và [kết quả kiểm thử](testing.md) để biết phạm vi đã xác nhận trong môi trường thử nghiệm.
