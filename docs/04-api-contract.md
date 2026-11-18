# Tài liệu Đặc tả Hợp đồng API (API Contract)

**Tên dự án:** Hệ thống Quản lý Chi tiêu Nhóm & Ví Thanh toán Nội bộ

**Phiên bản API:** `v1`

**Giao thức & Định dạng:** RESTful HTTP/1.1+, JSON (`application/json`)

**Tài liệu liên quan:** `docs/01-functional-specs.md`, `docs/02-non-functional-requirements.md`

---

## 1. Quy ước Chung & Chuẩn Giao tiếp (General Conventions)

- **Base URL:** `http://localhost:8000/api/v1`
- **Chuẩn thiết kế RESTful JSON APIs:** Tài nguyên được định danh bằng danh từ số nhiều (`/groups`, `/expenses`, `/wallets`) và thao tác thông qua đúng ngữ nghĩa của các phương thức HTTP (`GET`, `POST`, `PATCH`, `DELETE`). Toàn bộ dữ liệu trao đổi sử dụng định dạng **JSON**.
- **Xác thực bằng JWT (Authentication):** Các endpoint có gắn nhãn `[Auth: Bearer]` yêu cầu client gửi kèm Access Token trong header:

  ```http
  Authorization: Bearer <access_token>
  ```

- **Định dạng Dữ liệu Tài chính & Thời gian:**
  - **Tiền tệ:** Truyền tải dưới dạng chuỗi số thập phân có 2 chữ số sau dấu phẩy (ví dụ: `"150000.00"`) để ánh xạ chính xác với kiểu `Decimal` trong Python và `NUMERIC(15, 2)` trong PostgreSQL, tránh sai số làm tròn của kiểu số thực trong JSON.
  - **Thời gian:** Tuân thủ chuẩn quốc tế ISO 8601 ở múi giờ UTC (ví dụ: `"2026-11-18T15:30:00Z"`).
- **Quy chuẩn Phân trang (Pagination):** Các API trả về danh sách hỗ trợ tham số truy vấn `page` (mặc định `1`) và `limit` (mặc định `20`, tối đa `100`) với cấu trúc phản hồi thống nhất:

  ```json
  {
    "items": [],
    "meta": {
      "page": 1,
      "limit": 20,
      "total_items": 250,
      "total_pages": 13
    }
  }
  ```

---

## 2. Chuẩn Phản hồi Lỗi & Mã Trạng thái HTTP

### Cấu trúc JSON Phản hồi Lỗi Thống nhất

Mọi lỗi phát sinh từ tầng xác thực, kiểm tra dữ liệu đầu vào hoặc quy tắc nghiệp vụ đều trả về cùng một cấu trúc:

```json
{
  "error": {
    "code": "INSUFFICIENT_WALLET_BALANCE",
    "message": "Số dư ví hiện tại không đủ để thực hiện giao dịch thanh toán nợ.",
    "details": {
      "current_balance": "50000.00",
      "required_amount": "120000.00"
    }
  }
}
```

### Bảng Mã Trạng thái HTTP Sử dụng

| Mã HTTP                    | Ý nghĩa                 | Tình huống áp dụng trong hệ thống                                                       |
| -------------------------- | ----------------------- | --------------------------------------------------------------------------------------- |
| `200 OK`                   | Thành công              | Lấy dữ liệu, cập nhật tài nguyên, đăng nhập hoặc thanh toán nợ thành công.              |
| `201 Created`              | Khởi tạo thành công     | Đăng ký tài khoản mới, tạo nhóm, hoặc tạo khoản chi mới.                                |
| `204 No Content`           | Thành công (không body) | Xóa thành viên khỏi nhóm hoặc xóa khoản chi thành công.                                 |
| `304 Not Modified`         | Dữ liệu chưa thay đổi   | Phản hồi cho **HTTP Caching** khi header `If-None-Match` khớp với `ETag` hiện tại.      |
| `400 Bad Request`          | Lỗi nghiệp vụ           | Số dư ví không đủ, thành viên còn nợ chưa thể rời nhóm, hoặc tổng chia tiền không khớp. |
| `401 Unauthorized`         | Chưa xác thực           | Thiếu JWT, token sai chữ ký hoặc Access Token đã hết hạn.                               |
| `403 Forbidden`            | Không có quyền truy cập | Người dùng truy cập dữ liệu của nhóm mà họ không phải là thành viên.                    |
| `404 Not Found`            | Không tìm thấy          | ID của nhóm, khoản chi hoặc người dùng không tồn tại.                                   |
| `409 Conflict`             | Xung đột dữ liệu        | Email đăng ký đã tồn tại hoặc thành viên đã có mặt trong nhóm.                          |
| `422 Unprocessable Entity` | Sai định dạng đầu vào   | Thiếu trường bắt buộc, số tiền âm (`<= 0`) hoặc sai định dạng email/ngày tháng.         |

