# Chạy thử LinuxBackupSys giữa Ubuntu và máy ảo Arch Linux

Hai người cùng mở trang này. Người dùng **Ubuntu** chuẩn bị máy chủ giữ bản sao. Người dùng **Arch Linux trong Oracle VirtualBox** tạo dữ liệu, gửi bản sao và lấy tệp cũ về. Hai máy ở hai mạng Internet khác nhau và kết nối qua Tailscale.

Bài thử dùng một tệp `reports/bao-cao.txt`. Hai bạn sẽ sao lưu hai lần, nhìn thấy hai mã phiên trên Ubuntu, rồi lấy lại nội dung lần đầu trên Arch. Kết quả đạt khi tệp khôi phục khớp từng byte với bản đầu **và** tệp đang làm việc vẫn giữ nội dung lần hai.

| Người thực hiện | Chạy lệnh ở đâu | Chuẩn bị |
| --- | --- | --- |
| A, người giữ kho | Terminal trên Ubuntu 24.04 LTS | Tài khoản có `sudo`, Internet và tài khoản Tailscale có quyền mời người dùng |
| B, người sao lưu | Terminal **bên trong máy ảo Arch**, đăng nhập bằng tài khoản thường | Internet trong máy ảo, `sudo` để cài gói và tài khoản Tailscale của mình |

Dùng Bash. Nếu Terminal của bạn đang dùng `fish` hoặc `zsh`, gõ `bash` trước khi bắt đầu. Chạy từng khối theo nhãn **Ubuntu** hoặc **Arch** và đọc kết quả trước khi sang bước sau. B nên giữ nguyên tab Bash suốt bài thử.

## 1. Cài công cụ và clone dự án

**Ubuntu · A.** Thực hiện từ máy của bạn kể cả khi chưa từng clone dự án.

```bash
sudo apt update
sudo apt install git curl ca-certificates openssh-server rsync python3 nano
sudo systemctl enable --now ssh
python3 --version
python3 -c 'import tomllib; print("Python OK")'
```

**Arch · B.** Nếu máy ảo đã có Internet, giữ nguyên cấu hình mạng. Nếu chưa có, tắt máy ảo, vào **Settings → Network → Adapter 1**, bật **Enable Network Adapter**, chọn **NAT** và **Cable Connected**, rồi khởi động lại Arch. Mô hình này dùng kết nối đi ra từ máy ảo nên không cần chuyển tiếp cổng trên VirtualBox hoặc router. [Tài liệu mạng Oracle VirtualBox](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/networkingdetails.html)

```bash
sudo pacman -Syu --needed git openssh rsync python tailscale
python3 -c 'import tomllib; print("Python OK")'
```

`pacman -Syu` cập nhật toàn hệ thống Arch. Nếu cần khởi động lại sau khi cập nhật kernel, làm ngay ở đây. Cả hai máy phải có Python 3.11 trở lên và in `Python OK`.

**Cả hai máy.** Mỗi người chạy khối sau trong Terminal của mình. Dùng thư mục checkout mới để tách khỏi bản đang phát triển.

```bash
git clone --branch mvp-implementation --single-branch \
  https://github.com/HamNgo/LinuxBackupSys.git "$HOME/LinuxBackupSys-lab"
git -C "$HOME/LinuxBackupSys-lab" branch --show-current
git -C "$HOME/LinuxBackupSys-lab" rev-parse --short HEAD
```

**Đối chiếu qua cuộc gọi:** cả hai nhìn thấy nhánh `mvp-implementation` và cùng một mã commit. Nếu thư mục clone đã tồn tại, chạy hai lệnh `git -C` để nhận diện bản đang có trước khi tiếp tục.

## 2. Kết nối hai máy qua Tailscale

