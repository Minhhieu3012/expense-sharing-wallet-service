# Tài liệu Đặc tả Yêu cầu Nghiệp vụ (Functional Specs & Business Rules)

- **Tên dự án:** Hệ thống Quản lý Chi tiêu Nhóm & Ví Thanh toán Nội bộ
- **Ngôn ngữ & Công nghệ chính:** Python, PostgreSQL, Redis
- **Phạm vi tài liệu:** Đặc tả toàn bộ yêu cầu chức năng (MVP), quy tắc nghiệp vụ và các kịch bản kỹ thuật.

---

## 1. Tổng quan & Tác nhân hệ thống (Overview & Actors)

Hệ thống cung cấp bộ RESTful JSON APIs cho phép người dùng tạo nhóm chi tiêu, ghi nhận hóa đơn, tự động chia tiền và thanh toán công nợ trực tiếp thông qua ví điện tử nội bộ. Song song đó, hệ thống đi kèm một ứng dụng dòng lệnh (CLI app) phục vụ việc nhập dữ liệu sao kê và sinh dữ liệu giả lập khối lượng lớn để kiểm thử hiệu năng cơ sở dữ liệu.

Hệ thống bao gồm 3 nhóm tác nhân chính:

- **Member (Thành viên đã xác thực):** Người dùng có tài khoản, sở hữu ví cá nhân, có thể tạo nhóm mới, tham gia nhóm được mời, ghi nhận khoản chi và thực hiện giao dịch trả nợ.
- **Group Admin (Trưởng nhóm):** Người khởi tạo nhóm chi tiêu; kế thừa toàn bộ quyền của Member và có thêm quyền thêm hoặc xóa thành viên khỏi nhóm.
- **CLI Operator (Quản trị viên vận hành qua Terminal):** Tác nhân sử dụng công cụ dòng lệnh để import dữ liệu chi tiêu hàng loạt hoặc tạo dữ liệu mẫu phục vụ đo đạc tốc độ truy vấn.

---

## 2. Đặc tả Yêu cầu Chức năng (Functional Requirements)

### Module 1: Xác thực & Quản lý Tài khoản (Auth & Account)

- **FR-01 — Đăng ký tài khoản & Khởi tạo ví tự động:** Người dùng đăng ký bằng email, mật khẩu và họ tên. Ngay khi tài khoản được tạo, hệ thống tự động khởi tạo một ví cá nhân (`balance = 0`) gắn với người dùng đó.
- **FR-02 — Đăng nhập & Xác thực bằng JWT:** Hệ thống kiểm tra thông tin đăng nhập và cấp phát cặp JWT gồm Access Token và Refresh Token để bảo vệ các endpoint yêu cầu xác thực.
- **FR-03 — Làm mới phiên đăng nhập:** Cung cấp endpoint nhận Refresh Token hợp lệ để cấp lại Access Token mới mà không yêu cầu người dùng đăng nhập lại.

### Module 2: Quản lý Nhóm & Dữ liệu Danh mục (Groups & Reference Data)

- **FR-04 — Tạo nhóm & Quản lý thành viên:** Người dùng tạo nhóm chi tiêu (tên nhóm, đơn vị tiền tệ) và mặc định trở thành Group Admin. Trưởng nhóm có thể thêm thành viên khác vào nhóm thông qua email.
- **FR-05 — Truy vấn danh mục chi tiêu chuẩn:** Cung cấp API lấy danh sách các danh mục chi tiêu mặc định (Ăn uống, Di chuyển, Lưu trú, Hóa đơn, Giải trí). Endpoint này phải áp dụng cơ chế HTTP Caching (thông qua các header `Cache-Control` và `ETag`) để giảm tải các yêu cầu lặp lại từ phía client.

### Module 3: Ghi nhận & Truy vấn Khoản chi (Expenses & Splitting)

- **FR-06 — Tạo khoản chi mới với 3 chế độ chia tiền:** Thành viên trong nhóm có thể ghi nhận một khoản chi (tổng tiền, người đã trả tiền, danh mục, mô tả, thời gian chi) và chọn 1 trong 3 hình thức chia cho các thành viên tham gia:
  - **Chia đều (`EQUAL`):** Chia đều tổng số tiền cho danh sách thành viên được chọn.
  - **Chia theo số tiền cụ thể (`EXACT`):** Nhập chính xác số tiền từng thành viên phải chịu.
  - **Chia theo phần trăm (`PERCENTAGE`):** Nhập tỷ lệ phần trăm từng thành viên phải chịu.
- **FR-07 — Xem danh sách chi tiết khoản chi (Tối ưu truy vấn ORM):** API trả về danh sách các khoản chi trong nhóm kèm đầy đủ thông tin người trả tiền, tên danh mục và danh sách chi tiết số tiền từng thành viên phải trả. Truy vấn phải được tối ưu hóa ở tầng ORM để xử lý triệt để lỗi **N+1 Problem** (không phát sinh truy vấn phụ lặp lại theo từng bản ghi).
- **FR-08 — Lọc & Tra cứu lịch sử chi tiêu quy mô lớn:** Cho phép lọc khoản chi theo `group_id`, `user_id`, `category_id` và khoảng thời gian (`from_date` – `to_date`) có phân trang. Chức năng này phải đảm bảo tốc độ phản hồi nhanh trên tập dữ liệu hàng trăm nghìn dòng thông qua việc thiết kế DB Indexes và kiểm chứng bằng công cụ phân tích hiệu năng truy vấn của PostgreSQL.

### Module 4: Ví nội bộ, Sổ cái & Thanh toán nợ (Wallet, Ledger & Settlement)

