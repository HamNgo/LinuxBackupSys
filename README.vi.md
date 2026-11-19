# LinuxBackupSys — Dịch vụ sao lưu và khôi phục tập trung trên Linux

[English](README.md)

LinuxBackupSys dùng Bash, Python và các công cụ Linux để sao lưu file và thư mục từ máy khách sang máy chủ trong mạng LAN. Mỗi lần sao lưu thành công tạo một bản theo phiên (*snapshot*) để có thể khôi phục dữ liệu cũ.

> **Trạng thái:** Phiên bản MVP đã triển khai sao lưu qua rsync/SSH, snapshot theo phiên, xác minh SHA-256, khôi phục file và thư mục, dọn bản hết hạn, lịch sử JSONL, cấu hình TOML và các tệp systemd. Kiểm thử cục bộ trên WSL Ubuntu 26.04.1 ghi nhận 42 ca đạt và 1 ca SSH được bỏ qua. Việc tích hợp qua LAN và chạy theo lịch trên hai máy đích còn cần xác nhận. [Kết quả kiểm thử](docs/testing.md)

Bắt đầu với [hướng dẫn triển khai bằng tiếng Việt](docs/setup.vi.md). Tài liệu đi kèm gồm [cấu hình và CLI](docs/configuration.md), [kiến trúc](docs/architecture.md) và [kịch bản demo](docs/demo.md).

Nếu máy chủ Ubuntu và máy khách Arch ở hai mạng Internet khác nhau, dùng [hướng dẫn cài Tailscale và kiểm thử Ubuntu–Arch](docs/setup-tailscale.vi.md).

