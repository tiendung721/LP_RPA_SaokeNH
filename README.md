# Bank Agent Project

Accounting Agent offline để xử lý sao kê ACB/MSB/VCB, phân loại báo nợ/báo có, nhận diện nghiệp vụ kế toán, suy luận mã đối tượng và sinh file trung gian cho RPA nhập VACOM.

Phiên bản hiện tại dùng kiến trúc mức 2: rule + entity extraction + alias/fuzzy matching + ML offline fallback + accounting verifier. Không dùng LLM/API cloud.

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

## 2. Output Cho RPA

backendFile chạy tạm cho RPA: `output/rpa_input.xlsx`

- `BAO_NO_INPUT`: chỉ dòng báo nợ OK để RPA nhập luồng báo nợ ngân hàng.
- `BAO_CO_INPUT`: chỉ dòng báo có OK để RPA nhập luồng báo có ngân hàng.
- `EXCEPTION`: dòng lỗi, chưa chắc chắn, thiếu mã đối tượng, bảo hiểm, hoặc bị verifier chặn.
- `SUMMARY`: thống kê số dòng và tổng tiền.
- `RPA_TASKS`: mapping giữa dòng input và dòng trạng thái bền vững.
- Cột `Lí do` trong các sheet input có thể xuất TCVN3 cho VACOM bằng `output.rpa_reason_encoding: "tcvn3"`; khi bật chế độ này, file có thêm cột `Lí do Unicode` ngay bên cạnh để đọc/đối chiếu. Dữ liệu config/audit/summary vẫn giữ Unicode.

Các sheet input có các cột nghiệp vụ sau. Cột `Tỷ giá` để trống với giao dịch thường và có giá trị với giao dịch ngoại tệ:

```text
BAO_NO/BAO_CO/CHI_TIEN_MAT:
Ngày CT | Mã ĐT | Lí do | Người nhận tiền | TK nợ | TK có | Thành tiền | Tỷ giá | Ngân hàng

THU_TIEN_MAT:
Ngày CT | Mã ĐT | Lí do | Người nộp tiền | TK nợ | TK có | Thành tiền | Tỷ giá | Ngân hàng
```

File legacy tracking: `output/rpa_tracking.json`

- File JSON này không còn được tạo/cập nhật trong luồng vận hành thường ngày.
- Nếu còn tồn tại từ bản cũ thì chỉ xem như dữ liệu lịch sử/debug; trạng thái RPA hiện lấy từ `output/rpa_summary.xlsx`.

File review mã đối tượng: `output/object_match_review.xlsx`

- `OBJECT_ERRORS`: các dòng còn lỗi `Mã ĐT`, top candidates và nhóm nguyên nhân.
- `SUMMARY`: thống kê theo nhóm lỗi, ngân hàng, use case và hint.

Khi người dùng mở `output/rpa_input.xlsx` để bỏ bớt dòng trước khi PAD nhập:

- Nên xóa cả dòng trong Excel bằng thao tác Delete row; hide/filter dòng không làm PAD bỏ qua.
- Nếu người dùng lỡ chỉ xóa nội dung ô, hãy chạy bước dọn file trước khi PAD đọc lại workbook:

```powershell
.\.venv\Scripts\python.exe sanitize_rpa_input.py --input-file ".\output\rpa_input.xlsx"
```

- Trong PAD, chèn command trên ngay sau bước `PROMOTE_REVIEWED_EXCEPTIONS` thành công và trước bước `ARCHIVE_RPA_INPUT`/đọc các sheet `*_INPUT`. Với nhánh chạy file input cũ, chèn sau `PROMOTE_REVIEWED_EXCEPTIONS_OLD_FILE`.

File trạng thái bền vững: `output/rpa_summary.xlsx`

- Sheet `RPA_SUMMARY` lưu từng giao dịch theo `transaction_uid`, file/sheet/dòng gốc và trạng thái RPA.
- Người dùng quản lý trực tiếp 3 cột: `rpa_status`, `voucher_no`, `rpa_message`.
- Cột `rpa_status` có dropdown, chỉ dùng `chua_nhap` hoặc `hoan_thanh`.
- Trạng thái `hoàn thành` sẽ không được đưa lại vào `rpa_input.xlsx` ở các lần chạy sau.
- Chỉ có 2 trạng thái bền vững: `chưa nhập` và `hoàn thành`.
- Các trạng thái cũ như `lỗi`, `đang nhập`, `cần kiểm tra`, `bỏ qua` sẽ được chuẩn hóa về `chưa nhập`.
- Khi PAD gọi cập nhật `hoàn thành` cho một dòng, dòng đó được ghi trạng thái `hoàn thành` ngay và sẽ không được đưa lại vào `rpa_input.xlsx` ở lần chạy sau.
- `finalize-run` vẫn có thể gọi ở cuối flow để tương thích và xử lý dữ liệu cũ, nhưng không còn là điều kiện bắt buộc để khóa dòng đã nhập.
- Nếu PAD abort giữa chừng, abort run chỉ reset các dòng lỗi/tạm trong run đó; các dòng đã `hoàn thành` không bị đụng.
- Trước khi agent/PAD cập nhật trạng thái, hãy đóng `rpa_summary.xlsx`; nếu file đang mở, script sẽ báo cần đóng Excel rồi chạy lại.

## 3. Config Quan Trọng

- `config/own_company.yaml`: khai báo công ty mình để không bao giờ chọn nhầm mã ĐT như `LE PHAM`.
- `config/object_aliases.yaml`: alias thực tế trên sao kê, ví dụ `KBB`, `PETROLIMEX`, `VINH LONG`, `VSICO`.
- `config/reason_aliases.yaml`: alias loại thanh toán để sinh `Lí do` chi tiết, ví dụ `cước vận chuyển`, `phí cảng vụ`, `tiền thuê văn phòng`.
- `config/default_rules.yaml`: rule nghiệp vụ kế toán.
- `config/ml.yaml`: đường dẫn model ML offline.

Khi gặp mã ĐT hay sai, ưu tiên bổ sung alias vào `object_aliases.yaml` trước. Đây là cách ổn định và dễ kiểm toán nhất.

## 4. Feedback Và Train ML Offline

Template feedback:

```text
data/training/reviewed_transactions.xlsx
```

Kế toán có thể điền các cột:

- `correct_use_case`
- `correct_account`
- `correct_object_code`
- `correct_object_name`
- `review_status`

Build dữ liệu training từ summary Excel:

```powershell
python -m src.ml.build_training_data --summary output\rpa_summary.xlsx
```

Nếu cần khai thác file JSON cũ:

```powershell
python -m src.ml.build_training_data --tracking output\rpa_tracking.json
```

Train model phân loại giao dịch:

```powershell
python -m src.ml.train_models --feedback data\training\reviewed_transactions.xlsx
```

Model sẽ lưu vào:

```text
models/transaction_classifier.joblib
```

Nếu chưa có model, chương trình vẫn chạy bình thường bằng rule + entity + alias + fuzzy.

## 5. Chạy Test

```powershell
python -m pytest --basetemp .pytest_tmp
```

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
- ML không ghi thẳng vào RPA output; mọi dòng phải qua accounting verifier.