- **FR-09 — Nạp tiền giả lập vào ví (Wallet Top-up):** Cho phép người dùng nạp một khoản tiền vào ví cá nhân để phục vụ việc thanh toán nợ trong nhóm.
- **FR-10 — Bảng tổng hợp công nợ nhóm (Group Balances):** Tự động tính toán và hiển thị số dư nợ ròng giữa các thành viên trong nhóm (ai đang nợ ai bao nhiêu tiền) dựa trên lịch sử các khoản chi và các giao dịch đã thanh toán.
- **FR-11 — Thanh toán nợ nội bộ (Settle Up):** Cho phép người nợ thực hiện lệnh chuyển tiền từ ví của mình sang ví của chủ nợ để xóa nợ. Toàn bộ luồng nghiệp vụ gồm: kiểm tra số dư, trừ tiền ví người gửi, cộng tiền ví người nhận và ghi log biến động vào bảng sổ cái (`ledger_transactions`) bắt buộc phải thực thi bên trong một **ACID Transaction**.

### Module 5: Thống kê & Lưu đệm dữ liệu (Analytics & Caching)

- **FR-12 — Báo cáo thống kê chi tiêu theo tháng:** Cung cấp API tổng hợp tổng chi tiêu của nhóm theo từng danh mục trong tháng (sử dụng các câu lệnh gộp SQL như `SUM`, `GROUP BY`). Kết quả thống kê phải được lưu trữ trên Redis để phục vụ các lần đọc tiếp theo và tự động vô hiệu hóa (Cache Invalidation) ngay khi dữ liệu chi tiêu của nhóm thay đổi.

### Module 6: Công cụ Dòng lệnh (CLI Application)

- **FR-13 — CLI Tính toán & Import sao kê chi tiêu:** Xây dựng công cụ dòng lệnh cho phép đọc file `.csv` chứa danh sách chi tiêu, tự động tính toán phần chia tiền và lưu vào cơ sở dữ liệu.
- **FR-14 — CLI Sinh dữ liệu giả lập (Data Seeder):** Cho phép chạy lệnh trên terminal để tạo tự động từ 200.000 đến 500.000 bản ghi khoản chi và giao dịch vào PostgreSQL, phục vụ cho việc kiểm thử hiệu năng truy vấn và đánh giá tác dụng của chỉ mục.

---

## 3. Quy tắc Nghiệp vụ & Các trường hợp biên (Business Rules & Edge Cases)

- **BR-01 — Độ chính xác tuyệt đối trong tính toán tiền tệ:** Mọi giá trị tiền tệ phải sử dụng kiểu số thập phân chính xác (`Decimal` trong Python và `NUMERIC(15, 2)` trong PostgreSQL), nghiêm cấm sử dụng kiểu số thực dấu phẩy động (`float`) để tránh sai số làm tròn.
- **BR-02 — Quy tắc xử lý số lẻ khi chia tiền:** Khi chia đều một khoản tiền không chia hết (ví dụ: 100.000 chia cho 3 người được 33.333,33 mỗi người, còn dư 0,01), phần chênh lệch dư ra bắt buộc phải cộng dồn vào phần của người tạo khoản chi để đảm bảo tổng các phần chia luôn bằng chính xác tổng giá trị hóa đơn.
- **BR-03 — Ràng buộc tính hợp lệ của khoản chia:**
  - Với chế độ `PERCENTAGE`: Tổng tỷ lệ phần trăm của tất cả thành viên tham gia phải bằng đúng 100.00%.
  - Với chế độ `EXACT`: Tổng số tiền chi tiết của các thành viên phải bằng đúng `total_amount` của khoản chi.
  - Hệ thống phải từ chối yêu cầu (trả về lỗi HTTP 422 hoặc 400) nếu vi phạm một trong hai điều kiện trên.
- **BR-04 — Ràng buộc số dư ví & Tính bất biến của sổ cái:** Số dư khả dụng của ví không bao giờ được phép nhỏ hơn 0. Mọi biến động tăng/giảm số dư đều phải tạo ra một bản ghi mới trong bảng sổ cái (`ledger_transactions`); nghiêm cấm mọi hành vi cập nhật (`UPDATE`) hoặc xóa (`DELETE`) các bản ghi đã ghi vào sổ cái.
- **BR-05 — Tính nguyên tử của giao dịch chuyển tiền (Atomicity):** Trong chức năng thanh toán nợ (FR-11), nếu số dư ví người gửi không đủ tại thời điểm khóa bản ghi hoặc xảy ra lỗi hệ thống ở bước cộng tiền cho người nhận / ghi sổ cái, toàn bộ Transaction phải tự động hủy bỏ (rollback) để bảo đảm tính chất ACID.
- **BR-06 — Kiểm soát quyền truy cập tài nguyên (Authorization):**
  - Người dùng chỉ được phép xem thông tin, tạo khoản chi hoặc xem báo cáo của những nhóm mà họ đang là thành viên.
  - Chỉ Group Admin mới có quyền xóa thành viên khỏi nhóm, và hệ thống chỉ cho phép xóa khi thành viên đó đã thanh toán hết toàn bộ công nợ (số dư nợ ròng bằng 0).
- **BR-07 — Quy tắc đồng bộ Cache (Cache Invalidation):** Ngay sau khi một khoản chi mới được tạo, chỉnh sửa hoặc xóa thành công trong PostgreSQL, hệ thống phải xóa khóa cache báo cáo thống kê tương ứng của nhóm đó trên Redis để tránh trả về dữ liệu cũ (stale data).
