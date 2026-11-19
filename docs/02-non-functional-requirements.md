# Tài liệu Yêu cầu Phi chức năng & Ràng buộc Kỹ thuật (Non-Functional Requirements)

**Tên dự án:** Hệ thống Quản lý Chi tiêu Nhóm & Ví Thanh toán Nội bộ

**Ngôn ngữ & Công nghệ chính:** Python, PostgreSQL, Redis

**Tài liệu liên quan:** `docs/01-functional-specs.md`

**Phạm vi tài liệu:** Quy định các tiêu chuẩn kỹ thuật, ngưỡng hiệu năng, ràng buộc bảo mật, chiến lược lưu đệm và quy chuẩn kiểm thử nhằm hiện thực hóa toàn bộ kiến thức trong lộ trình Backend.

---

## 1. Độ tin cậy & Toàn vẹn Dữ liệu (Reliability & Data Integrity)

- **`NFR-01` Chuẩn hóa Cơ sở dữ liệu (Normalization):** Lược đồ cơ sở dữ liệu trên **PostgreSQL** phải đạt chuẩn hóa tối thiểu mức **3NF** (Third Normal Form) nhằm loại bỏ dư thừa dữ liệu và ngăn chặn bất thường khi thêm/sửa/xóa bản ghi.
- **`NFR-02` Quản lý Phiên bản Lược đồ (DB Migrations):** Mọi thay đổi về cấu trúc bảng, cột, khóa ngoại và chỉ mục bắt buộc phải được quản lý thông qua công cụ **DB Migrations** (như Alembic) lưu trong mã nguồn. Nghiêm cấm việc chỉnh sửa thủ công trực tiếp trên cơ sở dữ liệu bằng giao diện quản trị.
- **`NFR-03` Tuân thủ ACID & Giao dịch Nguyên tử (Transactions):** Mọi nghiệp vụ làm thay đổi số dư ví (nạp tiền, chuyển tiền thanh toán nợ) và ghi nhận sổ cái bắt buộc phải thực thi trong một **Database Transaction** tuân thủ đầy đủ 4 tính chất **ACID** (Atomicity, Consistency, Isolation, Durability). Sử dụng cơ chế khóa bi quan (`SELECT ... FOR UPDATE`) trên bản ghi ví để chống tranh chấp dữ liệu (race condition) khi có nhiều giao dịch đồng thời.
- **`NFR-04` Độ chính xác Số học Tài chính:** Toàn bộ các trường lưu trữ tiền tệ và tỷ lệ phần trăm phải sử dụng kiểu dữ liệu chính xác (`NUMERIC(15, 2)` trong **PostgreSQL** và `decimal.Decimal` trong **Python**). Nghiêm cấm sử dụng kiểu số thực dấu phẩy động (`float`) ở bất kỳ tầng xử lý nào.

---

## 2. Hiệu năng & Tối ưu hóa Truy vấn (Performance & Query Optimization)

- **`NFR-05` Tối ưu Chỉ mục & Phân tích Hiệu năng Truy vấn:**
  - API lọc và phân trang lịch sử chi tiêu (`FR-08`) phải đạt thời gian phản hồi dưới **100ms** (ở mức phân vị p95) khi bảng dữ liệu đạt quy mô từ `200.000` đến `500.000` bản ghi.
  - Bắt buộc thiết kế **DB Indexes** (Single Index và Composite Index) phù hợp cho các cột thường xuyên xuất hiện trong mệnh đề `WHERE`, `JOIN` và `ORDER BY`.
  - Mọi truy vấn phức tạp phải được kiểm chứng kế hoạch thực thi bằng lệnh `EXPLAIN ANALYZE` của **PostgreSQL** để đảm bảo hệ thống sử dụng `Index Scan` thay vì `Seq Scan` trên các bảng lớn.
- **`NFR-06` Sử dụng ORM có Kiểm soát & Loại bỏ N+1 Problem:**
  - Sử dụng **ORM** (SQLAlchemy) cho các thao tác nghiệp vụ tiêu chuẩn, nhưng phải tuân thủ nghiêm ngặt giới hạn của ORM.
  - Các endpoint truy vấn danh sách lồng nhau (như lấy danh sách khoản chi kèm thông tin người trả tiền và danh sách chia tiền) phải áp dụng kỹ thuật Eager Loading (`selectinload` hoặc `joinedload`) để triệt tiêu hoàn toàn lỗi **N+1 Problem**.
  - Đối với các truy vấn thống kê tổng hợp nhiều tầng mà ORM sinh ra mã **SQL** kém tối ưu, hệ thống ưu tiên sử dụng câu lệnh **SQL** thuần (Raw SQL / Core Expression) để đảm bảo hiệu năng.