**Ubuntu · A.** Nếu chưa cài Tailscale, tải và chạy trình cài chính thức. [Hướng dẫn Tailscale cho Linux](https://tailscale.com/docs/install/linux)

```bash
installer=$(mktemp) &&
  curl -fsSLo "$installer" https://tailscale.com/install.sh &&
  sh "$installer"
```

```bash
sudo systemctl enable --now tailscaled
sudo tailscale up
tailscale ip -4
```

Mở URL đăng nhập mà `tailscale up` hiển thị. A gửi **địa chỉ IPv4 do `tailscale ip -4` in ra** cho B. Trong Tailscale Admin Console, A vào **Users → Invite external users**, chọn quyền **Member** và gửi lời mời. B mở lời mời bằng tài khoản riêng, rồi chọn đúng mạng của A khi đăng ký máy Arch. Nếu hai người đã cùng một tailnet, chỉ cần kiểm tra hai thiết bị xuất hiện. [Cách mời người dùng](https://tailscale.com/docs/features/sharing/how-to/invite-any-user)

**Arch · B.** Chạy Tailscale bên trong Arch, mở URL đăng nhập và chọn mạng vừa được mời.

```bash
sudo systemctl enable --now tailscaled
sudo tailscale up
tailscale status
```

Chạy riêng dòng sau, nhập IPv4 Tailscale **của Ubuntu** rồi nhấn Enter.

```bash
read -r -p 'IPv4 Tailscale cua Ubuntu: ' server_ip
```

```bash
tailscale ping "$server_ip"
```

**Mốc 1:** thấy `pong` từ Ubuntu, trực tiếp hoặc qua relay. Hai bạn sẽ kiểm tra TCP 22 và khóa đăng nhập riêng ở bước 4. Bài này dùng OpenSSH của Ubuntu trên đường truyền Tailscale. Khi chạy `tailscale up` hãy để tính năng riêng **Tailscale SSH** tắt trên máy lab vì tính năng đó có thể tiếp quản cổng 22. [OpenSSH qua Tailscale](https://tailscale.com/docs/reference/ssh-over-tailscale)

## 3. Ubuntu chuẩn bị tài khoản và kho

**Chỉ A thực hiện.** Dùng tài khoản mới `lbsbackup` để tránh trùng với tài khoản hệ thống `backup` có thể đã có trên Ubuntu. Các lệnh dưới dành cho lần thiết lập đầu tiên. Nếu tài khoản, kho `/srv/linux-backup-tailnet-test` hoặc file cấu hình cùng tên đã có, chỉ dùng lại khi A xác nhận chúng thuộc đúng bài thử này.

```bash
sudo bash "$HOME/LinuxBackupSys-lab/deploy/install-code.sh" /opt/linux-backup-lab
sudo adduser --disabled-password --gecos '' lbsbackup
getent passwd lbsbackup
id lbsbackup
```

Kiểm tra `lbsbackup` có home `/home/lbsbackup` và shell đăng nhập như `/bin/bash`. Tài khoản này dùng khóa SSH và không cần quyền `sudo`. Trình cài chỉ chấp nhận thư mục `/opt/linux-backup-lab` mới. Nếu lần trước đã cài đúng phiên bản ở đó, bỏ qua lệnh cài mã.

```bash
sudo install -d -m 0755 /etc/linux-backup
sudo install -d -o lbsbackup -g "$(id -gn lbsbackup)" -m 0700 /srv/linux-backup-tailnet-test
sudo nano /etc/linux-backup/server-tailnet-test.conf
```

Dán bốn dòng TOML sau vào `nano`, nhấn **Ctrl+O**, **Enter**, rồi **Ctrl+X**.

```toml
CLIENT_ID = "arch-tailnet-test"
STORAGE_ROOT = "/srv/linux-backup-tailnet-test"
RETENTION_DAYS = 7
TIMEOUT_SECONDS = 3600
```

```bash
sudo chown "root:$(id -gn lbsbackup)" /etc/linux-backup/server-tailnet-test.conf
sudo chmod 0640 /etc/linux-backup/server-tailnet-test.conf
sudo -u lbsbackup python3 /opt/linux-backup-lab/server/agent.py \
  --config /etc/linux-backup/server-tailnet-test.conf init
```

**Mốc 2:** kết quả có `"initialized":true` và `client_root` kết thúc bằng `/arch-tailnet-test`. A giữ Ubuntu thức, có mạng, `ssh` và `tailscaled` hoạt động. Arch sẽ tự gọi chương trình trên Ubuntu qua SSH khi có yêu cầu.

## 4. Trao đổi khóa và kiểm tra OpenSSH

**Arch · B tạo khóa riêng cho bài thử.** Thư mục `lab` nằm trên hệ thống tệp Linux của máy ảo. Nó sẽ chứa cả cấu hình và kết quả đối chiếu.

```bash
umask 077
lab=$(mktemp -d "$(cd -- "$HOME" && pwd -P)/linux-backup-lab.XXXXXX")
printf 'Ghi lai duong dan lab: %s\n' "$lab"
ssh-keygen -t ed25519 -f "${lab:?}/id_ed25519" -C arch-linuxbackupsys-lab
cat "$lab/id_ed25519.pub"
```

Ghi lại đường dẫn `lab` để dùng tiếp khi đổi tab. Nếu dùng passphrase, nạp khóa bằng `ssh-add "$lab/id_ed25519"` trong phiên có SSH agent trước khi chạy client. Với cặp khóa chỉ dùng cho lab, có thể nhấn **Enter** hai lần ở câu hỏi passphrase. **B gửi A đúng một dòng công khai** từ file `.pub`, bắt đầu bằng `ssh-ed25519`. Khóa riêng `id_ed25519` ở lại trên Arch.

**Ubuntu · A nhận khóa.** Tạo file dưới đúng tài khoản, sau đó dán dòng của B ở cuối file, mỗi khóa một dòng.

```bash
sudo -u lbsbackup -H bash -c 'umask 077; mkdir -p "$HOME/.ssh"; touch "$HOME/.ssh/authorized_keys"'
sudo -u lbsbackup -H nano /home/lbsbackup/.ssh/authorized_keys
```

Lưu file rồi chạy:

```bash
sudo chmod 700 /home/lbsbackup/.ssh
sudo chmod 600 /home/lbsbackup/.ssh/authorized_keys
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

**A đọc chuỗi `SHA256:...` cho B** qua cuộc gọi hoặc kênh riêng đã dùng để liên hệ. Đây là fingerprint của máy chủ Ubuntu.

**Arch · B đăng nhập thử.** Dùng cùng tab Bash đã khai báo `lab` và `server_ip`.

```bash
ssh_lab=(ssh -F /dev/null -p 22 -o ConnectTimeout=10 -o IdentitiesOnly=yes
  -o HostKeyAlgorithms=ssh-ed25519 -o "UserKnownHostsFile=\"${lab:?}/known_hosts\""
  -i "$lab/id_ed25519")
"${ssh_lab[@]}" -o StrictHostKeyChecking=ask "lbsbackup@${server_ip:?}" whoami
```

So fingerprint trên màn hình Arch với chuỗi A vừa đọc. Nếu khớp, gõ `yes`. Lệnh phải in `lbsbackup`. Nếu khác, kiểm tra lại địa chỉ và fingerprint tại console Ubuntu trước khi tiếp tục.

```bash
"${ssh_lab[@]}" -o BatchMode=yes -o StrictHostKeyChecking=yes \
  "lbsbackup@$server_ip" 'whoami && python3 --version && rsync --version'
```

**Mốc 3:** Arch in được `lbsbackup`, phiên bản Python và rsync của Ubuntu, không hỏi mật khẩu. Đây là phép thử SSH theo cách client cần để chạy tự động.

## 5. Arch tạo tệp mẫu và kết nối kho

**B thực hiện bằng tài khoản thường.** Giữ bản chuẩn của phiên đầu trong `expected/`, bên ngoài thư mục nguồn.

```bash
mkdir -p "${lab:?}/source/reports" "$lab/expected" "$lab/restore"
printf 'Phien ban 1\n' > "$lab/source/reports/bao-cao.txt"
cp "$lab/source/reports/bao-cao.txt" "$lab/expected/bao-cao-v1.txt"
```

Dán nguyên khối sau vào Bash để địa chỉ và đường dẫn thật được điền vào TOML. `SERVER_PROGRAM` và `SERVER_CONFIG` là đường dẫn trên Ubuntu; các đường dẫn chứa `$lab` nằm trên Arch.

```bash
cat > "${lab:?}/client.conf" <<EOF
CLIENT_ID = "arch-tailnet-test"
BACKUP_SOURCE = "$lab/source"
SSH_HOST = "${server_ip:?}"
SSH_USER = "lbsbackup"
SSH_PORT = 22
SSH_IDENTITY = "$lab/id_ed25519"
SSH_KNOWN_HOSTS = "$lab/known_hosts"
SERVER_PROGRAM = "/opt/linux-backup-lab/server/agent.py"
SERVER_CONFIG = "/etc/linux-backup/server-tailnet-test.conf"
LOG_FILE = "$lab/history.jsonl"
RESTORE_ROOT = "$lab/restore"
VERIFY_CHECKSUM = true
COMPRESSION = false
TIMEOUT_SECONDS = 3600
EOF
chmod 600 "$lab/client.conf"
```

```bash
cli=(bash "$HOME/LinuxBackupSys-lab/backup-manager.sh" --config "$lab/client.conf")
"${cli[@]}" configure --check
"${cli[@]}" status
```

**Mốc 4:** `configure --check` trả `"valid": true`. Lệnh `status` gọi được agent trên Ubuntu và trả `client_id` là `arch-tailnet-test`. Kho mới có `snapshots` là `[]` và `latest` là `null`.

## 6. Hai người cùng quan sát hai lần sao lưu

**Arch · B.** Chạy lần đầu:

```bash
"${cli[@]}" backup
```

Trong JSON, kiểm tra `transfer` là `complete`, `verification` là `verified`, `publication` là `complete`. Sao chép giá trị `snapshot_id` (bỏ dấu ngoặc kép), rồi chạy dòng sau và dán ID khi được hỏi:

```bash
read -r -p 'Dan snapshot_id lan thu nhat: ' v1
```

```bash
"${cli[@]}" verify "${v1:?}"
```

Chỉ sau khi `verify` trả `"verified": true`, thay nội dung tệp trong nguồn thử rồi sao lưu lần hai:

```bash
printf 'Phien ban 2\n' > "${lab:?}/source/reports/bao-cao.txt"
"${cli[@]}" backup
```

```bash
read -r -p 'Dan snapshot_id lan thu hai: ' v2
```

```bash
"${cli[@]}" verify "${v2:?}"
"${cli[@]}" status
printf 'V1 = %s\nV2 = %s\n' "$v1" "$v2"
```

**Ubuntu · A.** Quan sát trực tiếp kho trong khi B đọc hai ID:

```bash
sudo -u lbsbackup ls -1 /srv/linux-backup-tailnet-test/arch-tailnet-test/snapshots
```

**Mốc 5:** cả hai ID đều xuất hiện trên Ubuntu và khác nhau. Trên Arch, `verify` của từng phiên trả `true`, `latest` trùng với V2.

## 7. Arch lấy lại V1 và chứng minh nguồn vẫn là V2

**B thực hiện.** Đích `lay-lai-v1` phải chưa tồn tại. Để lệnh `restore` tự tạo thư mục này dưới `$lab/restore`.

```bash
dest="${lab:?}/restore/lay-lai-v1"
"${cli[@]}" restore "${v1:?}" --path reports/bao-cao.txt --destination "$dest"
```

Khi kết quả trả `"verified": true`, mở tệp vừa khôi phục và tệp đang làm việc:

```bash
printf 'Tep khoi phuc: '; cat "$dest/bao-cao.txt"
printf 'Tep dang lam viec: '; cat "$lab/source/reports/bao-cao.txt"
```

Kết quả mong đợi:

```text
Tep khoi phuc: Phien ban 1
Tep dang lam viec: Phien ban 2
```

```bash
sha256sum "$lab/expected/bao-cao-v1.txt" "$dest/bao-cao.txt"
cmp "$lab/expected/bao-cao-v1.txt" "$dest/bao-cao.txt" &&
  echo 'PASS 1: Tep khoi phuc khop tung byte voi ban dau'
printf 'Phien ban 2\n' | cmp - "$lab/source/reports/bao-cao.txt" &&
  echo 'PASS 2: Tep nguon van giu phien ban 2'
```

**Mốc 6:** hai chuỗi SHA-256 giống nhau và có đủ hai dòng `PASS`. Để ghi nhận kết quả, A lưu ảnh hai ID trong kho, B lưu ảnh hai phép so sánh và ghi lại mã commit. Hai ảnh này ứng với cùng một lượt thử.

## 8. Arch xem lịch sử và mở giao diện

```bash
"${cli[@]}" history --limit 20
"${cli[@]}" history --local --operation restore --limit 5
"${cli[@]}" cleanup --dry-run
```

Lệnh đầu đọc lịch sử Ubuntu, lệnh thứ hai đọc lịch sử Arch. Lệnh cuối cho xem những phiên sẽ được giữ hoặc dọn. Với hai snapshot vừa tạo, cả hai đều được giữ.

Nếu Arch có desktop, B có thể khôi phục lại qua giao diện bằng chính V1 đã tạo. Chạy trong terminal của phiên đồ họa:

```bash
sudo pacman -S --needed tk
"${cli[@]}" gui
```

Vào **Bản sao lưu**, chọn đúng mã V1, bấm **Khôi phục… → Duyệt phiên…**, chọn `reports/bao-cao.txt`. Để trống ô đích để ứng dụng tạo thư mục mới. Mở tệp theo đường dẫn ứng dụng trả về.

## Khi cần tiếp tục hoặc báo lỗi

**Nếu B đã đóng Terminal** nhưng còn thư mục lab, mở Bash, nhập lại đường dẫn đã ghi ở bước 4. Sau khi đã tạo `client.conf`, có thể tiếp tục như sau:

```bash
read -r -p 'Duong dan tuyet doi den thu muc lab da ghi: ' lab
```

```bash
cli=(bash "$HOME/LinuxBackupSys-lab/backup-manager.sh" --config "${lab:?}/client.conf")
"${cli[@]}" status
```

Lấy lại V1, V2 từ các mã đã ghi ở bước 6 và gán lại bằng hai lệnh `read` tương ứng. Nếu đã khôi phục một lần, chọn một tên đích mới dưới `$lab/restore`. Nếu ngắt buổi thử trước khi tạo `client.conf`, nhập lại cả `server_ip` ở bước 2 và khai báo lại mảng `ssh_lab` ở bước 4 để dùng tiếp khóa đã có.

| Mốc gặp lỗi | Kiểm tra tại máy nào |
| --- | --- |
| Arch chưa thấy Ubuntu trong `tailscale status` | Hai người kiểm tra tên tailnet, việc nhận lời mời và trạng thái duyệt thiết bị. Trên Arch kiểm tra `systemctl is-active tailscaled`. |
| Có `pong` nhưng SSH timeout hoặc `Connection refused` | Ubuntu chạy `systemctl status ssh --no-pager` và `sudo ss -ltnp`. Kiểm tra cổng TCP 22, quyền truy cập của Arch trong tailnet và firewall của Ubuntu trên `tailscale0`. |
| `Permission denied (publickey)` | A kiểm tra dòng `.pub`, chủ sở hữu và quyền của `/home/lbsbackup/.ssh/authorized_keys`. B kiểm tra đúng `lbsbackup`, đúng thư mục `lab` và SSH agent nếu có passphrase. |
| `Host key verification failed` | A đọc lại fingerprint từ console Ubuntu. B đối chiếu IP, fingerprint và file `$lab/known_hosts`. |
| SSH chạy được, `status` lỗi | A kiểm tra `init` ở bước 3. B kiểm tra `CLIENT_ID`, `SERVER_PROGRAM` và `SERVER_CONFIG` trong `$lab/client.conf`. |
| Mất mạng ngay sau lệnh `backup` | Khi kết nối lại, B chạy `status` và `history`. Nếu có phiên mới, chạy `verify` với ID đó trước khi sao lưu lại. |
| `restore` báo đích đã tồn tại | B giữ nguyên dữ liệu đã khôi phục và chọn tên đích mới khi thực hiện lại bước 7. |

Khi báo lỗi, gửi **số bước, tên máy (Ubuntu hay Arch), lệnh vừa chạy và nguyên văn thông báo lỗi**. Nếu lỗi xảy ra sau khi chạy backup, bổ sung mã phiên liên quan nếu có. Giữ khóa riêng và liên kết đăng nhập Tailscale trên máy của người sử dụng.

Xem thêm [tham số cấu hình và mã thoát](configuration.md), [tài liệu triển khai qua Tailscale](setup-tailscale.vi.md) và [phạm vi kiểm thử đã ghi nhận](testing.md).
