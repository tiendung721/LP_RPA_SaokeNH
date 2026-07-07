from src.reason_aliases import (
    load_object_name_purposes,
    load_object_purpose_defaults,
    load_reason_purposes,
    match_object_name_purpose,
    match_reason_purpose,
)
from src.reason_generator import generate_reason


def test_reason_purpose_loader_blocks_generic_aliases_and_matches_longest(tmp_path):
    alias_file = tmp_path / "reason_aliases.yaml"
    alias_file.write_text(
        """
purposes:
  - code: electricity
    label: "tiền điện"
    aliases:
      - "TIEN DIEN"
      - "TT"
  - code: utilities
    label: "tiền điện nước"
    aliases:
      - "TIEN DIEN NUOC"
""",
        encoding="utf-8",
    )

    purposes = load_reason_purposes(alias_file)

    assert purposes[0].aliases == ("TIEN DIEN",)
    assert match_reason_purpose("TT TIEN DIEN NUOC THANG 3", purposes).code == "utilities"
    assert match_reason_purpose("TT ABC", purposes) is None


def test_reason_purpose_loader_falls_back_to_empty_for_missing_file(tmp_path):
    assert load_reason_purposes(tmp_path / "missing.yaml") == []


def test_object_purpose_defaults_loader_normalizes_object_codes(tmp_path):
    alias_file = tmp_path / "reason_aliases.yaml"
    alias_file.write_text(
        """
object_purpose_defaults:
  CANG-HA: port_service_fee
  "S5 VIET NAM": crew_change_service_fee
""",
        encoding="utf-8",
    )

    defaults = load_object_purpose_defaults(alias_file)

    assert defaults["CANG HA"] == "port_service_fee"
    assert defaults["S5 VIET NAM"] == "crew_change_service_fee"


def test_object_name_purposes_loader_matches_longest_keyword_on_name(tmp_path):
    alias_file = tmp_path / "reason_aliases.yaml"
    alias_file.write_text(
        """
object_name_purposes:
  - keyword: "CANG VU HANG HAI"
    purpose: port_authority_fee
  - keyword: "HOA TIEU"
    purpose: pilotage_fee
""",
        encoding="utf-8",
    )

    rules = load_object_name_purposes(alias_file)

    # Suy nghiệp vụ theo LOẠI công ty, tổng quát cả đối tượng chưa từng gặp.
    assert match_object_name_purpose("Cảng vụ hàng hải Đà Nẵng", rules) == "port_authority_fee"
    assert match_object_name_purpose("Công ty TNHH MTV Hoa Tiêu Hàng Hải KV V", rules) == "pilotage_fee"
    assert match_object_name_purpose("Công ty TNHH Nguyên Liệu Thiên Sơn", rules) == ""


def test_generate_reason_prefers_description_then_default_then_name_category():
    purposes = load_reason_purposes("config/reason_aliases.yaml")
    name_rules = [("CANG VU HANG HAI", "port_authority_fee")]
    defaults = {"KBB": "goods", "VSICO": "sea_freight"}

    def reason(object_code, object_name, description):
        return generate_reason(
            "bao_no",
            debit_account="331",
            credit_account="1121CT",
            object_code=object_code,
            object_name=object_name,
            description=description,
            purposes=purposes,
            object_purpose_defaults=defaults,
            object_name_purposes=name_rules,
        )

    # 1) Mục đích nêu rõ trong nội dung CK thắng mọi nguồn khác.
    assert reason("VSICO", "Cảng vụ hàng hải Hải Phòng", "TT phí hoa tiêu") == "TT phí hoa tiêu (Cảng vụ hàng hải Hải Phòng)"
    # 2) Không có trong nội dung -> default riêng theo Mã ĐT.
    assert reason("VSICO", "Công ty cổ phần hàng hải Vsico", "chuyen khoan") == "TT cước biển (Công ty cổ phần hàng hải Vsico)"
    # 3) Không có default -> suy theo LOẠI đối tượng (tên danh mục).
    assert reason("CVHH-DN", "Cảng vụ hàng hải Đà Nẵng", "chuyen khoan") == "TT phí cảng vụ (Cảng vụ hàng hải Đà Nẵng)"
    # 4) Không suy được gì -> fallback tiền hàng (giữ hành vi cũ, không tạo exception).
    assert reason("ABCXYZ", "Công ty TNHH Vô Danh", "chuyen khoan") == "TT tiền hàng (Công ty TNHH Vô Danh)"


def _reason_from_real_config(object_code, object_name, description):
    return generate_reason(
        "bao_no",
        debit_account="331",
        credit_account="1121CT",
        object_code=object_code,
        object_name=object_name,
        description=description,
        purposes=load_reason_purposes("config/reason_aliases.yaml"),
        object_purpose_defaults=load_object_purpose_defaults("config/reason_aliases.yaml"),
        object_name_purposes=load_object_name_purposes("config/reason_aliases.yaml"),
    )


def test_new_purposes_matched_from_description():
    # Nghiệp vụ mới mined từ thong_ke_ma_dt_ly_do_chung_v2, khớp từ NỘI DUNG chuyển khoản.
    assert _reason_from_real_config("TREE MARINE", "Công ty TNHH Tree Marine", "TT phí đại lý") == "TT phí đại lý (Công ty TNHH Tree Marine)"
    assert _reason_from_real_config("HQHP", "Cục Hải quan thành phố HP", "TT phí hải quan tk xuất khẩu") == "TT phí hải quan (Cục Hải quan thành phố HP)"
    assert _reason_from_real_config("001", "Khách lẻ", "TT phí chứng từ") == "TT phí chứng từ (Khách lẻ)"
    assert _reason_from_real_config("KETSAT", "Công ty TNHH Két Sắt An Toàn", "TT tiền két sắt theo HĐ 698") == "TT tiền két sắt (Công ty TNHH Két Sắt An Toàn)"


def test_new_object_purpose_defaults_when_description_is_generic():
    # Đối tượng có TÊN không lộ nghiệp vụ -> default riêng theo Mã ĐT.
    assert _reason_from_real_config("HAILONG", "Công Ty TNHH Hải Long", "chuyen khoan") == "TT tiền cảng phí (Công Ty TNHH Hải Long)"
    assert _reason_from_real_config("MINHCONG", "Công ty cổ phần TM DV Minh Công", "chuyen khoan") == "TT tiền thuê văn phòng (Công ty cổ phần TM DV Minh Công)"


def test_new_category_rules_generalize_to_unseen_objects():
    # Luật theo LOẠI đối tượng phủ cả đối tượng chưa từng gặp cùng loại.
    assert _reason_from_real_config("HQ-HN", "Cục Hải quan Hà Nội", "chuyen khoan") == "TT phí hải quan (Cục Hải quan Hà Nội)"
    assert _reason_from_real_config("DK-ABC", "Trung tâm đăng kiểm phương tiện giao thông ABC", "chuyen khoan") == "TT phí đăng kiểm (Trung tâm đăng kiểm phương tiện giao thông ABC)"
    assert _reason_from_real_config("QT-XYZ", "Công ty TNHH Cảng Quốc Tế Xyz", "chuyen khoan") == "TT tiền cảng phí (Công ty TNHH Cảng Quốc Tế Xyz)"
    assert _reason_from_real_config("VM-HP", "Bệnh viện ĐKQT Vinmec Hải Phòng", "chuyen khoan") == "TT viện phí thuyền viên (Bệnh viện ĐKQT Vinmec Hải Phòng)"
