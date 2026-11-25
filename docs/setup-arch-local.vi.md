# Chạy thử LinuxBackupSys trên một máy Arch Linux trong VirtualBox

Bạn sẽ tạo hai bản sao của `ghichu.txt`, lấy lại nội dung phiên 1 bằng giao diện tiếng Việt và kiểm tra rằng tệp đang dùng vẫn ở phiên 2. Một máy Arch chạy cả client lẫn server. Dữ liệu đi qua rsync và OpenSSH thật tới `127.0.0.1`, rồi được lưu trên cùng ổ đĩa ảo. Bài thử này chưa kiểm tra khả năng phục hồi khi hỏng ổ đĩa hoặc kết nối giữa hai máy.

**Bạn đã làm dở bài thử?** Khi Terminal báo `/source/ghichu.txt: No such file or directory`, hãy [mở lại đúng bài thử](#tiep-tuc). Khi thấy `ImportError: libtk8.6.so`, hãy [sửa Tk](#sua-tk). Cả hai trường hợp đều có thể giữ kho và các phiên đã tạo.

## 1. Chuẩn bị máy ảo và mã nguồn

Dùng Arch Linux đã cài trên ổ đĩa ảo, đăng nhập desktop bằng tài khoản thường có quyền `sudo`. Trong VirtualBox, chọn **Settings → Network → Adapter 1 → NAT** để Arch tải gói và mã nguồn. SSH giữa hai vai trò đi qua địa chỉ loopback ngay trong máy ảo. Tailscale và chuyển tiếp cổng chỉ liên quan đến kịch bản kết nối khác. [Mạng NAT trong VirtualBox](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/networkingdetails.html)

Mở Terminal **bên trong Arch**. Nếu shell hiện tại là Zsh hoặc Fish, gõ `bash` và nhấn Enter trước khi dán các lệnh. Chạy lần lượt từng khối, xử lý ngay khi có lỗi. `pacman -Syu` cập nhật cả hệ thống, vì vậy hãy xem danh sách gói trước khi chấp nhận. [Tài liệu pacman](https://man.archlinux.org/man/pacman.8.en)

```bash
sudo pacman -Syu --needed git python rsync openssh tk
python3 --version
python3 -m tkinter
```

Dự án cần Python 3.11 trở lên. Lệnh cuối sẽ mở một cửa sổ thử Tk. Đóng cửa sổ để tiếp tục. Trên máy chỉ có dòng lệnh, có thể bỏ qua phép thử Tk và dùng các lệnh CLI ở mục 6.

**Lần đầu tải dự án**, chạy:

```bash
git clone --branch mvp-implementation https://github.com/HamNgo/LinuxBackupSys.git "$HOME/LinuxBackupSys"
```

**Nếu đã clone**, dùng bản đang có. Trong checkout, kiểm tra `git status --short --branch`. Nếu đang làm dở thay đổi riêng, lưu công việc trước khi chuyển nhánh. Để cập nhật một checkout sạch:

```bash
git -C "$HOME/LinuxBackupSys" switch mvp-implementation
git -C "$HOME/LinuxBackupSys" pull --ff-only
```

Trong cả hai trường hợp, lưu đường dẫn thực của checkout vào biến `repo`. Nếu đã clone ở chỗ khác, thay đường dẫn trong lệnh này. Dùng hệ thống tệp Linux của máy ảo cho cả kho và bài thử để có đúng quyền sở hữu và quyền truy cập.

```bash
repo=$(git -C "$HOME/LinuxBackupSys" rev-parse --show-toplevel)
bash "$repo/backup-manager.sh" --help
```

Trong danh sách lệnh cần có `gui` và `list-files`.

## 2. Tạo dữ liệu riêng cho một bài thử mới

Chỉ chạy khối này khi muốn bắt đầu **bài mới**. `mktemp` tạo thư mục có hậu tố riêng dưới home. Ghi lại đường dẫn in ra. Nếu đã có snapshot muốn khôi phục, dùng mục **Tiếp tục ở tab mới** bên dưới.

```bash
umask 077
lab=$(mktemp -d "$HOME/linuxbackup-demo.XXXXXX")
mkdir -m 700 -- "${lab:?}/source" "$lab/restore" "$lab/storage" "$lab/expected"
printf 'Phien ban 1\n' > "${lab:?}/source/ghichu.txt"
cp -- "${lab:?}/source/ghichu.txt" "$lab/expected/ghichu-v1.txt"
printf 'Thư mục bài thử: %s\n' "$lab"
```

`source/` chứa dữ liệu được sao lưu. `storage/` là kho của server. `restore/` sẽ chứa kết quả khôi phục. `expected/ghichu-v1.txt` là bản đối chiếu chụp **trước** lần sao lưu đầu, nằm ngoài nguồn và kho. Dùng tài khoản desktop hiện tại cho cả hai vai trò trong VM thử nghiệm. Hướng dẫn triển khai hai máy dùng tài khoản server chuyên biệt. [Triển khai hai máy](setup.vi.md)

## 3. Cho phép SSH từ máy ảo về chính nó

Khởi động OpenSSH cho lần chạy hiện tại. Gói `openssh` trên Arch cung cấp unit `sshd.service`. [Danh sách tệp của gói OpenSSH](https://archlinux.org/packages/core/x86_64/openssh/files/)

```bash
sudo systemctl start sshd.service
systemctl is-active sshd.service
```

Khi thấy `active`, tạo khóa trong thư mục bài thử bằng tài khoản thường. Khóa demo dùng để đăng nhập không tương tác và chỉ được chấp nhận từ loopback. Nếu bài đang có `demo_key` và `demo_key.pub`, giữ cặp khóa đó.

```bash
if [[ ! -e "${lab:?}/demo_key" && ! -e "$lab/demo_key.pub" ]]; then
    ssh-keygen -q -t ed25519 -N '' -f "$lab/demo_key" -C "linuxbackup-$(basename -- "$lab")"
fi
```

Chỉ thêm **khóa công khai** vào `authorized_keys`. Khối sau giữ các dòng hiện hữu và kiểm tra trước khi thêm cùng một khóa.

```bash
install -d -m 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if [[ -s "${lab:?}/demo_key.pub" ]]; then
    rule="from=\"127.0.0.1\",restrict $(cat "$lab/demo_key.pub")"
    if ! grep -Fqx -- "$rule" "$HOME/.ssh/authorized_keys"; then
        printf '\n%s\n' "$rule" >> "$HOME/.ssh/authorized_keys"
    fi
fi
```

Đọc **khóa công khai của máy chủ** ngay trên console của VM để tạo `known_hosts` riêng cho bài mới. Khi quay lại một bài cũ gặp cảnh báo host key, xem bảng xử lý lỗi trước khi thay khóa đã tin cậy.

```bash
awk '{print "127.0.0.1", $1, $2}' /etc/ssh/ssh_host_ed25519_key.pub > "${lab:?}/known_hosts"
ssh -F /dev/null -p 22 -o BatchMode=yes -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=\"$lab/known_hosts\"" \
    -i "$lab/demo_key" "$(id -un)@127.0.0.1" 'echo SSH_OK'
```

Chỉ tiếp tục khi thấy **`SSH_OK`** và lệnh thoát thành công.

## 4. Khởi tạo kho, kiểm tra cấu hình và mở giao diện

Tạo hai tệp cấu hình trong **bài mới**. Bash sẽ ghi các đường dẫn tuyệt đối vào TOML. Nếu đã có `server.conf` và `client.conf`, giữ chúng và chuyển tới phần kiểm tra cấu hình bên dưới.

```bash
cat > "${lab:?}/server.conf" <<EOF
CLIENT_ID = "arch-vm"
STORAGE_ROOT = "$lab/storage"
RETENTION_DAYS = 7
EOF

cat > "${lab:?}/client.conf" <<EOF
CLIENT_ID = "arch-vm"
BACKUP_SOURCE = "$lab/source"
RESTORE_ROOT = "$lab/restore"
LOG_FILE = "$lab/history.jsonl"
SSH_HOST = "127.0.0.1"
SSH_USER = "$(id -un)"
SSH_PORT = 22
SSH_IDENTITY = "$lab/demo_key"
SSH_KNOWN_HOSTS = "$lab/known_hosts"
SERVER_PROGRAM = "${repo:?}/server/agent.py"
SERVER_CONFIG = "$lab/server.conf"
VERIFY_CHECKSUM = true
EOF
```

Chạy các lệnh dưới đây bằng **tài khoản desktop**. `configure --check` kiểm tra cấu hình. `init` chuẩn bị kho. `status` kiểm tra toàn bộ đường kết nối tới kho qua SSH.

```bash
cli=(bash "${repo:?}/backup-manager.sh" --config "${lab:?}/client.conf")
"${cli[@]}" configure --check
python3 "$repo/server/agent.py" --config "$lab/server.conf" init
"${cli[@]}" status
```

Kho mới trả về `"snapshots": []`. Với bài đang làm dở, `snapshots` liệt kê các phiên đã hoàn tất. Đăng ký mục menu bằng đường dẫn cấu hình của bài này:

```bash
python3 "$repo/deploy/install-desktop.py" --config "$lab/client.conf"
```

Mở **LinuxBackupSys** từ menu ứng dụng. Kiểm tra mục **Nguồn sao lưu** hiển thị thư mục `source` của đúng bài. Để xem lỗi khi khởi động từ Terminal, chạy `"${cli[@]}" gui`. Lệnh giữ Terminal cho tới khi bạn đóng cửa sổ ứng dụng. Nếu mở thêm tab để sửa tệp, làm theo mục sau.

<a id="tiep-tuc"></a>

## 5. Tiếp tục ở tab mới hoặc sau khi khởi động lại

Biến `lab`, `repo` và mảng `cli` thuộc về phiên Bash đã tạo chúng. Mở Terminal mới và chạy lệnh dùng `"$lab/source/ghichu.txt"` khi `lab` rỗng sẽ khiến Bash tìm `/source/ghichu.txt`. Thông báo `No such file or directory` trong trường hợp này xuất hiện trước khi Bash ghi tệp. Các snapshot đã có vẫn nằm trong kho.

Cách nhanh nhất là quay lại **tab Terminal ban đầu** rồi chạy `printf '%s\n' "$lab"`. Nếu đúng đường dẫn bài thử xuất hiện, tiếp tục ở mục 6. Nếu tab cũ đã đóng hoặc đang chạy GUI, hãy đối chiếu **Nguồn sao lưu** trong cửa sổ ứng dụng với danh sách dưới đây. Ví dụ, nếu nguồn là `/home/ban/linuxbackup-demo.ABC123/source`, chọn `/home/ban/linuxbackup-demo.ABC123/client.conf`. Hậu tố của mỗi bài thử sẽ khác nhau.

```bash
find "$HOME" -mindepth 2 -maxdepth 2 -type f -path '*/linuxbackup-demo.*/client.conf' -print
```

Trong tab mới, chạy dòng sau, dán **nguyên đường dẫn của tệp `client.conf`** tương ứng (không thêm dấu nháy), rồi nhấn Enter.

```bash
read -r -p 'Dán đường dẫn client.conf của bài đang dùng: ' profile
```

Nạp lại biến và so đường dẫn nguồn vừa in với cửa sổ ứng dụng:

```bash
if [[ "$profile" == /*/client.conf && -f "$profile" && -f "${profile%/*}/source/ghichu.txt" ]]; then
    lab=${profile%/*}
    repo=$(git -C "$HOME/LinuxBackupSys" rev-parse --show-toplevel)
    cli=(bash "${repo:?}/backup-manager.sh" --config "$profile")
    printf 'Nguồn đã chọn: %s/source\n' "$lab"
else
    unset lab cli
    printf 'Chưa tìm thấy cấu hình và tệp nguồn tương ứng. Hãy chọn lại đường dẫn.\n'
fi
```

Nếu clone ở vị trí khác, thay `"$HOME/LinuxBackupSys"` như ở mục 1. Nếu vừa khởi động lại và `systemctl is-active sshd.service` báo `inactive`, chạy `sudo systemctl start sshd.service`. Sau đó chạy `"${cli[@]}" status` và kiểm tra đúng ID của phiên 1 trước khi sửa dữ liệu. Việc mở lại menu đã đăng ký ở mục 4 không phụ thuộc các biến trong Terminal.

## 6. Tạo hai phiên rồi khôi phục đúng phiên đầu

Dùng **một** trong hai cột cho mỗi thao tác. GUI và CLI cùng làm việc với một kho. Trong GUI, mã của hàng đang chọn nằm ở dòng **Mã phiên**. Trong CLI, lấy trường `snapshot_id` từ kết quả `backup`.

| Bước | Qua giao diện | Lệnh tương ứng trong Bash |
| --- | --- | --- |
| 1. Sao lưu phiên 1 | Kiểm tra `source/ghichu.txt` chứa `Phien ban 1`, bấm **Sao lưu ngay**, chờ hoàn tất và ghi lại mã phiên 1. Nếu đã có phiên 1, dùng lại mã đó. | `"${cli[@]}" backup` |
| 2. Xác minh phiên 1 | Chọn phiên 1 rồi bấm **Kiểm tra SHA-256**. | `read -r -p 'Mã phiên 1: ' v1` rồi `"${cli[@]}" verify "$v1"` |
| 3. Sửa tệp nguồn | Giữ cửa sổ ứng dụng mở. Trong Bash, chạy khối **Sửa nội dung** dưới đây. | Dùng cùng khối lệnh. |
| 4. Sao lưu phiên 2 | Bấm **Sao lưu ngay** lần nữa. Danh sách hiển thị hai mã khác nhau và tự chọn phiên vừa tạo. | `"${cli[@]}" backup` rồi `"${cli[@]}" status` |
| 5. Lấy lại phiên 1 | **Chọn lại mã phiên 1** → **Khôi phục…** → **Duyệt phiên…** → `ghichu.txt` → **Chọn mục này**. Để trống **Thư mục đích mới**, bấm **Khôi phục**. | `"${cli[@]}" restore "$v1" --path ghichu.txt` |

**Sửa nội dung (bước 3).** Chỉ chạy sau khi xác nhận phiên 1 đã hoàn tất. Lệnh sẽ yêu cầu mở lại bài nếu `lab` rỗng, và chỉ ghi khi tìm thấy tệp thử.

```bash
if [[ -f "${lab:?Hãy mở lại bài theo mục 5}/source/ghichu.txt" ]]; then
    printf 'Phien ban 2\n' > "$lab/source/ghichu.txt"
    cat "$lab/source/ghichu.txt"
else
    printf 'Thiếu source/ghichu.txt. Kiểm tra lại thư mục bài thử theo mục 5.\n'
fi
```

**Đối chiếu sau bước 5.** Sao chép *đường dẫn thư mục* từ thông báo **Đích** của GUI hoặc trường `destination` của CLI. Mỗi lần khôi phục vào đích mặc định sẽ tạo một thư mục mới. Dán đường dẫn được trả về, kể cả khi bạn đã khôi phục nhiều lần.

```bash
read -r -p 'Dán đường dẫn thư mục vừa khôi phục: ' dest
if [[ -n "$dest" && -f "$dest/ghichu.txt" ]]; then
    printf 'Phien ban 1\n' | cmp - "$dest/ghichu.txt" &&
        printf 'Đạt: tệp khôi phục chứa đúng phiên 1.\n'
    printf 'Phien ban 2\n' | cmp - "${lab:?}/source/ghichu.txt" &&
        printf 'Đạt: tệp nguồn vẫn ở phiên 2.\n'
    if [[ -f "$lab/expected/ghichu-v1.txt" ]]; then
        sha256sum "$lab/expected/ghichu-v1.txt" "$dest/ghichu.txt"
    fi
else
    printf 'Chưa tìm thấy ghichu.txt trong thư mục đích vừa nhập.\n'
fi
```

Kết quả mong đợi là **cả hai dòng `Đạt`** và hai giá trị SHA-256 giống nhau nếu có tệp đối chiếu. Các bài tạo theo hướng dẫn cũ có thể thiếu `expected/`, hai lệnh `cmp` vẫn kiểm tra được nội dung mẫu. Xem **Lịch sử → Nhật ký máy này / Nhật ký máy chủ** để tra thao tác, hoặc **Thời hạn lưu → Xem trước chính sách** để xem phiên dự kiến giữ hoặc xóa. CLI tương ứng là `"${cli[@]}" history --local`, `"${cli[@]}" history` và `"${cli[@]}" cleanup --dry-run`.

<a id="sua-tk"></a>

## 7. Khi giao diện báo thiếu Tk

Nếu menu đã cài nhưng chạy `gui` xuất hiện `ImportError: libtk8.6.so: cannot open shared object file`, Python đang thiếu thư viện đồ họa mà Tkinter cần. Trên Arch, gói `tk` cung cấp tệp này. Chạy trong VM bằng Terminal của desktop. [Tệp do gói tk cung cấp](https://archlinux.org/packages/extra/x86_64/tk/files/)

```bash
sudo pacman -Syu tk
python3 -m tkinter
```

Ở bước sửa lỗi này, cho phép `pacman` cài lại `tk` nếu gói đã có. Khi cửa sổ thử Tk mở được, đóng nó và mở lại **LinuxBackupSys** từ menu. Nếu vẫn lỗi, dùng `pacman -Qkk tk` để kiểm tra các tệp của gói và `command -v python3` để xác định Python đang chạy. Thông báo `no display name and no $DISPLAY environment variable` có nghĩa là Tk đã nạp nhưng tiến trình chưa kết nối được với màn hình. Hãy mở Terminal ngay từ phiên desktop của Arch, hoặc dùng cột CLI ở mục 6.

## 8. Các tình huống khác

| Dấu hiệu | Việc cần kiểm tra |
| --- | --- |
| `destination path 'LinuxBackupSys' already exists` hoặc CLI chưa có `gui` | Dùng checkout hiện có ở mục 1, kiểm tra `git branch --show-current` trong checkout. Nhánh có giao diện là `mvp-implementation`. |
| Bấm menu nhưng cửa sổ không xuất hiện, hoặc thấy nguồn của bài khác | Mở từ Terminal bằng `"${cli[@]}" gui` để đọc lỗi. Nếu đã di chuyển checkout hoặc đổi bài, đăng ký lại menu ở mục 4 với đúng `client.conf`. Nếu di chuyển checkout, cập nhật cả `SERVER_PROGRAM` trong cấu hình client. |
| `Connection refused` sau khi bật lại VM | Xem `systemctl status sshd.service` và `journalctl -u sshd.service -b`. Khởi động dịch vụ rồi thử lại lệnh `SSH_OK` ở mục 3. |
| `Permission denied (publickey)` | Kiểm tra `id -un` khớp `SSH_USER`, `ssh-keygen -lf "$lab/demo_key.pub"` đúng khóa đã thêm, `~/.ssh` có quyền 700, `authorized_keys` và `demo_key` có quyền 600. Xem journal của `sshd` khi thử lại. |
| `Host key verification failed` sau khi tạo lại VM | So fingerprint từ `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` trên console với `ssh-keygen -lf "$lab/known_hosts"`. Sau khi xác nhận nguyên nhân đổi khóa và danh tính VM, tạo lại riêng `known_hosts` của bài theo mục 3. |
| `configure --check` đạt nhưng `status` lỗi | Mở **Chi tiết…** hoặc xem stderr của CLI. Kiểm tra lại `SSH_OK`, `CLIENT_ID` trong hai tệp cấu hình, `SERVER_PROGRAM`, `SERVER_CONFIG` và kết quả `init` bằng đúng tài khoản desktop. |
| Lỗi quyền, đường dẫn hoặc trùng kho với nguồn | Dùng thư mục trên hệ thống tệp Linux, đường dẫn tuyệt đối, tránh symlink. `source`, `storage` và `restore` là ba thư mục riêng. `storage` phải thuộc tài khoản chạy server và có quyền 700. |
| `Restore destination already exists` hoặc khôi phục ra phiên 2 | Để trống ô đích để tạo thư mục mới. Đọc lại **Mã phiên** ở hàng đã chọn trước khi bấm **Khôi phục…**. |
| VM tắt giữa lúc sao lưu, kho báo bận hoặc đầy | Xem `status`, lịch sử ở hai phía và `df -h "$lab/storage"`. Chờ thao tác đang chạy kết thúc, xác minh ID đã công bố nếu có rồi mới thử lại. Chỉ các phiên hoàn tất mới xuất hiện trong danh sách để khôi phục. |

Muốn tiếp tục ngày khác, giữ thư mục bài thử và dùng mục 5. Khi kết thúc hẳn, có thể thu hồi khóa demo bằng cách bỏ đúng dòng chứa khóa công khai trong `"$lab/demo_key.pub"` khỏi `~/.ssh/authorized_keys`. Chỉ dừng `sshd.service` nếu chính bạn đã bật dịch vụ để thử và không còn kết nối nào cần nó.

Khi cần kiểm tra qua hai mạng thật, chuyển sang mô hình máy Arch gửi dữ liệu tới kho trên máy Ubuntu. [Ubuntu và Arch qua Tailscale](setup-tailscale.vi.md) · [Phạm vi kiểm thử đã ghi nhận](testing.md)