- **`NFR-07` Hiệu năng Công cụ Dòng lệnh (CLI Bulk Processing):** Ứng dụng **CLI** nạp dữ liệu giả lập (`FR-14`) phải sử dụng kỹ thuật chèn theo lô (bulk insert / batch processing) để nạp `200.000` bản ghi vào **PostgreSQL** trong thời gian dưới **30 giây**, tránh tràn bộ nhớ RAM.

---

## 3. Chiến lược Lưu đệm (Caching Strategy)

- **`NFR-08` Lưu đệm Phía Máy chủ với Redis:**
  - Các báo cáo thống kê chi tiêu theo tháng (`FR-12`) sử dụng nhiều phép tính gộp **SQL** (`SUM`, `GROUP BY`) phải được lưu kết quả trên **Redis** dưới định dạng JSON với thời gian sống (**TTL**) mặc định là **15 phút**.
  - Áp dụng chiến lược **Cache-Aside (Lazy Loading)** kết hợp **Explicit Cache Invalidation**: hệ thống tự động xóa khóa cache tương ứng ngay khi có giao dịch tạo mới khoản chi trong nhóm để đảm bảo tính nhất quán dữ liệu.
- **`NFR-09` Lưu đệm Giao thức HTTP (HTTP Caching):**
  - Các endpoint cung cấp dữ liệu tham chiếu ít thay đổi (như danh sách danh mục chi tiêu chuẩn `FR-05`) bắt buộc phải trả về các HTTP header chuẩn gồm `Cache-Control` (ví dụ: `public, max-age=3600`) và `ETag`.
  - Hệ thống phải hỗ trợ xử lý header `If-None-Match` từ phía client và trả về mã trạng thái `304 Not Modified` (không kèm payload) nếu dữ liệu chưa có sự thay đổi.

---

## 4. Bảo mật & Chuẩn Giao tiếp API (Security & API Standards)

- **`NFR-10` Chuẩn thiết kế RESTful JSON APIs:**
  - Toàn bộ API phải tuân thủ nguyên tắc kiến trúc **REST**, sử dụng đúng ngữ nghĩa của các phương thức HTTP (`GET`, `POST`, `PATCH`, `DELETE`) và định dạng trao đổi dữ liệu thống nhất là **JSON** (`Content-Type: application/json`).
  - Mọi phản hồi lỗi đều phải trả về theo một cấu trúc JSON chuẩn hóa bọc trong object `"error"` (gồm `code`, `message`, `details`) đi kèm mã trạng thái HTTP chính xác (`400`, `401`, `403`, `404`, `409`, `422`, `500`).
- **`NFR-11` Cơ chế Xác thực JWT & Bảo mật Thông tin Nhạy cảm:**
  - Xác thực người dùng bằng **JWT** (JSON Web Token) theo cơ chế phi trạng thái (stateless): `Access Token` có thời hạn ngắn (**15–30 phút**) để giảm rủi ro lộ lọt, kết hợp `Refresh Token` có thời hạn dài (**7 ngày**) để duy trì phiên đăng nhập.
  - Mật khẩu người dùng tuyệt đối không lưu dưới dạng văn bản thuần (plaintext) và không xuất hiện trong log hệ thống; mật khẩu phải được băm bằng thuật toán một chiều an toàn (`bcrypt` hoặc `argon2`) kèm chuỗi muối ngẫu nhiên (salt).
  - Áp dụng kiểm tra phân quyền ở tầng dịch vụ (Service Layer) cho mọi yêu cầu truy xuất tài nguyên nhóm nhằm ngăn chặn lỗ hổng truy cập trái phép qua ID (IDOR).

---

## 5. Chất lượng Mã nguồn & Kiểm thử Tự động (Code Quality & Automated Testing)

