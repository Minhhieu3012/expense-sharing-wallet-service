# Tài liệu Thiết kế Cơ sở dữ liệu (Database Schema)

**Tên dự án:** Hệ thống Quản lý Chi tiêu Nhóm & Ví Thanh toán Nội bộ  
**Hệ quản trị CSDL:** PostgreSQL 16+  
**Công cụ ORM & Migration:** SQLAlchemy 2.0 + Alembic  
**Tài liệu liên quan:** `docs/01-functional-specs.md`, `docs/02-non-functional-requirements.md`, `docs/04-api-contract.md`

---

## 1. Tổng quan Kiến trúc Dữ liệu & Chuẩn hóa (Normalization)

Lược đồ cơ sở dữ liệu được thiết kế gồm **7 bảng nghiệp vụ cốt lõi** (`users`, `wallets`, `groups`, `group_members`, `expenses`, `expense_splits`, `ledger_transactions`) kết hợp với **2 bảng danh mục & đối soát** (`categories`, `settlements`) nhằm đáp ứng trọn vẹn các API đã đặc tả.

### Áp dụng Chuẩn hóa Dữ liệu (1NF $\rightarrow$ 3NF)

- **Đạt chuẩn 1NF (First Normal Form):** Mọi cột đều lưu trữ giá trị nguyên tử (atomic). Danh sách những người cùng chia một hóa đơn không lưu dưới dạng mảng JSON trong bảng `expenses` mà được tách thành từng dòng độc lập tại bảng `expense_splits`.
- **Đạt chuẩn 2NF (Second Normal Form):** Các bảng sử dụng khóa chính tổ hợp như `group_members (group_id, user_id)` chỉ chứa các thuộc tính phụ thuộc hoàn toàn vào cả hai khóa (`role`, `joined_at`).
- **Đạt chuẩn 3NF (Third Normal Form):** Loại bỏ hoàn toàn phụ thuộc bắc cầu. Tên và mã danh mục chi tiêu được tách sang bảng tham chiếu `categories` thay vì lưu lặp lại chuỗi văn bản trong `expenses`; thông tin hồ sơ người dùng tách biệt khỏi thông tin số dư ví (`wallets`).
- **Phi chuẩn hóa có chủ đích (Controlled Denormalization):** Cột `balance` được duy trì trực tiếp trên bảng `wallets` thay vì tính tổng động (`SUM`) từ hàng triệu dòng của `ledger_transactions` mỗi lần kiểm tra số dư. Điều này giúp thao tác đọc và khóa bản ghi khi thanh toán đạt độ phức tạp $O(1)$, đồng thời vẫn đảm bảo tính đối soát tuyệt đối thông qua hai cột `balance_before` và `balance_after` trong sổ cái.

---

## 2. Sơ đồ Quan hệ Thực thể (ERD)

```text
+------------------+       1:1       +------------------+
|      users       |---------------->|     wallets      |
+------------------+                 +------------------+
| PK id (UUID)     |                 | PK id (UUID)     |
| UK email         |                 | FK user_id (UK)  |
|    password_hash |                 |    balance       |
|    full_name     |                 |    currency      |
+------------------+                 +------------------+
         |                                    |
         | 1:N                                | 1:N (Immutable)
         v                                    v
+------------------+                 +-----------------------+
|  group_members   |                 |  ledger_transactions  |
+------------------+                 +-----------------------+
| PK,FK group_id   |                 | PK id (UUID)          |
| PK,FK user_id    |                 | FK wallet_id          |
|       role       |                 |    transaction_type   |
+------------------+                 |    amount             |
         ^                           |    balance_before     |
         | 1:N                       |    balance_after      |
+------------------+                 |    reference_id       |
|      groups      |                 +-----------------------+
+------------------+
| PK id (UUID)     |       1:N       +------------------+
|    name          |---------------->|   settlements    |
|    currency      |                 +------------------+
| FK created_by    |                 | PK id (UUID)     |
+------------------+                 | FK group_id      |
         |                           | FK payer_user_id |
         | 1:N                       | FK payee_user_id |
         v                           |    amount        |
+------------------+       N:1       +------------------+
|     expenses     |---------------->+------------------+
+------------------+                 |    categories    |
| PK id (UUID)     |                 +------------------+
| FK group_id      |                 | PK id (SERIAL)   |
| FK paid_by_user  |                 | UK code          |
| FK created_by    |                 |    name          |
| FK category_id   |                 +------------------+
|    total_amount  |
|    split_type    |
|    expense_date  |
+------------------+
         |
         | 1:N
         v
+------------------+
|  expense_splits  |
+------------------+
| PK id (UUID)     |
| FK expense_id    |
| FK user_id       |
|    amount        |
|    percentage    |
+------------------+
```

