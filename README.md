# Bank Agent Project

Accounting Agent offline để xử lý sao kê ACB/MSB/VCB, phân loại báo nợ/báo có, nhận diện nghiệp vụ kế toán, suy luận mã đối tượng và sinh file trung gian cho RPA nhập VACOM.

Phiên bản hiện tại dùng kiến trúc rule-first: rule + entity extraction + alias/fuzzy matching + historical memory + accounting verifier. Không dùng ML, LLM hoặc API cloud.

## 1. Chạy Bằng Venv

```powershell
cd C:\Users\Admin\Desktop\test\bank_agent_project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python bank_agent.py --input-dir .\input --output-dir .\output
```

Nếu PowerShell chặn activate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 2. Output vận hành

Mỗi lần chạy chỉ tạo hoặc cập nhật ba workbook:

```text
output/
├── rpa_input.xlsx
├── rpa_summary.xlsx
└── object_match_review.xlsx
```

Log vẫn hiển thị trên PowerShell nhưng không còn ghi `agent_run.log`. Các file `agent_run.log` và `rpa_tracking.json` còn lại từ phiên bản cũ chỉ là dữ liệu legacy; chương trình không tự xóa chúng.

### `rpa_input.xlsx`

Workbook có đúng năm sheet theo thứ tự:

- `BAO_NO_INPUT`: giao dịch báo nợ đủ điều kiện nhập.
- `BAO_CO_INPUT`: giao dịch báo có đủ điều kiện nhập.
- `THU_TIEN_MAT_INPUT`: phiếu thu tiền mặt, dùng cột `Người nộp tiền`.
- `CHI_TIEN_MAT_INPUT`: phiếu chi tiền mặt, dùng cột `Người nhận tiền`.
- `EXCEPTION`: các dòng cần người dùng kiểm tra hoặc bổ sung.

Bốn sheet input giữ nguyên tiêu đề PAD. Năm cột kỹ thuật `transaction_uid`, `run_id`, `Trạng thái RPA`, `Thông báo RPA`, `Thời gian nhập RPA` nằm cuối bảng và được ẩn. Cột `Lí do` dùng TCVN3 cho VACOM khi cấu hình `output.rpa_reason_encoding: "tcvn3"`; cột `Lí do Unicode` dùng để đọc và đối chiếu.

Tại `EXCEPTION`, người dùng bổ sung các ô màu vàng, chọn một trong bốn giá trị tại `Luồng nhập RPA`, sau đó nhập `yes` tại `Duyệt nhập RPA`. Chạy lệnh sau để kiểm tra và chuyển dòng hợp lệ vào đúng sheet input:

```powershell
.\.venv\Scripts\python.exe promote_reviewed_exceptions.py --input-file ".\output\rpa_input.xlsx"
```

Nếu thiếu dữ liệu, cột `Trạng thái xử lý` và `Vấn đề cần xử lý` cho biết chính xác trường cần bổ sung. Dòng đã chuyển được kiểm tra trùng bằng `transaction_uid`.

### `rpa_summary.xlsx`

Workbook chỉ có sheet `RPA_SUMMARY` và tích lũy lịch sử qua nhiều lần chạy. Người dùng/PAD cập nhật ba cột màu vàng: `Trạng thái RPA`, `Số chứng từ VACOM`, `Thông báo RPA`. Trạng thái chỉ dùng `chua_nhap` hoặc `hoan_thanh`; dòng `hoan_thanh` không quay lại `rpa_input.xlsx`.

Các cột kỹ thuật phục vụ cập nhật/finalize/abort được giữ ở cuối và ẩn. Khi đọc file summary schema cũ, chương trình tự chuyển đổi và tạo một bản sao tại `output/backup/rpa_summary_before_simplify_<timestamp>.xlsx` trước khi thay file.

### `object_match_review.xlsx`

Đây là file dành cho người quản trị danh mục/alias, chỉ phản ánh vấn đề của lần chạy hiện tại:

- `LOI_MA_DOI_TUONG`: một dòng cho mỗi giao dịch thực sự lỗi mã đối tượng, kèm tối đa hai gợi ý.
- `DE_XUAT_CAP_NHAT`: nhóm các lỗi và va chạm hiện tại thành danh sách hành động quản trị.

Hai sheet giữ `Trạng thái xử lý` và `Ghi chú` qua lần chạy sau bằng UID/action key. Nếu không có lỗi, workbook vẫn được tạo với hai sheet chỉ có header.

Khi người dùng mở `output/rpa_input.xlsx` để bỏ bớt dòng trước khi PAD nhập:

- Nên xóa cả dòng trong Excel bằng thao tác Delete row; hide/filter dòng không làm PAD bỏ qua.
- Nếu người dùng lỡ chỉ xóa nội dung ô, hãy chạy bước dọn file trước khi PAD đọc lại workbook:

```powershell
.\.venv\Scripts\python.exe sanitize_rpa_input.py --input-file ".\output\rpa_input.xlsx"
```

- Trong PAD, chèn command trên ngay sau bước `PROMOTE_REVIEWED_EXCEPTIONS` thành công và trước bước `ARCHIVE_RPA_INPUT`/đọc các sheet `*_INPUT`. Với nhánh chạy file input cũ, chèn sau `PROMOTE_REVIEWED_EXCEPTIONS_OLD_FILE`.

Trước khi agent/PAD cập nhật trạng thái, hãy đóng các workbook output. Mọi workbook được ghi qua file tạm rồi mới thay thế; nếu Excel đang khóa file hoặc quá trình ghi lỗi, file đích cũ vẫn được giữ nguyên.

## 3. Config Quan Trọng

