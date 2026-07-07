from src.entity_extractor import OwnCompanyConfig
from src.object_matcher import ObjectMatcher


def test_match_object_by_simplified_name():
    matcher = ObjectMatcher.from_records(
        [{"code": "WANHAI", "name": "Công ty TNHH Wan Hai Việt Nam"}],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="TT CHO WAN HAI BL 040GX03571", counterparty_hint="WAN HAI")
    assert result.status == "OK"
    assert result.code == "WANHAI"


def test_ambiguous_object_match():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "ABC1", "name": "Công ty ABC"},
            {"code": "ABC2", "name": "ABC"},
        ],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="THANH TOAN ABC", counterparty_hint="ABC")
    assert result.status == "AMBIGUOUS"


def test_no_object_match():
    matcher = ObjectMatcher.from_records([{"code": "AAA", "name": "Công ty AAA"}], min_score=80, min_gap=8)
    result = matcher.match(description="THANH TOAN ZZZ")
    assert result.status == "NOT_FOUND"


def test_match_object_from_catalog_phrase_in_description_without_counterparty():
    matcher = ObjectMatcher.from_records(
        [{"code": "POSCO SS- VINA", "name": "Công ty cổ phần thép Posco Yamato Vina"}],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(
        description="CONG TY CO PHAN THEP POSCO YAMATO VINA PAYMENT FOR BUYING LIME"
    )
    assert result.status == "OK"
    assert result.code == "POSCO SS- VINA"
    assert result.source == "catalog_phrase"


def test_full_catalog_phrase_beats_single_token_variant_in_hint():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "VULAM", "name": "Công ty TNHH Vũ Lâm"},
            {"code": "XMSONGLAM", "name": "Công ty cổ phần xi măng Sông Lam"},
        ],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="TT CHO XI MANG SONG LAM", counterparty_hint="XI MANG SONG LAM")
    assert result.status == "OK"
    assert result.code == "XMSONGLAM"
    assert result.source == "catalog_phrase"


def test_short_entity_phrase_with_multiple_real_objects_stays_ambiguous():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "KSTHIENSON", "name": "Công ty cổ phần xây dựng và khoáng sản Thiên Sơn"},
            {"code": "THIENSON", "name": "Công ty TNHH nguyên liệu Thiên Sơn"},
        ],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="TT CHO THIEN SON", counterparty_hint="THIEN SON")
    assert result.status == "AMBIGUOUS"


def test_broad_alias_collision_does_not_auto_select_one_object():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "VINACONTROL HP", "name": "Công ty cổ phần Vinacontrol Hải Phòng"},
            {"code": "VINACONTROL QN", "name": "Công ty cổ phần Vinacontrol Quảng Ninh"},
        ],
        min_score=80,
        min_gap=8,
        aliases={"VINACONTROL HP": ["VINACONTROL"]},
    )
    result = matcher.match(description="THANH TOAN CHO VINACONTROL", counterparty_hint="VINACONTROL")
    assert result.status == "AMBIGUOUS"
    assert result.code == "ERROR"
    assert all(candidate.source != "alias_match" for candidate in result.candidates)


def test_short_document_alias_does_not_override_real_counterparty():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "HD", "name": "Xí nghiệp xếp dỡ Hoàng Diệu cảng Hải Phòng"},
            {"code": "QUANGMINH", "name": "Công ty Quang Minh"},
        ],
        min_score=80,
        min_gap=8,
        aliases={"HD": ["HD", "XI NGHIEP XEP DO HOANG DIEU CANG HAI PHONG"]},
    )
    result = matcher.match(
        description="LE PHAM THANH TOAN TIEN PHONG CHO CTY QUANG MINH THEO HD 1491",
        counterparty_hint="QUANG MINH",
    )
    assert result.status == "OK"
    assert result.code == "QUANGMINH"
    assert all(candidate.code != "HD" or candidate.source != "alias_match" for candidate in result.candidates)