---

## 3. Định nghĩa Chi tiết Bảng & Ràng buộc (PostgreSQL DDL)

Toàn bộ lược đồ sử dụng kiểu `NUMERIC(15, 2)` cho tiền tệ để tránh sai số dấu phẩy động và áp dụng `ON DELETE RESTRICT` cho các khóa ngoại tài chính nhằm bảo vệ dấu vết kiểm toán (audit trail).

```sql
-- Kích hoạt extension sinh UUID ngẫu nhiên (PostgreSQL < 13)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 1. BẢNG NGƯỜI DÙNG (users)
-- ============================================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_users_email UNIQUE (email)
);

-- ============================================================================
-- 2. BẢNG VÍ ĐIỆN TỬ CÁ NHÂN (wallets)
-- ============================================================================
CREATE TABLE wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_wallets_user_id UNIQUE (user_id),
    CONSTRAINT fk_wallets_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_wallets_balance_non_negative CHECK (balance >= 0.00)
);

-- ============================================================================
-- 3. BẢNG NHÓM CHI TIÊU (groups)
-- ============================================================================
CREATE TABLE groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    description TEXT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_groups_created_by FOREIGN KEY (created_by)
        REFERENCES users (id) ON DELETE RESTRICT
);

-- ============================================================================
-- 4. BẢNG THÀNH VIÊN NHÓM (group_members)
-- ============================================================================
CREATE TABLE group_members (
    group_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'MEMBER',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (group_id, user_id),
    CONSTRAINT fk_group_members_group FOREIGN KEY (group_id)
        REFERENCES groups (id) ON DELETE CASCADE,
    CONSTRAINT fk_group_members_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_group_members_role CHECK (role IN ('ADMIN', 'MEMBER'))
);

-- ============================================================================
-- 5. BẢNG DANH MỤC CHI TIÊU CHUẨN (categories - Dữ liệu tham chiếu)
-- ============================================================================
CREATE TABLE categories (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_categories_code UNIQUE (code)
);

-- ============================================================================
-- 6. BẢNG KHOẢN CHI TIÊU (expenses)
-- ============================================================================
CREATE TABLE expenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL,
    paid_by_user_id UUID NOT NULL,
    created_by_user_id UUID NOT NULL,
    category_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    total_amount NUMERIC(15, 2) NOT NULL,
    split_type VARCHAR(20) NOT NULL,
    expense_date TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_expenses_group FOREIGN KEY (group_id)
        REFERENCES groups (id) ON DELETE RESTRICT,
    CONSTRAINT fk_expenses_paid_by FOREIGN KEY (paid_by_user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_expenses_created_by FOREIGN KEY (created_by_user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_expenses_category FOREIGN KEY (category_id)
        REFERENCES categories (id) ON DELETE RESTRICT,
    CONSTRAINT chk_expenses_total_positive CHECK (total_amount > 0.00),
    CONSTRAINT chk_expenses_split_type CHECK (split_type IN ('EQUAL', 'EXACT', 'PERCENTAGE'))
);

-- ============================================================================
-- 7. BẢNG CHI TIẾT CHIA TIỀN (expense_splits)
-- ============================================================================
CREATE TABLE expense_splits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_id UUID NOT NULL,
    user_id UUID NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    percentage NUMERIC(5, 2) NULL,

    CONSTRAINT uq_expense_splits_expense_user UNIQUE (expense_id, user_id),
    CONSTRAINT fk_expense_splits_expense FOREIGN KEY (expense_id)
        REFERENCES expenses (id) ON DELETE CASCADE,
    CONSTRAINT fk_expense_splits_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_expense_splits_amount_non_negative CHECK (amount >= 0.00),
    CONSTRAINT chk_expense_splits_percentage_range CHECK (
        percentage IS NULL OR (percentage >= 0.00 AND percentage <= 100.00)
    )
);

-- ============================================================================
-- 8. BẢNG GIAO DỊCH THANH TOÁN NỢ NHÓM (settlements)
-- ============================================================================
CREATE TABLE settlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL,
    payer_user_id UUID NOT NULL,
    payee_user_id UUID NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    note VARCHAR(255) NULL,
    settled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_settlements_group FOREIGN KEY (group_id)
        REFERENCES groups (id) ON DELETE RESTRICT,
    CONSTRAINT fk_settlements_payer FOREIGN KEY (payer_user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_settlements_payee FOREIGN KEY (payee_user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT chk_settlements_amount_positive CHECK (amount > 0.00),
    CONSTRAINT chk_settlements_distinct_users CHECK (payer_user_id <> payee_user_id)
);

-- ============================================================================
-- 9. BẢNG SỔ CÁI GIAO DỊCH BẤT BIẾN (ledger_transactions)
-- ============================================================================
CREATE TABLE ledger_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id UUID NOT NULL,
    transaction_type VARCHAR(30) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    balance_before NUMERIC(15, 2) NOT NULL,
    balance_after NUMERIC(15, 2) NOT NULL,
    reference_id UUID NULL,
    reference_note VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_ledger_wallet FOREIGN KEY (wallet_id)
        REFERENCES wallets (id) ON DELETE RESTRICT,
    CONSTRAINT chk_ledger_type CHECK (
        transaction_type IN ('DEPOSIT', 'SETTLEMENT_OUT', 'SETTLEMENT_IN')
    ),
    CONSTRAINT chk_ledger_amount_positive CHECK (amount > 0.00),
    CONSTRAINT chk_ledger_balances_non_negative CHECK (
        balance_before >= 0.00 AND balance_after >= 0.00
    )
);
```