---

## 3. Đặc tả Chi tiết Các Nhóm Endpoints

### Module 1: Xác thực & Tài khoản (`Auth & Users`)

#### `1.1. Đăng ký tài khoản & Khởi tạo ví`

- **Endpoint:** `POST /api/v1/auth/register` | `[Auth: Public]`
- **Mục đích:** Tạo người dùng mới và tự động khởi tạo ví cá nhân với số dư `0.00` bên trong một **Database Transaction**.
- **Request Body:**

  ```json
  {
    "email": "guest@example.com",
    "password": "StrongPassword@123",
    "full_name": "Nguyễn Văn A"
  }
  ```

- **Response (`201 Created`):**

  ```json
  {
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "email": "guest@example.com",
      "full_name": "Nguyễn Văn A",
      "created_at": "2026-11-18T10:00:00Z"
    },
    "wallet": {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "balance": "0.00",
      "currency": "VND"
    }
  }
  ```

#### `1.2. Đăng nhập & Cấp phát JWT`

- **Endpoint:** `POST /api/v1/auth/login` | `[Auth: Public]`
- **Mục đích:** Xác thực thông tin đăng nhập và trả về cặp **JWT** (`access_token` và `refresh_token`).
- **Request Body:**

  ```json
  {
    "email": "guest@example.com",
    "password": "StrongPassword@123"
  }
  ```