def test_short_brand_alias_can_still_match_when_not_blocked():
    matcher = ObjectMatcher.from_records(
        [{"code": "KBB", "name": "Công ty TNHH Tư Vấn Công Nghệ Cao KBB"}],
        min_score=80,
        min_gap=8,
        aliases={"KBB": ["KBB"]},
    )
    result = matcher.match(description="LE PHAM CT CHO KBB HD 359", counterparty_hint="KBB")
    assert result.status == "OK"
    assert result.code == "KBB"


def test_weak_alias_in_description_does_not_override_counterparty_hint():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "KBB", "name": "Công ty TNHH Tư Vấn Công Nghệ Cao KBB"},
            {"code": "QUANGMINH", "name": "Công ty Quang Minh"},
        ],
        min_score=80,
        min_gap=8,
        aliases={"KBB": ["KBB"]},
    )
    result = matcher.match(
        description="LE PHAM THANH TOAN CHO QUANG MINH NOI DUNG KBB",
        counterparty_hint="QUANG MINH",
    )
    assert result.status == "OK"
    assert result.code == "QUANGMINH"
    assert all(candidate.code != "KBB" or candidate.source != "alias_match" for candidate in result.candidates)


def test_generic_single_word_alias_does_not_match_goods_description():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "LIME", "name": "Công ty Lime"},
            {"code": "POSCO SS- VINA", "name": "Công ty cổ phần thép Posco Yamato Vina"},
        ],
        min_score=80,
        min_gap=8,
        aliases={"LIME": ["LIME"]},
    )
    result = matcher.match(
        description="CONG TY CO PHAN THEP POSCO YAMATO VINA PAYMENT FOR BUYING LIME"
    )
    assert result.status == "OK"
    assert result.code == "POSCO SS- VINA"
    assert all(candidate.code != "LIME" or candidate.source != "alias_match" for candidate in result.candidates)


def test_alphanumeric_payment_alias_does_not_override_counterparty_phrase():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "TCT", "name": "Tổng cục thuế"},
            {"code": "EVN", "name": "Công ty Điện lực Hải Phòng"},
        ],
        min_score=80,
        min_gap=8,
        aliases={
            "TCT": ["PH03000018671"],
            "EVN": ["CONG TY DIEN LUC HAI PHONG"],
        },
    )
    result = matcher.match(
        description="PH03000018671 THANH TOAN TIEN DIEN KY HOA DON THANG 4/2026",
        counterparty_hint="DIEN LUC HAI PHONG TCT DL MIEN BAC",
    )
    assert result.status == "OK"
    assert result.code == "EVN"
    assert all(candidate.code != "TCT" or candidate.source != "alias_match" for candidate in result.candidates)


def test_medium_fuzzy_description_match_does_not_auto_select_short_code():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "NV", "name": "Nam Việt"},
            {"code": "PTSC", "name": "Công ty dịch vụ kỹ thuật PTSC Thanh Hóa"},
        ],
        min_score=80,
        min_gap=8,
        ambiguous_min_score=90,
    )
    result = matcher.match(
        description="CT TNHH LE PHAM TT CHO CANG DVKT DAU KHI QBINH HD 794",
        counterparty_hint="CHI NHANH PTSC MIEN TRUNG TCT KY THUAT DAU KHI",
    )
    assert result.status == "NOT_FOUND"
    assert result.code == ""
    assert result.candidates


def test_low_confidence_close_candidates_are_not_reported_as_ambiguous():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "PHUAN", "name": "Công ty cổ phần Phú An"},
            {"code": "KHANHHUNG", "name": "Công ty TNHH Khánh Hưng"},
        ],
        min_score=80,
        min_gap=8,
        ambiguous_min_score=90,
    )
    result = matcher.match(description="CTY PHU HUNG THANH TOAN", counterparty_hint="PHU HUNG")
    assert result.status == "NOT_FOUND"


def test_alias_audit_flags_unsafe_collision():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "VINACONTROL HP", "name": "Công ty cổ phần Vinacontrol Hải Phòng"},
            {"code": "VINACONTROL QN", "name": "Công ty cổ phần Vinacontrol Quảng Ninh"},
        ],
        aliases={"VINACONTROL HP": ["VINACONTROL"]},
    )
    rows = matcher.alias_audit_records("payable")
    vinacontrol = next(row for row in rows if row["alias"] == "VINACONTROL")
    assert vinacontrol["risk"] == "unsafe_collision"
    assert vinacontrol["collision_count"] == 2