---

## 4. Thiết kế Chỉ mục (DB Indexes) & Phân tích Hiệu năng Truy vấn

### Danh sách Chỉ mục Cần tạo

PostgreSQL chỉ tự động tạo chỉ mục cho `PRIMARY KEY` và `UNIQUE`, không tự tạo cho `FOREIGN KEY`. Vì vậy, các chỉ mục dưới đây được thiết kế bám sát các mẫu truy vấn thực tế của API:

```sql
-- 1. Tối ưu truy vấn danh sách nhóm mà một người dùng đang tham gia
CREATE INDEX idx_group_members_user_id ON group_members (user_id);

-- 2. Composite Index phục vụ lọc khoản chi theo nhóm và sắp xếp giảm dần theo thời gian (FR-08)
-- Hỗ trợ cả truy vấn chỉ lọc theo group_id nhờ quy tắc Leftmost Prefix
CREATE INDEX idx_expenses_group_date ON expenses (group_id, expense_date DESC);

-- 3. Composite Index phục vụ lọc khoản chi theo người trả tiền trong khoảng thời gian
CREATE INDEX idx_expenses_paid_by_date ON expenses (paid_by_user_id, expense_date DESC);

-- 4. Hỗ trợ JOIN nhanh từ khoản chi sang chi tiết chia tiền và tính tổng nợ theo user
CREATE INDEX idx_expense_splits_expense_id ON expense_splits (expense_id);
CREATE INDEX idx_expense_splits_user_id ON expense_splits (user_id);

-- 5. Phục vụ tính toán tổng hợp công nợ nhóm (FR-10)
CREATE INDEX idx_settlements_group_id ON settlements (group_id);

-- 6. Phục vụ tra cứu lịch sử biến động sổ cái theo ví và thời gian mới nhất (API 5.5)
CREATE INDEX idx_ledger_wallet_created ON ledger_transactions (wallet_id, created_at DESC);
```

