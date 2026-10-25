import pytest
from app.bncap.parser import (ParseError, parse_list_page, parse_sitemap_index,
                              parse_vehicle_page, parse_vehicle_sitemap)
from tests.conftest import FIXTURES


def test_dzire_headline_numbers(html):
    d = parse_vehicle_page(html["dzire"])
    assert d["external_id"] == "maruti-dzire-gasoline"
    assert d["title"] == "MARUTI - DZIRE - GASOLINE"
    assert (d["adult_stars"], d["child_stars"]) == (5, 5)
    assert (d["aop_score"], d["aop_max"]) == (29.46, 32.0)
    assert (d["cop_score"], d["cop_max"]) == (41.57, 49.0)
    assert d["parse_warnings"] == []


def test_dzire_breakdown_matches_official_fact_sheet(html):
    """Expected values are read off the official Dzire fact sheet PDF, not off our parser."""
    d = parse_vehicle_page(html["dzire"])
    assert (d["frontal_score"], d["frontal_max"]) == (14.17, 16.0)
    assert (d["side_score"], d["side_max"]) == (15.29, 16.0)
    assert d["pole_result"] == "OK"
    assert (d["cop_dynamic"], d["cop_dynamic_max"]) == (23.57, 24.0)
    assert (d["cop_crs_install"], d["cop_crs_install_max"]) == (12.0, 12.0)
    assert (d["cop_vehicle_assess"], d["cop_vehicle_assess_max"]) == (6.0, 13.0)
    assert d["tested_variant"] == "MARUTI - DZIRE - GASOLINE - LXI 1.2L ISS 5MT"
    assert d["body_type"] == "Sedan (2 rows)"
    assert d["crash_test_weight_kg"] == 1185
    assert d["publication_year"] == 2025
    assert d["assessed_on_text"] == "February 2025"
    assert d["revision"] is None
    assert d["fact_sheet_url"].endswith("FACT-SHEET_Dzire.pdf")


def test_nexon_matches_official_fact_sheet_and_revisions(html):
    d = parse_vehicle_page(html["nexon"])
    assert d["external_id"] == "tata-nexon"
    assert (d["aop_score"], d["cop_score"]) == (29.41, 43.83)
    assert (d["frontal_score"], d["side_score"]) == (14.65, 14.76)
    assert (d["cop_dynamic"], d["cop_vehicle_assess"]) == (22.83, 9.0)
    assert d["assessed_on_text"] == "August 2024"
    assert (d["revision"], d["revision_text"]) == (2, "Aug 2026")
    assert len(d["applicability"]) == 3          # base list + revision 1 + revision 2
    assert d["parse_warnings"] == []


def test_component_scores_add_up_to_totals(html):
    for name in ("dzire", "nexon"):
        d = parse_vehicle_page(html[name])
        assert d["frontal_score"] + d["side_score"] == pytest.approx(d["aop_score"], abs=0.011)
        assert (d["cop_dynamic"] + d["cop_crs_install"] + d["cop_vehicle_assess"]
                == pytest.approx(d["cop_score"], abs=0.011))


def test_equipment_and_child_restraint_tables(html):
    d = parse_vehicle_page(html["dzire"])
    eq = d["equipment"]
    assert list(eq) == ["FRONTAL CRASH PROTECTION", "SIDE CRASH PROTECTION",
                        "CHILD PROTECTION", "SAFETY ASSIST TECHNOLOGIES"]
    assert eq["FRONTAL CRASH PROTECTION"]["Frontal airbag"]["driver"] == "YES - STANDARD"
    assert eq["SAFETY ASSIST TECHNOLOGIES"]["Pedestrian protection (AIS-100)"] == {"all": "YES - STANDARD"}
    assert [r["child"] for r in d["child_restraints"]] == ["18-month-old child", "3 years old child"]
    assert d["child_restraints"][1]["front"] == 7.57


def test_list_page_has_all_37_vehicle_links(html):
    items = parse_list_page(html["list"])
    urls = [i["url"] for i in items]
    assert len(items) == len(set(urls)) == 37
    assert "https://www.bncap.in/vehicle/maruti-dzire-gasoline/" in urls
    assert "https://www.bncap.in/vehicle/tata-nexon/" in urls


def test_sitemap_parsers():
    idx = (FIXTURES / "sitemap_index_sample.xml").read_text()
    assert parse_sitemap_index(idx) == ["https://www.bncap.in/wp-sitemap-posts-vehicle-1.xml"]
    veh = parse_vehicle_sitemap((FIXTURES / "sitemap_vehicle_sample.xml").read_text())
    assert [u.rsplit("/", 2)[-2] for u, _ in veh] == ["maruti-dzire-gasoline", "tata-nexon", "tata-nexon-ev"]
    assert veh[0][1] == "2026-10-01T10:19:13+00:00"


# ---- the parser must fail loudly rather than guess ----

def test_list_page_is_not_a_vehicle_page(html):
    with pytest.raises(ParseError):
        parse_vehicle_page(html["list"])


def test_garbage_is_rejected():
    with pytest.raises(ParseError):
        parse_vehicle_page("<html><body>maintenance</body></html>", "https://www.bncap.in/vehicle/x/")


def test_missing_scores_rejected(html):
    broken = html["dzire"].replace("29.46 / 32.00 Adult", "n/a")
    with pytest.raises(ParseError):
        parse_vehicle_page(broken)


def test_impossible_score_rejected(html):
    broken = html["dzire"].replace("29.46 / 32.00 Adult", "35.00 / 32.00 Adult")
    with pytest.raises(ParseError):
        parse_vehicle_page(broken)


def test_star_out_of_range_rejected(html):
    import re
    pattern = r'(itemprop="ratingValue"[^>]*?content=")5(")'
    assert re.search(pattern, html["dzire"]), "fixture no longer has the markup this test edits"
    broken = re.sub(pattern, r"\g<1>7\g<2>", html["dzire"], count=1)
    assert broken != html["dzire"]
    with pytest.raises(ParseError):
        parse_vehicle_page(broken)


def test_changed_breakdown_is_flagged_not_hidden(html):
    broken = html["dzire"].replace("14.17 out of 16.00", "9.99 out of 16.00")
    d = parse_vehicle_page(broken)
    assert any("do not add up" in w for w in d["parse_warnings"])