- **Response (`200 OK`):**

  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 1800
  }
  ```

#### `1.3. Làm mới Access Token`

- **Endpoint:** `POST /api/v1/auth/refresh` | `[Auth: Public]`
- **Request Body:**

  ```json
  {
    "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
  }
  ```

- **Response (`200 OK`):** Trả về cặp `access_token` và `refresh_token` mới.

---

### Module 2: Dữ liệu Danh mục & HTTP Caching (`Reference Data`)

#### `2.1. Lấy danh sách danh mục chi tiêu chuẩn`

- **Endpoint:** `GET /api/v1/categories` | `[Auth: Bearer]`
- **Mục đích:** Thực hành **HTTP Caching** ở tầng giao thức mạng cho dữ liệu ít thay đổi.
- **Request Headers (tùy chọn từ client ở các lần gọi sau):**

  ```http
  If-None-Match: "cat-v1-8f9e2b1a"
  ```

- **Response Headers (`200 OK`):**

  ```http
  Cache-Control: public, max-age=3600
  ETag: "cat-v1-8f9e2b1a"
  ```

- **Response Body (`200 OK`):**

  ```json
  {
    "items": [
      { "id": 1, "code": "FOOD", "name": "Ăn uống" },
      { "id": 2, "code": "TRANSPORT", "name": "Di chuyển" },
      { "id": 3, "code": "ACCOMMODATION", "name": "Lưu trú" },
      { "id": 4, "code": "UTILITIES", "name": "Hóa đơn & Tiện ích" },
      { "id": 5, "code": "ENTERTAINMENT", "name": "Giải trí" }
    ]
  }
  ```

- **Response (`304 Not Modified`):** Trả về header rỗng (không body) nếu `If-None-Match` trùng với `ETag` của máy chủ.

---

### Module 3: Quản lý Nhóm & Thành viên (`Groups`)

#### `3.1. Tạo nhóm chi tiêu mới`

- **Endpoint:** `POST /api/v1/groups` | `[Auth: Bearer]`
- **Request Body:**

  ```json
  {
    "name": "Chuyến đi Đà Lạt 2026",
    "description": "Quỹ chia tiền ăn uống và xe cộ",
    "currency": "VND"
  }
  ```

- **Response (`201 Created`):** Trả về thông tin nhóm mới tạo kèm vai trò `ADMIN` của người khởi tạo.

#### `3.2. Thêm thành viên vào nhóm`

- **Endpoint:** `POST /api/v1/groups/{group_id}/members` | `[Auth: Bearer - Chỉ Group Admin]`
- **Request Body:**

  ```json
  {
    "email": "thanhvien2@example.com"
  }
  ```

- **Response (`201 Created`):** Trả về thông tin thành viên vừa được thêm vào nhóm.

#### `3.3. Xóa thành viên khỏi nhóm`

- **Endpoint:** `DELETE /api/v1/groups/{group_id}/members/{user_id}` | `[Auth: Bearer - Chỉ Group Admin]`
- **Ràng buộc:** Trả về `400 Bad Request` (`MEMBER_HAS_UNSETTLED_DEBT`) nếu thành viên này vẫn còn dư nợ chưa thanh toán trong nhóm.
- **Response (`204 No Content`):** Xóa thành công.

---

### Module 4: Khoản chi & Chia tiền (`Expenses` — ORM Eager Loading & DB Indexing)

#### `4.1. Tạo khoản chi mới & Chia tiền`

- **Endpoint:** `POST /api/v1/groups/{group_id}/expenses` | `[Auth: Bearer - Thành viên nhóm]`
- **Mục đích:** Ghi nhận khoản chi, tính toán chia tiền theo 1 trong 3 chế độ (`EQUAL`, `EXACT`, `PERCENTAGE`), lưu vào **PostgreSQL** trong một **Transaction** và xóa khóa cache thống kê tương ứng trên **Redis**.
- **Request Body (ví dụ chế độ chia đều `EQUAL`):**

  ```json
  {
    "title": "Ăn tối lẩu gà lá é",
    "total_amount": "300000.00",
    "paid_by_user_id": "550e8400-e29b-41d4-a716-446655440001",
    "category_id": 1,
    "expense_date": "2026-11-18T19:30:00Z",
    "split_type": "EQUAL",
    "splits": [
      { "user_id": "550e8400-e29b-41d4-a716-446655440001" },
      { "user_id": "550e8400-e29b-41d4-a716-446655440002" },
      { "user_id": "550e8400-e29b-41d4-a716-446655440003" }
    ]
  }
  ```

  > **Lưu ý:** Nếu `split_type` là `EXACT`, mỗi phần tử trong `splits` gửi kèm `"amount": "120000.00"`; nếu là `PERCENTAGE`, gửi kèm `"percentage": "40.00"`.

- **Response (`201 Created`):**

  ```json
  {
    "id": "770e8400-e29b-41d4-a716-446655440099",
    "group_id": "880e8400-e29b-41d4-a716-446655440010",
    "title": "Ăn tối lẩu gà lá é",
    "total_amount": "300000.00",
    "split_type": "EQUAL",
    "paid_by": {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "full_name": "Nguyễn Văn A"
    },
    "category": {
      "id": 1,
      "name": "Ăn uống"
    },
    "splits": [
      {
        "user_id": "550e8400-e29b-41d4-a716-446655440001",
        "full_name": "Nguyễn Văn A",
        "amount": "100000.00"
      },
      {
        "user_id": "550e8400-e29b-41d4-a716-446655440002",
        "full_name": "Nguyễn Văn C",
        "amount": "100000.00"
      },
      {
        "user_id": "550e8400-e29b-41d4-a716-446655440003",
        "full_name": "Trần Thị B",
        "amount": "100000.00"
      }
    ],
    "expense_date": "2026-11-18T19:30:00Z"
  }
  ```

#### `4.2. Lọc & Truy vấn Danh sách Khoản chi`

- **Endpoint:** `GET /api/v1/groups/{group_id}/expenses` | `[Auth: Bearer - Thành viên nhóm]`
- **Mục đích:**
  1. Kiểm chứng việc loại bỏ **N+1 Problem** ở tầng **ORM** khi tải lồng nhau `paid_by`, `category` và danh sách `splits` cho nhiều khoản chi cùng lúc.
  2. Kiểm chứng hiệu năng của **DB Indexes** (Composite Index trên `(group_id, expense_date)` và `(paid_by_user_id, expense_date)`) thông qua `EXPLAIN ANALYZE` trên tập dữ liệu `200.000+` bản ghi.
- **Query Parameters:**
  - `user_id` _(UUID, tùy chọn)_: Lọc theo người trả tiền.
  - `category_id` _(Integer, tùy chọn)_: Lọc theo danh mục.
  - `from_date` _(ISO 8601, tùy chọn)_: Từ thời điểm.
  - `to_date` _(ISO 8601, tùy chọn)_: Đến thời điểm.
  - `page` _(Integer, mặc định `1`)_, `limit` _(Integer, mặc định `20`)_.
- **Response (`200 OK`):** Trả về đối tượng phân trang chứa danh sách các khoản chi đầy đủ thông tin lồng nhau như mẫu tại mục `4.1`.

---

### Module 5: Ví Nội bộ, Sổ cái & Thanh toán Nợ (`Wallet & Settlement` — ACID Transactions)

#### `5.1. Xem thông tin ví cá nhân`

- **Endpoint:** `GET /api/v1/wallets/me` | `[Auth: Bearer]`
- **Response (`200 OK`):**

  ```json
  {
    "wallet_id": "660e8400-e29b-41d4-a716-446655440001",
    "user_id": "550e8400-e29b-41d4-a716-446655440001",
    "balance": "850000.00",
    "currency": "VND",
    "updated_at": "2026-11-18T20:00:00Z"
  }
  ```

#### `5.2. Nạp tiền giả lập vào ví (Top-up)`

- **Endpoint:** `POST /api/v1/wallets/top-up` | `[Auth: Bearer]`
- **Mục đích:** Cộng tiền vào ví cá nhân và ghi nhận một dòng sổ cái mới (`DEPOSIT`) bên trong một **ACID Transaction**.
- **Request Body:**

  ```json
  {
    "amount": "500000.00",
    "reference_note": "Nạp tiền vào ví cá nhân"
  }
  ```

- **Response (`200 OK`):** Trả về thông tin ví với số dư mới và mã giao dịch sổ cái (`ledger_entry_id`).

#### `5.3. Xem tổng hợp công nợ trong nhóm`

- **Endpoint:** `GET /api/v1/groups/{group_id}/balances` | `[Auth: Bearer - Thành viên nhóm]`
- **Response (`200 OK`):**

  ```json
  {
    "group_id": "880e8400-e29b-41d4-a716-446655440010",
    "debts": [
      {
        "from_user": {
          "id": "550e8400-e29b-41d4-a716-446655440002",
          "full_name": "Nguyễn Văn C"
        },
        "to_user": {
          "id": "550e8400-e29b-41d4-a716-446655440001",
          "full_name": "Nguyễn Văn A"
        },
        "amount": "100000.00"
      }
    ]
  }
  ```

#### `5.4. Thanh toán nợ nội bộ giữa hai thành viên (Settle Up)`

- **Endpoint:** `POST /api/v1/groups/{group_id}/settle` | `[Auth: Bearer - Thành viên nhóm]`
- **Mục đích:** Thực thi giao dịch chuyển tiền cấn trừ nợ trực tiếp từ ví người gửi sang ví người nhận. Bắt buộc bọc toàn bộ quá trình khóa bản ghi ví, trừ tiền, cộng tiền, tạo bản ghi thanh toán nợ và ghi 2 dòng biến động sổ cái (`SETTLEMENT_OUT`, `SETTLEMENT_IN`) trong một **ACID Transaction** duy nhất.
- **Request Body:**

  ```json
  {
    "payee_user_id": "550e8400-e29b-41d4-a716-446655440001",
    "amount": "100000.00",
    "note": "Trả tiền lẩu gà lá é"
  }
  ```

- **Response (`200 OK`):**

  ```json
  {
    "settlement_id": "990e8400-e29b-41d4-a716-446655440055",
    "group_id": "880e8400-e29b-41d4-a716-446655440010",
    "payer_user_id": "550e8400-e29b-41d4-a716-446655440002",
    "payee_user_id": "550e8400-e29b-41d4-a716-446655440001",
    "amount": "100000.00",
    "sender_new_balance": "400000.00",
    "settled_at": "2026-11-18T21:15:00Z"
  }
  ```

#### `5.5. Tra cứu lịch sử sổ cái cá nhân (Immutable Ledger)`

- **Endpoint:** `GET /api/v1/wallets/me/ledger` | `[Auth: Bearer]`
- **Query Parameters:** `page`, `limit`, `transaction_type` (`DEPOSIT`, `SETTLEMENT_OUT`, `SETTLEMENT_IN`).
- **Response (`200 OK`):** Danh sách phân trang các bản ghi biến động số dư kèm `balance_before` và `balance_after`.

---

### Module 6: Báo cáo Thống kê & Redis Caching (`Analytics`)

#### `6.1. Thống kê tổng chi tiêu nhóm theo danh mục trong tháng`

- **Endpoint:** `GET /api/v1/groups/{group_id}/analytics/monthly` | `[Auth: Bearer - Thành viên nhóm]`
- **Mục đích:** Thực hiện truy vấn tổng hợp **SQL** (`SUM`, `GROUP BY`) trên **PostgreSQL** và lưu kết quả vào **Redis** với khóa `analytics:group:{group_id}:{year}-{month}` (TTL `900s`). Khóa này tự động bị xóa khi có sự kiện tạo/sửa/xóa khoản chi tại `4.1`.
- **Query Parameters:**
  - `year` _(Integer, bắt buộc, ví dụ: `2026`)_
  - `month` _(Integer, bắt buộc, từ `1` đến `12`, ví dụ: `11`)_
- **Response Headers:**

  ```http
  X-Cache-Status: HIT
  ```

  Giá trị là `MISS` ở lần truy vấn đầu tiên (tính toán từ PostgreSQL) và `HIT` ở các lần đọc tiếp theo (đọc từ Redis).

- **Response (`200 OK`):**

  ```json
  {
    "group_id": "880e8400-e29b-41d4-a716-446655440010",
    "period": "2026-11",
    "total_spent": "1250000.00",
    "breakdown_by_category": [
      {
        "category_id": 1,
        "category_name": "Ăn uống",
        "total_amount": "850000.00",
        "percentage": "68.00"
      },
      {
        "category_id": 2,
        "category_name": "Di chuyển",
        "total_amount": "400000.00",
        "percentage": "32.00"
      }
    ]
  }
  ```

---

## 4. Ma trận Đối chiếu API với Kiến thức Lộ trình Backend

| Endpoint tiêu biểu                                                              | Kỹ thuật Backend được kiểm chứng trực tiếp                                                      |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`                 | Xây dựng **RESTful JSON APIs**, xác thực phi trạng thái bằng **JWT** (Access & Refresh Token).  |
| `GET /categories`                                                               | Áp dụng **HTTP Caching** (`Cache-Control`, `ETag`, `If-None-Match` → `304 Not Modified`).       |
| `GET /groups/{group_id}/expenses`                                               | Khắc phục **N+1 Problem** trong **ORM** và đo tốc độ **DB Indexes** bằng `EXPLAIN ANALYZE`.     |
| `POST /wallets/top-up`, `POST /groups/{group_id}/settle`                        | Thực thi **ACID Transactions** trên **PostgreSQL**, chống tranh chấp số dư và bảo toàn sổ cái.  |
| `GET /groups/{group_id}/analytics/monthly` & `POST /groups/{group_id}/expenses` | Kết hợp truy vấn gộp **SQL** với **Redis Caching** (Cache-Aside & Cache Invalidation).          |
| Toàn bộ luồng từ `1.1` → `6.1`                                                  | Kịch bản chuẩn để viết **Integration Testing** và **Functional Testing** tự động bằng `pytest`. |
