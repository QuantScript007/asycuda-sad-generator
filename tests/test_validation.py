from sad_generator.validation import ERROR, check_shipment, validate


def _msgs(data):
    return validate(data)


def _clean():
    return {
        "general": {"bl_number": "BL1", "country_of_export": "IN", "invoice_currency": "USD",
                    "delivery_terms": "CIF", "invoice_amount": 150, "total_packages": 5},
        "items": [
            {"hs_code": "1006300099", "description": "Rice", "item_price": 100, "country_origin": "IN",
             "gross_mass": 50, "no_packages": 3},
            {"hs_code": "6403990099", "description": "Sandals", "item_price": 50, "country_origin": "CN",
             "gross_mass": 5, "no_packages": 2},
        ],
    }


def test_clean_shipment_has_no_issues():
    assert check_shipment(_clean()) == []


def test_original_warnings_are_kept():
    msgs = _msgs({"general": {}, "items": [{"hs_code": "1006300099"}]})
    assert "BL number is empty (box 40)." in msgs
    assert "Item 1: description is empty (box 31)." in msgs
    assert "Item 1: item price is empty (box 42)." in msgs


def test_header_checks():
    d = _clean()
    d["general"].update(country_of_export="India", invoice_currency="US", delivery_terms="XYZ")
    msgs = " | ".join(_msgs(d))
    assert "Country of export" in msgs and "box 15" in msgs
    assert "Invoice currency" in msgs
    assert "not a recognised Incoterm" in msgs
    assert any(i.severity == ERROR and i.field == "invoice_currency" for i in check_shipment(d))


def test_declared_totals_are_compared_with_lines():
    d = _clean()
    d["general"]["invoice_amount"] = 400
    d["general"]["total_packages"] = 9
    msgs = _msgs(d)
    assert any("add up to 150.00" in m and "400.00" in m for m in msgs)
    assert any("5 packages" in m and "9" in m for m in msgs)


def test_small_rounding_difference_is_tolerated():
    d = _clean()
    d["general"]["invoice_amount"] = 150.4
    assert _msgs(d) == []


def test_item_checks():
    d = _clean()
    d["items"][0].update(hs_code="10063", country_origin="Indiaa", gross_mass="heavy", item_price=0)
    d["items"][1].update(hs_code="", no_packages=1.5, gross_mass=-2)
    issues = check_shipment(d)
    text = " | ".join(i.message for i in issues)
    assert "Item 1: item price is zero" in text
    assert "Item 1: HS code 010063" in text            # leading zero restored → 6 digits
    assert "Item 1: country of origin" in text
    assert "Item 1: gross mass “heavy” is not a number" in text
    assert "Item 2: HS code is missing" in text
    assert "Item 2: number of packages" in text
    assert "Item 2: gross mass is negative" in text
    assert {i.item for i in issues if i.item} == {1, 2}


def test_non_numeric_price_is_an_error():
    d = _clean()
    d["items"][0]["item_price"] = "abc"
    errs = [i for i in check_shipment(d) if i.severity == ERROR]
    assert errs and errs[0].item == 1 and errs[0].field == "item_price"


def test_duplicate_lines_are_flagged_once():
    d = _clean()
    d["items"].append(dict(d["items"][0]))
    d["general"]["invoice_amount"] = 250
    d["general"]["total_packages"] = 8
    msgs = _msgs(d)
    assert msgs == ["Item 3: looks like a duplicate of item 1."]


def test_service_validate_uses_the_new_checks():
    from sad_generator import service

    assert service.validate({"general": {"bl_number": "X", "invoice_currency": "U"},
                             "items": [{"hs_code": "1006300099", "description": "Rice", "item_price": 1}]})