```bash
# Chạy từ thư mục gốc của dự án trên Linux
bash backup-manager.sh --help
bash tests/run.sh
# Tạo mẫu cấu hình ở một đường dẫn mới rồi chỉnh các giá trị minh họa
bash backup-manager.sh configure --output /absolute/new-backup.conf
```

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Mục tiêu](#2-mục-tiêu)
3. [Kiến trúc hệ thống](#3-kiến-trúc-hệ-thống)
4. [Tính năng](#4-tính-năng)
5. [Công nghệ sử dụng](#5-công-nghệ-sử-dụng)
6. [Cấu trúc dự án](#6-cấu-trúc-dự-án)
7. [Lệnh quản lý](#7-lệnh-quản-lý)
8. [Phân công nhóm](#8-phân-công-nhóm)
9. [Lộ trình hai tuần](#9-lộ-trình-hai-tuần)
10. [Mốc bàn giao](#10-mốc-bàn-giao)
11. [Kịch bản demo](#11-kịch-bản-demo)
12. [Bảo mật và độ tin cậy](#12-bảo-mật-và-độ-tin-cậy)
13. [Phạm vi và hướng phát triển](#13-phạm-vi-và-hướng-phát-triển)
14. [Danh sách kiểm tra](#14-danh-sách-kiểm-tra)

## 1. Tổng quan

Máy khách gửi các file và thư mục được chọn đến một máy chủ riêng. Máy chủ lưu nhiều phiên sao lưu, kiểm tra tính toàn vẹn, quản lý thời hạn lưu và cung cấp dữ liệu khi máy khách yêu cầu khôi phục. Dự án minh họa quản trị Linux, tự động hóa và phục hồi dữ liệu qua mạng.

## 2. Mục tiêu

- Truyền dữ liệu qua SSH bằng tài khoản sao lưu riêng.
- Lưu từng phiên và khôi phục file hoặc thư mục từ một phiên cũ.
- Lập lịch sao lưu định kỳ bằng systemd timer.
- Xác minh tính toàn vẹn bằng SHA-256 và dọn snapshot hết hạn theo cấu hình.
- Ghi kết quả thao tác, tra cứu lịch sử và quản lý dịch vụ qua một CLI thống nhất.

## 3. Kiến trúc hệ thống

Hai máy kết nối qua LAN. Máy B chủ động mở kết nối SSH đến máy A để gửi dữ liệu và yêu cầu khôi phục.

```text
Máy B — Máy khách                         Máy A — Máy chủ
Chọn nguồn, chạy lịch      ── rsync/SSH ─► Nhận dữ liệu, lưu snapshot
Yêu cầu khôi phục         ◄── rsync/SSH ── Cung cấp file từ phiên đã chọn
Kiểm tra bản khôi phục                    Quản lý retention và lịch sử
```

Máy A chạy OpenSSH Server và sở hữu kho snapshot. Mỗi lần sao lưu được nhận vào vùng tạm (*staging*) riêng rồi mới công bố sau khi truyền và các kiểm tra bắt buộc thành công. Máy B quản lý cấu hình nguồn, khóa SSH, nhật ký cục bộ và thư mục nhận dữ liệu khôi phục.

Hướng dẫn chính dùng Ubuntu 24.04 LTS cho cả hai máy. Nếu có một máy Ubuntu và một máy Arch Linux, có thể dùng Ubuntu làm máy A và Arch làm máy B. Trên Arch, cài các gói `python`, `rsync` và `openssh`, rồi dùng cấu hình máy B với đúng tài khoản và đường dẫn. Cặp Ubuntu–Arch còn cần kiểm thử trực tiếp. [Hướng dẫn triển khai](docs/setup.vi.md)

## 4. Tính năng

| Tính năng | Cách hoạt động |
| --- | --- |
| Kết nối và xác thực | SSH sử dụng khóa của máy B và tài khoản `backup` riêng trên máy A. Client xác minh khóa máy chủ trước khi kết nối. |
| Kho sao lưu tập trung | Snapshot được lưu dưới thư mục dành riêng cho client. Mỗi phiên là một bản sao đầy đủ và độc lập. |
| Lịch chạy | systemd timer trên máy B gọi cùng luồng với lệnh chạy tay. Lịch mẫu chạy mỗi ngày lúc 02:00 UTC, tức 09:00 giờ Việt Nam, với độ trễ tối đa 5 phút. |
| Khôi phục | Chọn snapshot đã hoàn tất rồi khôi phục một file, một thư mục hoặc toàn bộ nội dung vào đích mới. |
| Kiểm tra tính toàn vẹn | Manifest SHA-256 giúp phát hiện file thiếu hoặc thay đổi. Bản khôi phục được đối chiếu với manifest của snapshot đã chọn. |
| Thời hạn lưu (retention) | Thời hạn tính theo từng khoảng 24 giờ từ giờ hoàn tất UTC. Luôn giữ snapshot thành công mới nhất. `cleanup --dry-run` hiển thị ứng viên trước khi áp dụng. |
| Nhật ký và lịch sử | JSONL lưu thời gian, thao tác, kết quả và lỗi. `history` xem lịch sử server, `history --local` xem lịch sử client. |
| Quản lý cấu hình | `configure` tạo mẫu hoặc kiểm tra TOML. Kho lưu và retention cấu hình trên server. Nguồn dữ liệu và SSH cấu hình trên client. |

Ví dụ `/etc/linux-backup/backup.conf` trên máy B. Thay tên máy, tài khoản và đường dẫn theo môi trường triển khai.

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

`CLIENT_ID` cần khớp ở cả hai máy. Chỉnh thời hạn lưu bằng `RETENTION_DAYS` trên máy A và lịch chạy qua `OnCalendar` trên máy B. [Mẫu client](client/client.conf.example) · [Mẫu server](server/server.conf.example) · [systemd timer](deploy/linux-backup.timer)

## 5. Công nghệ sử dụng

| Công nghệ | Vai trò |
| --- | --- |
| Ubuntu 24.04 LTS | Môi trường triển khai trong hướng dẫn chính |
| OpenSSH và rsync | Xác thực, truyền dữ liệu và giao tiếp giữa hai máy |
| Bash | Các lệnh quản lý, cài mã và khởi chạy job theo lịch |
| Python 3.11+ | Xử lý cấu hình, đường dẫn, manifest và logic lưu snapshot bằng thư viện chuẩn |
| JSON và JSONL | Metadata snapshot và lịch sử thao tác |
| SHA-256 | Kiểm tra nội dung file qua `hashlib`. Có thể dùng `sha256sum` khi demo |
| systemd | Quản lý service và lịch sao lưu |
| Git | Quản lý phiên bản mã nguồn |

## 6. Cấu trúc dự án

```text
LinuxBackupSys/
├── backup-manager.sh          # CLI quản lý chính
├── client/                    # Backup, restore, kết nối SSH và mẫu cấu hình client
├── server/                    # Kho snapshot, retention, tiến trình nhận và mẫu server
├── common/                    # CLI, cấu hình, kiểm tra đường dẫn, manifest và giao thức
├── deploy/                    # Script cài mã và các tệp systemd
├── tests/                     # Kiểm thử bằng dữ liệu tạm, rsync thật và SSH tùy chọn
├── docs/                      # Kiến trúc, cấu hình, triển khai, kiểm thử và demo
├── .github/workflows/test.yml # Cấu hình CI cho Ubuntu 24.04
├── README.md                  # Bản tiếng Anh
└── README.vi.md               # Bản tiếng Việt
```

Kho sao lưu, file cấu hình thực tế và nhật ký vận hành được lưu bên ngoài kho Git.

## 7. Lệnh quản lý

Chạy trên máy B sau khi cấu hình. Thay `SNAPSHOT_ID` bằng giá trị `snapshot_id` do `backup` trả về hoặc lấy từ `status`.

```bash
bash backup-manager.sh --config /etc/linux-backup/backup.conf configure --check
bash backup-manager.sh --config /etc/linux-backup/backup.conf status
bash backup-manager.sh --config /etc/linux-backup/backup.conf backup
bash backup-manager.sh --config /etc/linux-backup/backup.conf verify SNAPSHOT_ID
bash backup-manager.sh --config /etc/linux-backup/backup.conf restore SNAPSHOT_ID --path 'reports/report.txt'
bash backup-manager.sh --config /etc/linux-backup/backup.conf history --limit 20
bash backup-manager.sh --config /etc/linux-backup/backup.conf cleanup --dry-run
# Áp dụng sau khi đã xem danh sách ứng viên
bash backup-manager.sh --config /etc/linux-backup/backup.conf cleanup --apply
```

Các lệnh xuất JSON và trả mã khác `0` khi gặp lỗi. Bỏ `--path` để khôi phục toàn bộ snapshot. Theo mặc định, lệnh tạo một thư mục mới trong `RESTORE_ROOT`. Nếu chỉ định `--destination`, hãy chọn một đường dẫn tuyệt đối chưa tồn tại với thư mục cha có sẵn. [Chi tiết tham số và mã thoát](docs/configuration.md)

## 8. Phân công nhóm

| Vai trò | Công việc |
| --- | --- |
| Thành viên 1 — Máy chủ và hạ tầng | Chuẩn bị máy A, tài khoản và SSH, thiết lập quyền kho lưu, quản lý snapshot, retention và nhật ký server. |
| Thành viên 2 — Máy khách và khôi phục | Chuẩn bị máy B và khóa SSH, cấu hình nguồn, chạy backup và restore, xác minh SHA-256 và tra cứu lịch sử. |
| Cả nhóm | Thống nhất cấu hình và giao diện, kiểm thử LAN và lỗi, viết báo cáo tiếng Anh, chuẩn bị slide và tập demo. |

## 9. Lộ trình hai tuần

Đây là kế hoạch ban đầu của dự án. Mục tiêu là hoàn thành luồng backup và restore giữa hai máy vào **ngày 10**, sau đó tập trung kiểm thử và chuẩn bị trình bày.

| Ngày | Công việc | Kết quả dự kiến |
| --- | --- | --- |
| 1 | Phân vai hai máy, kiểm tra công cụ, thống nhất cấu trúc kho và tên snapshot, tạo repo và ghi kiến trúc. | Repo và kiến trúc đã thống nhất. |
| 2 | Bật OpenSSH trên máy A, tạo tài khoản và kho sao lưu, thiết lập khóa từ máy B. | Kết nối SSH hoạt động. |
| 3 | Chọn dữ liệu thử nhỏ, truyền qua rsync/SSH, đối chiếu nội dung và xử lý lỗi truyền. | Chạy được backup thủ công. |
| 4 | Tạo thư mục snapshot riêng, đặt ID theo thời gian, sửa file rồi chạy phiên thứ hai. Khảo sát tùy chọn `--link-dest`. | Phân biệt được nhiều phiên sao lưu. |
| 5 | Tạo cấu hình hai máy, ghi nhật ký, thiết lập và kiểm tra lịch systemd. | Job theo lịch có cấu hình và nhật ký. |
| 6 | Tạo và so sánh SHA-256, thử danh sách hết hạn và dọn dữ liệu mẫu. | Có xác minh và chính sách thời hạn lưu. |
| 7 | Khôi phục file và thư mục từ phiên đã chọn vào đích riêng rồi so sánh với dữ liệu gốc. | Khôi phục được phiên cũ. |
| 8 | Ghi ID, thời gian, kết quả và đường dẫn liên quan, bổ sung lệnh xem lịch sử. Cân nhắc SQLite nếu cần. | Tra cứu được các thao tác trước đó. |
| 9 | Gộp lệnh vào CLI, kiểm tra cấu hình, quyền, tham số và thông báo lỗi. | Dùng chung một lệnh quản lý. |
| 10 | Tích hợp hai máy, sửa và xóa dữ liệu mẫu, khôi phục phiên cũ và xử lý lỗi tích hợp. | Hoàn thành luồng chính trên cặp máy đích. |
| 11 | Thử lỗi mạng, xác thực SSH, đường dẫn sai, checksum sai, bản hết hạn và restore phiên cũ. Ghi kết quả mong đợi và thực tế. | Có kết quả kiểm thử và danh sách vấn đề. |
| 12 | Viết báo cáo tiếng Anh và chuẩn bị slide. | Có bản nháp báo cáo và bài trình bày. |
| 13 | Kiểm tra lại sau khi khởi động lại, tập demo, kiểm tra lịch và chụp màn hình làm bằng chứng. | Có quy trình demo lặp lại được. |
| 14 | Trình bày kiến trúc, chạy demo, giải thích kết quả và nộp tài liệu. | Hoàn tất bài trình bày. |

Báo cáo có thể trình bày mục tiêu, công nghệ, yêu cầu và kiến trúc, cách cài đặt, cơ chế snapshot và khôi phục, SHA-256 và retention, kết quả thử nghiệm, giới hạn và hướng phát triển. Thành viên 1 trình bày hạ tầng và snapshot, thành viên 2 trình bày client, khôi phục và kiểm thử. Cả hai cùng demo và trả lời câu hỏi.

## 10. Mốc bàn giao

| Thời điểm | Kết quả dự kiến |
| --- | --- |
| Cuối ngày 3 | Hai máy kết nối và chạy được backup cơ bản. |
| Cuối ngày 7 | Tạo nhiều phiên, kiểm tra SHA-256, thử retention và khôi phục. |
| Cuối ngày 10 | Hoàn tất tích hợp từ đầu đến cuối trên hai máy. |
| Cuối ngày 11 | Hoàn thành kiểm thử lỗi và độ tin cậy. |
| Cuối ngày 13 | Sẵn sàng báo cáo và demo. |
| Ngày 14 | Trình bày và nộp bài. |

## 11. Kịch bản demo

Dành 10–15 phút và dùng dữ liệu thử riêng cho các bước sửa hoặc xóa.

1. Giới thiệu máy khách và thư mục nguồn thử nghiệm.
2. Chạy backup lần đầu và ghi ID của phiên thứ nhất.
3. Sửa một file trên máy khách rồi chạy backup lần hai để tạo phiên mới.
4. Xóa một thư mục thử trên máy khách. Khôi phục thư mục đó từ phiên thứ nhất sang đích mới.
5. So sánh SHA-256 của file khôi phục với bản mẫu đã lưu riêng trước khi sửa hoặc xóa.
6. Xem lịch sử thao tác, cấu hình thời hạn lưu và kết quả `cleanup --dry-run`. Nếu có snapshot thử đã hết hạn, minh họa việc áp dụng cleanup trên kho thử.

[Quy trình demo chi tiết](docs/demo.md)

## 12. Bảo mật và độ tin cậy

- Dùng tài khoản sao lưu riêng trên máy chủ, xác thực bằng khóa SSH và đối chiếu fingerprint qua kênh đáng tin cậy.
- Giới hạn quyền ghi vào kho sao lưu. Dữ liệu đang truyền nằm trong vùng staging riêng và được công bố sau khi các bước bắt buộc thành công.
- Khôi phục vào thư mục mới. Các thao tác backup, restore và cleanup phối hợp qua khóa phía máy chủ.
- Kiểm tra nhật ký khi thao tác thất bại. Giữ đồng hồ hai máy đồng bộ để đọc đúng thời gian snapshot và lịch sử.
- Thử khôi phục định kỳ. SHA-256 xác minh nội dung theo manifest. Với dữ liệu của ứng dụng đang ghi, hãy chuẩn bị bản xuất nhất quán trước khi sao lưu.

## 13. Phạm vi và hướng phát triển

MVP phục vụ một máy khách và một máy chủ, sao lưu và khôi phục file thường cùng thư mục. Symlink và file đặc biệt bị từ chối. Mỗi snapshot lưu một bản sao đầy đủ, vì vậy dung lượng tăng theo số phiên được giữ.

Các hạng mục tùy chọn gồm dùng hard link qua `--link-dest`, lưu lịch sử bằng SQLite, giao diện web, thông báo lỗi, nhiều máy khách, mã hóa kho lưu, sao lưu ngoài LAN và kiểm soát truy cập nâng cao. Phục hồi toàn bộ hệ điều hành nằm ngoài phạm vi của MVP.

## 14. Danh sách kiểm tra

### Hạ tầng

- [ ] Chọn máy A làm server, máy B làm client và kiểm tra kết nối LAN.
- [ ] Cài Python 3.11+, Bash, OpenSSH và rsync. Kiểm tra SSH và rsync trên cả hai máy.
- [ ] Thiết lập xác thực bằng khóa và tạo kho sao lưu trên máy A.
- [ ] Chạy thử service và bật lịch systemd trên máy B.
- [x] Tạo repo và các thư mục dự án.

### Sao lưu và khôi phục

- [x] Triển khai truyền dữ liệu, snapshot theo phiên, nhật ký và lịch sử.
- [x] Triển khai restore file và thư mục, SHA-256 và cleanup theo thời hạn.
- [x] Thử khôi phục phiên cũ với dữ liệu tạm cục bộ. Kiểm tra từ chối đích đã có và bảo toàn dữ liệu nguồn.
- [ ] Kiểm thử lỗi mạng và xác thực SSH trong môi trường triển khai.

### Cấu hình và nộp bài

- [x] Tạo mẫu cấu hình, kiểm tra TOML và cung cấp CLI thống nhất.
- [ ] Hoàn tất kiểm thử tích hợp trên hai máy, lưu ảnh chụp và kết quả thực tế.
- [ ] Hoàn thành báo cáo tiếng Anh và slide. Tập demo trước khi trình bày.