def test_equivalent_catalog_names_are_merged_before_ambiguity_check():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "CANGSONDUONG", "name": "Công ty TNHH Dịch vụ hàng hải Cảng Sơn Dương"},
            {"code": "HHCANGSONDUONG", "name": "Công ty TNHH Dịch vụ hàng hải Cảng Sơn Dương"},
        ],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="TT CHO HANG HAI CANG SON DUONG", counterparty_hint="HANG HAI CANG SON DUONG")
    assert result.status == "OK"
    assert result.code in {"CANGSONDUONG", "HHCANGSONDUONG"}
    assert len(result.candidates) == 1


def test_match_object_from_tax_code_in_description_without_counterparty():
    matcher = ObjectMatcher.from_records(
        [{"code": "PIL VN", "name": "Công ty TNHH PIL Việt Nam", "tax_code": "0303449450"}],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="PIL VIETNAM CO LTD TAX CODE - 0303449450 PAY INV 397")
    assert result.status == "OK"
    assert result.code == "PIL VN"
    assert result.source == "tax_code"


def test_exact_phrase_override_beats_ambiguous_fuzzy_candidates():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "KSTHIENSON", "name": "Công ty cổ phần xây dựng và khoáng sản Thiên Sơn"},
            {"code": "THIENSON", "name": "Công ty TNHH nguyên liệu Thiên Sơn"},
        ],
        min_score=80,
        min_gap=8,
        exact_phrase_overrides={"CT CHO THIEN SON": "THIENSON"},
    )
    result = matcher.match(description="LE PHAM CT CHO THIEN SON", counterparty_hint="THIEN SON")
    assert result.status == "OK"
    assert result.code == "THIENSON"
    assert result.source == "exact_phrase"


def test_exact_phrase_override_can_match_short_weak_phrase():
    matcher = ObjectMatcher.from_records(
        [
            {"code": "VATCACH", "name": "Công ty TNHH Logistics Interserco Vật Cách"},
            {"code": "ILSHIN TECH", "name": "Công ty TNHH Ilshin Tech Việt Nam"},
        ],
        min_score=80,
        min_gap=8,
        exact_phrase_overrides={"ILS": "VATCACH"},
    )
    result = matcher.match(description="THANH TOAN DICH VU ILS")
    assert result.status == "OK"
    assert result.code == "VATCACH"
    assert result.source == "exact_phrase"


def test_generic_short_code_does_not_match_long_context_word():
    matcher = ObjectMatcher.from_records(
        [{"code": "HANH", "name": "Công ty Hoàng Anh"}],
        min_score=80,
        min_gap=8,
    )
    result = matcher.match(description="THU PHI PHAT HANH BAO LANH THUC HIEN HOP DONG")
    assert result.status == "NOT_FOUND"


def test_own_company_candidate_is_excluded():
    own_company = OwnCompanyConfig(["LE PHAM", "CONG TY TNHH LE PHAM"], ["0200410388"], ["LE PHAM"])
    matcher = ObjectMatcher.from_records(
        [
            {"code": "LE PHAM", "name": "Công ty TNHH Lê Phạm"},
            {"code": "PETRO", "name": "Công ty TNHH MTV Petrolimex Hải Phòng"},
            {"code": "PETROLIMEX", "name": "Tổng công ty hóa dầu PETROLIMEX - CTCP"},
        ],
        min_score=80,
        min_gap=8,
        exact_phrase_overrides={"PETROLIMEX": "PETRO"},
        own_company=own_company,
    )
    result = matcher.match(
        description="LE PHAM THANH TOAN TIEN XANG DAU CHO PETROLIMEX",
        counterparty_hint="PETROLIMEX",
        cleaned_description="THANH TOAN TIEN XANG DAU CHO PETROLIMEX",
    )
    assert result.status == "OK"
    assert result.code == "PETRO"