### Quy trình Kiểm chứng Hiệu năng với `EXPLAIN ANALYZE`

Sau khi dùng công cụ CLI (`FR-14`) nạp $200.000+$ bản ghi vào bảng `expenses`, thực hiện kiểm chứng kế hoạch thực thi của câu lệnh lọc lịch sử chi tiêu:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, title, total_amount, paid_by_user_id, category_id, expense_date
FROM expenses
WHERE group_id = '880e8400-e29b-41d4-a716-446655440010'
  AND expense_date >= '2026-01-01T00:00:00Z'
  AND expense_date < '2026-12-01T00:00:00Z'
ORDER BY expense_date DESC
LIMIT 20 OFFSET 0;
```

- **Trước khi đánh `idx_expenses_group_date`:** PostgreSQL thực hiện `Seq Scan on expenses` kèm bước `Sort` tốn bộ nhớ, thời gian phản hồi thường vượt ngưỡng $150\text{ms} - 400\text{ms}$.
- **Sau khi đánh `idx_expenses_group_date`:** PostgreSQL chuyển sang `Index Scan using idx_expenses_group_date`, loại bỏ hoàn toàn bước `Sort` do dữ liệu trên cây B-Tree đã được sắp xếp sẵn theo `expense_date DESC`, giảm thời gian thực thi xuống dưới $5\text{ms} - 15\text{ms}$.

---

## 5. Chiến lược Giao dịch ACID & Kiểm soát Đồng thời (Transactions & Locking)

Đối với nghiệp vụ **Thanh toán nợ nội bộ (`POST /api/v1/groups/{group_id}/settle`)**, hệ thống phải bảo vệ tính toàn vẹn của dòng tiền trước tình huống hai người dùng chuyển tiền cho nhau hoặc rút tiền cùng một mili-giây:

```sql
BEGIN;

-- Bước 1a: Khóa bi quan 2 bản ghi thành viên nhóm theo thứ tự user_id ASC
-- Mục đích: Tuần tự hóa các giao dịch trả nợ giữa cặp (payer, payee), ngăn chặn việc gửi trùng 2 request cùng lúc vượt quá mức nợ
SELECT group_id, user_id
FROM group_members
WHERE group_id = :group_id AND user_id IN (:payer_id, :payee_id)
ORDER BY user_id ASC
FOR UPDATE;

-- Bước 1b: Khóa bi quan hai bản ghi ví theo thứ tự tăng dần của user_id để chống âm số dư và Deadlock
SELECT id, user_id, balance
FROM wallets
WHERE user_id IN (:payer_id, :payee_id)
ORDER BY user_id ASC
FOR UPDATE;

-- Bước 2: Sau khi đã giữ khóa, tính lại nợ ròng thực tế trong nhóm và kiểm tra tại tầng ứng dụng:
-- (a) :amount <= current_net_debt (nếu vượt nợ -> ROLLBACK, trả lỗi 400 OVER_SETTLEMENT_AMOUNT)
-- (b) payer_wallet.balance >= :amount (nếu không đủ số dư -> ROLLBACK, trả lỗi 400 INSUFFICIENT_WALLET_BALANCE)

-- Bước 3: Cập nhật số dư ví người gửi và người nhận
UPDATE wallets
SET balance = balance - :amount, updated_at = NOW()
WHERE id = :payer_wallet_id;

UPDATE wallets
SET balance = balance + :amount, updated_at = NOW()
WHERE id = :payee_wallet_id;

-- Bước 4: Lưu bản ghi thanh toán nợ trong nhóm
INSERT INTO settlements (id, group_id, payer_user_id, payee_user_id, amount, note)
VALUES (:settlement_id, :group_id, :payer_id, :payee_id, :amount, :note);

-- Bước 5: Ghi 2 dòng sổ cái bất biến (Double-entry audit trail)
INSERT INTO ledger_transactions (wallet_id, transaction_type, amount, balance_before, balance_after, reference_id, reference_note)
VALUES
    (:payer_wallet_id, 'SETTLEMENT_OUT', :amount, :payer_before, :payer_after, :settlement_id, :note),
    (:payee_wallet_id, 'SETTLEMENT_IN', :amount, :payee_before, :payee_after, :settlement_id, :note);