- **`NFR-12` Quy trình Quản lý Mã nguồn với Git & GitHub:**
  - Toàn bộ mã nguồn được lưu trữ và quản lý phiên bản trên **GitHub**.
  - Áp dụng mô hình phân nhánh theo tính năng (`main` luôn giữ trạng thái ổn định; phát triển trên các nhánh `feat/<ten-tinh-nang>` hoặc `fix/<ten-loi>`), viết thông điệp commit rõ ràng và thực hiện ghép mã thông qua Pull Request.
- **`NFR-13` Tiêu chuẩn Kiểm thử Tự động (Automated Testing):**
  - Dự án bắt buộc phải xây dựng bộ kiểm thử tự động (`pytest`) đạt độ phủ mã nguồn tối thiểu **80%** cho tầng nghiệp vụ (`services/`) và bao phủ đầy đủ 3 cấp độ kiểm thử:
    - **Unit Testing:** Kiểm thử độc lập (không kết nối DB/Redis) toàn bộ các hàm tính toán thuần túy, đặc biệt là logic chia tiền và xử lý làm tròn số lẻ (`BR-02`).
    - **Integration Testing:** Kiểm thử tích hợp với **PostgreSQL** và **Redis** thực tế (chạy qua Docker) để xác minh cơ chế rollback của **ACID Transaction** khi thiếu số dư, ràng buộc khóa ngoại và cơ chế làm mới cache trên Redis.
    - **Functional Testing:** Kiểm thử toàn trình (End-to-End API) mô phỏng hành vi người dùng thực qua HTTP request từ khâu đăng ký, lấy **JWT**, tạo nhóm, thêm khoản chi cho đến thanh toán nợ và đối chiếu số dư cuối cùng.

---

## 6. Ràng buộc Môi trường & Khả năng Vận hành (Environment & Operability)

- **`NFR-14` Đóng gói Hạ tầng Cục bộ:** Các dịch vụ phụ thuộc gồm **PostgreSQL** và **Redis** phải được cấu hình sẵn trong tệp `docker-compose.yml` để có thể khởi tạo môi trường phát triển và kiểm thử đồng nhất chỉ bằng một câu lệnh.
- **`NFR-15` Tách biệt Cấu hình Môi trường:** Toàn bộ thông số kết nối cơ sở dữ liệu, chuỗi bí mật ký **JWT** (`JWT_SECRET_KEY`), cấu hình **Redis** và chế độ ghi log **SQL** phải được nạp từ biến môi trường (`.env`), đi kèm tệp mẫu `.env.example` trên repository.
- **`NFR-16` Khả năng Giám sát Truy vấn (Observability):** Hệ thống phải hỗ trợ bật/tắt chế độ xuất câu lệnh **SQL** thô ra console trong môi trường phát triển để lập trình viên dễ dàng phát hiện lỗi **N+1 Problem** và đo thời gian thực thi từng truy vấn.

---

## 7. Bảng Tổng hợp Cam kết Kỹ thuật (Technical Metrics Matrix)

| Mã ràng buộc       | Hạng mục kỹ thuật            | Chỉ số / Tiêu chuẩn cam kết                                     | Phương pháp kiểm chứng                                          |
| ------------------ | ---------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------- |
| `NFR-03`, `NFR-04` | Toàn vẹn giao dịch & Tiền tệ | 100% dùng `NUMERIC(15,2)` / `Decimal`; Rollback tức thì khi lỗi | Integration Test với lỗi giả lập giữa Transaction               |
| `NFR-05`           | Tốc độ truy vấn dữ liệu lớn  | `< 100ms` (p95) trên bảng `200.000+` dòng                       | Kiểm tra `EXPLAIN ANALYZE` trên PostgreSQL                      |
| `NFR-06`           | Kiểm soát ORM                | `0` lỗi N+1 trên các endpoint danh sách                         | Bật SQL Echo Log & đếm số lượng query trên mỗi request          |
| `NFR-08`, `NFR-09` | Hiệu quả Caching             | Redis TTL `15 phút`; HTTP `304 Not Modified` với `ETag`         | Kiểm tra Cache Hit/Miss trên Redis và HTTP Response Headers     |
| `NFR-11`           | Bảo mật xác thực             | JWT Access (`15-30m`), Refresh (`7d`), Hash `bcrypt`/`argon2`   | Functional Test các kịch bản token hết hạn & truy cập trái phép |
| `NFR-13`           | Độ phủ kiểm thử tự động      | `>= 80%` coverage; đủ Unit, Integration & Functional Test       | Chạy báo cáo `pytest --cov` trước khi merge Pull Request        |
