import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import models
from app.bncap.ingest import run_ingestion
from tests.test_bncap_ingest import DZ, NX, FakeFetcher, pages_of


@pytest.fixture()
def loaded(db, html):
    run_ingestion(db, pages_of(FakeFetcher({DZ: html["dzire"], NX: html["nexon"]}), [DZ, NX]))
    return db


def test_model_detail_includes_its_safety_rating(api, loaded):
    r = api.get("/models/tata/nexon").json()
    assert len(r["safety_ratings"]) == 1
    s = r["safety_ratings"][0]
    assert (s["agency"], s["adult_stars"], s["child_stars"]) == ("BNCAP", 5, 5)
    assert (s["aop_score"], s["aop_max"], s["cop_score"], s["cop_max"]) == (29.41, 32.0, 43.83, 49.0)
    assert s["source_url"].startswith("https://www.bncap.in/vehicle/")
    assert s["last_checked_at"]


def test_untested_car_has_empty_list_not_zero_stars(api, loaded):
    for brand, model in (("hyundai", "creta"), ("maruti-suzuki", "swift"), ("honda", "city")):
        r = api.get(f"/models/{brand}/{model}").json()
        assert r["safety_ratings"] == []


def test_models_without_data_still_work_before_any_ingestion(api):
    assert api.get("/models/tata/nexon").json()["safety_ratings"] == []


def test_bncap_list_and_detail(api, loaded):
    items = api.get("/safety/bncap").json()
    assert [i["external_id"] for i in items] == ["maruti-dzire-gasoline", "tata-nexon"]
    d = api.get("/safety/bncap/tata-nexon").json()
    assert d["frontal_score"] == 14.65 and d["pole_result"] == "OK" and d["revision"] == 2
    assert d["equipment"]["FRONTAL CRASH PROTECTION"]["Frontal airbag"]["driver"] == "YES - STANDARD"
    assert api.get("/safety/bncap/nope").status_code == 404


def test_mapped_filter_and_pagination(api, loaded):
    assert len(api.get("/safety/bncap", params={"mapped": True}).json()) == 2
    assert api.get("/safety/bncap", params={"mapped": False}).json() == []
    assert len(api.get("/safety/bncap", params={"limit": 1, "offset": 1}).json()) == 1
    assert api.get("/safety/bncap", params={"limit": 0}).status_code == 422


def _row(**over):
    base = dict(agency="BNCAP", external_id="x", title="X", adult_stars=5, child_stars=5,
                aop_score=29.0, aop_max=32.0, cop_score=40.0, cop_max=49.0,
                source_url="https://www.bncap.in/vehicle/x/", content_sha256="0" * 64)
    from app.timeutil import utcnow
    base.update(fetched_at=utcnow(), last_checked_at=utcnow())
    base.update(over)
    return models.SafetyRating(**base)


@pytest.mark.parametrize("bad", [
    dict(adult_stars=6), dict(child_stars=-1), dict(aop_score=33.0), dict(cop_score=-0.1),
    dict(aop_max=0), dict(agency="NHTSA"), dict(source_url="lol"),
])
def test_database_rejects_impossible_ratings(db, bad):
    db.add(_row(**bad))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_duplicate_rating_page(db):
    db.add(_row()); db.commit()
    db.add(_row())
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