COMMIT;
```

---

## 6. Kiểm soát ORM & Xử lý Lỗi N+1 Problem (SQLAlchemy)

### Tình huống phát sinh N+1 Problem

Tại endpoint `GET /api/v1/groups/{group_id}/expenses` (`limit=20`), nếu sử dụng cơ chế tải mặc định (`lazy="select"`) của ORM khi chuyển đổi $20$ đối tượng `Expense` sang JSON phản hồi:

- **1 truy vấn** lấy $20$ bản ghi từ bảng `expenses`.
- **20 truy vấn** lấy thông tin `paid_by` từ bảng `users`.
- **20 truy vấn** lấy thông tin `category` từ bảng `categories`.
- **20 truy vấn** lấy danh sách chia tiền từ bảng `expense_splits`.
- Tổng cộng phát sinh **$1 + 3N = 61$ truy vấn** cho một lần gọi API duy nhất.

### Giải pháp Eager Loading chuẩn hóa

Kết hợp `joinedload` cho quan hệ nhiều-một (`N:1`) và `selectinload` cho quan hệ một-nhiều (`1:N`) để giảm số lượng câu lệnh SQL xuống mức hằng số (**2 truy vấn duy nhất** bất kể `limit` bằng bao nhiêu):

```python
stmt = (
    select(Expense)
    .where(Expense.group_id == group_id)
    .options(
        joinedload(Expense.paid_by),          # JOIN trực tiếp bảng users
        joinedload(Expense.category),         # JOIN trực tiếp bảng categories
        selectinload(Expense.splits)          # Thực thi 1 câu WHERE expense_id IN (...)
        .joinedload(ExpenseSplit.user),       # JOIN luôn thông tin user của từng phần chia
    )
    .order_by(Expense.expense_date.desc())
    .limit(limit)
    .offset(offset)
)
```

### Giới hạn của ORM cần tránh trong dự án

1. **Nạp dữ liệu hàng loạt (CLI Seeder `FR-14`):** Không khởi tạo $200.000$ thực thể ORM qua `session.add_all()` vì chi phí theo dõi trạng thái (Identity Map) sẽ làm chậm tiến trình và ngốn RAM. Thay vào đó, sử dụng `session.execute(insert(Expense), batch_dicts)` hoặc lệnh `COPY` của PostgreSQL theo từng lô $5.000$ dòng.
2. **Báo cáo thống kê phức tạp (`FR-12`):** Sử dụng câu lệnh SQL tổng hợp trực tiếp (`SUM`, `GROUP BY`) thay vì kéo toàn bộ bản ghi lên Python để cộng thủ công.

---

## 7. Quy chuẩn Quản lý DB Migrations (Alembic)

1. **Tổ chức phiên bản:** Mọi tệp migration nằm trong thư mục `alembic/versions/` với tiền tố thứ tự rõ ràng:
   - `0001_initial_schema.py`: Khởi tạo 9 bảng, khóa ngoại, ràng buộc `CHECK` và toàn bộ chỉ mục.
   - `0002_seed_default_categories.py`: Nạp 5 danh mục chi tiêu mặc định (`FOOD`, `TRANSPORT`, `ACCOMMODATION`, `UTILITIES`, `ENTERTAINMENT`).
2. **Tính thuận nghịch (Reversibility):** Mọi hàm `upgrade()` phải có hàm `downgrade()` tương ứng để có thể hoàn tác lược đồ an toàn trong quá trình phát triển và chạy kiểm thử tích hợp (`Integration Testing`).
3. **Kiểm duyệt trước khi áp dụng:** Luôn kiểm tra mã nguồn sinh tự động bởi `alembic revision --autogenerate` trước khi chạy `alembic upgrade head` để đảm bảo tên các ràng buộc (`uq_`, `fk_`, `chk_`, `idx_`) tuân thủ đúng quy ước đặt tên của dự án.