- `config/own_company.yaml`: khai báo công ty mình để không bao giờ chọn nhầm mã ĐT như `LE PHAM`.
- `config/object_aliases.yaml`: alias thực tế trên sao kê, ví dụ `KBB`, `PETROLIMEX`, `VINH LONG`, `VSICO`.
- `config/reason_aliases.yaml`: alias loại thanh toán để sinh `Lí do` chi tiết, ví dụ `cước vận chuyển`, `phí cảng vụ`, `tiền thuê văn phòng`.
- `config/default_rules.yaml`: rule nghiệp vụ kế toán.
Khi gặp mã ĐT hay sai, ưu tiên bổ sung alias vào `object_aliases.yaml` trước. Đây là cách ổn định và dễ kiểm toán nhất.

## 4. Chạy Test

```powershell
python -m pytest --basetemp .pytest_tmp
```

## 5. Quản lý dữ liệu sao kê

`Quản lý dữ liệu sao kê` là cửa sổ desktop quản lý ba nhóm dữ liệu: Mã đối tượng, Loại thanh toán và Nghiệp vụ kế toán.

Khởi động bằng PowerShell:

```powershell
.\scripts\run_rule_manager.ps1
```

Hoặc chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe rule_manager.py
```

Luồng sử dụng:

1. Chọn danh mục Phải thu, Phải trả hoặc Nội bộ.
2. Chọn Mã ĐT đang có để bổ sung alias, hoặc bấm `Thêm Mã ĐT`.
3. Nhập alias; chương trình tự phân loại thành `Cụm từ chính xác` hoặc `Alias linh hoạt` khi áp dụng.
4. Click trực tiếp vào ô Alias để chỉnh sửa. Click chuột phải vào dòng để tạm ngưng, kích hoạt lại hoặc xóa.
5. Có thể tạm ngưng/kích hoạt mọi Mã ĐT. Chỉ Mã ĐT được thêm từ màn hình này mới có thể xóa.
6. Bấm `Áp dụng`; chương trình kiểm tra và thông báo rõ lỗi nếu dữ liệu chưa hợp lệ.

Khi áp dụng, chương trình lưu dữ liệu user tại `data/rule_manager/object_rules.user.json`, backup các file bị tác động vào `backup/rule_manager/<timestamp>/`, cập nhật workbook danh mục nếu có Mã ĐT mới, rồi hợp nhất và thay thế an toàn `config/object_aliases.yaml` cùng `config/object_overrides.yaml`. Hệ thống chỉ giữ một backup gần nhất; backup mới sẽ thay thế backup cũ. Nếu một bước thất bại, transaction tự khôi phục các file cũ.

Mã ĐT mới chỉ cần Mã ĐT, Tên ĐT và đúng danh mục. Khi xóa Mã ĐT mới, chương trình xóa dòng khỏi workbook local, dọn alias và giữ tombstone để dữ liệu lịch sử không suy lại mã đã xóa. Hãy đóng workbook danh mục trong Excel trước khi áp dụng hoặc xóa.

### Loại thanh toán

1. Chọn `Loại thanh toán` ở thanh điều hướng.
2. Chọn một loại đang có hoặc bấm `Thêm loại thanh toán`.
3. Nhập tên loại và các alias nhận diện từ nội dung chuyển khoản.
4. Bấm `Áp dụng`; chương trình kiểm tra trùng/quá chung, backup rồi cập nhật `config/reason_aliases.yaml`.

Mã kỹ thuật được tạo và quản lý tự động. Các cấu hình suy theo Mã ĐT/tên đối tượng vẫn được giữ nguyên và không hiển thị trên giao diện.

### Nghiệp vụ kế toán

1. Chọn `Nghiệp vụ kế toán` ở thanh điều hướng.
2. Các nghiệp vụ có sẵn được hiển thị ở chế độ chỉ xem nhưng có thể tạm ngưng hoặc kích hoạt lại.
3. Bấm `Thêm nghiệp vụ`, nhập Tên nghiệp vụ, Tài khoản, Luồng và alias nhận diện từ nội dung chuyển khoản.
4. Nghiệp vụ do người dùng thêm có thể chỉnh sửa, tạm ngưng hoặc xóa; nghiệp vụ có sẵn không thể xóa.
5. Bấm `Áp dụng`; chương trình backup rồi hợp nhất rule user vào `config/default_rules.yaml`.

Một nghiệp vụ chỉ thuộc một luồng. Alias có thể trùng giữa hai luồng khác nhau nhưng không được trùng trong cùng luồng. Thu/Chi tiền mặt tự dùng tài khoản `1111`.

Dữ liệu quản lý của ba module được tách tại `data/rule_manager/object_rules.user.json`, `payment_rules.user.json` và `accounting_rules.user.json`. Mỗi lần áp dụng đều tạo backup mới, thay thế backup trước đó và tự khôi phục nếu xuất bản thất bại.

## 6. File Input

- Sao kê ACB/MSB/VCB: `input/statements/`
- Danh mục phải thu: `input/DS mã đối tượng phải thu.xlsx`
- Danh mục phải trả: `input/DS mã đối tượng phải trả.xlsx`
- File quy luật đang dùng: `config/default_rules.yaml`

Chương trình hiện dùng rule YAML trực tiếp, không đọc file quy luật Excel khi chạy.

## 7. Nguyên Tắc An Toàn

- Không chắc thì đưa vào `EXCEPTION`.
- Bảo hiểm luôn không xử lý tự động.
- Mã ĐT công ty mình bị chặn tuyệt đối.
- Mọi dòng phải qua accounting verifier trước khi vào RPA output.
