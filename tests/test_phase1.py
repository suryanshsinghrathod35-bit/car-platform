from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base, get_db
from app.main import app
from app.seed import seed


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, autoflush=False)
    with S() as s:
        seed(s)
        yield s


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_seed_has_ten_models_and_is_idempotent(session):
    assert len(session.scalars(select(models.CarModel)).all()) == 10
    seed(session)
    assert len(session.scalars(select(models.CarModel)).all()) == 10
    assert len(session.scalars(select(models.Brand)).all()) == 6


def test_seed_contains_no_prices(session):
    assert session.scalars(select(models.Variant)).all() == []


def test_list_models_filters(client):
    assert len(client.get("/models").json()) == 10
    suvs = client.get("/models", params={"body_type": "SUV"}).json()
    assert len(suvs) == 7 and all(m["body_type"] == "SUV" for m in suvs)
    tata = client.get("/models", params={"brand": "tata"}).json()
    assert {m["name"] for m in tata} == {"Nexon", "Curvv"}


def test_model_detail_and_404(client):
    r = client.get("/models/hyundai/creta")
    assert r.status_code == 200 and r.json()["brand_name"] == "Hyundai"
    assert r.json()["variants"] == []
    assert client.get("/models/hyundai/nope").status_code == 404


def test_add_variant_without_price_ok(client):
    r = client.post("/models/tata/nexon/variants",
                    json={"name": "Test", "fuel_type": "Petrol", "transmission": "MT"})
    assert r.status_code == 201 and r.json()["ex_showroom_price_inr"] is None


def test_price_without_source_rejected(client):
    r = client.post("/models/tata/nexon/variants", json={
        "name": "X", "fuel_type": "Petrol", "transmission": "MT",
        "ex_showroom_price_inr": 800000})
    assert r.status_code == 422


def test_price_with_provenance_accepted(client):
    r = client.post("/models/tata/nexon/variants", json={
        "name": "X", "fuel_type": "Petrol", "transmission": "MT",
        "ex_showroom_price_inr": 800000, "source_url": "https://example.com/p",
        "last_verified": "2026-10-09T10:00:00"})
    assert r.status_code == 201
    assert client.get("/models/tata/nexon").json()["variants"][0]["last_verified"]


def test_negative_price_rejected(client):
    r = client.post("/models/tata/nexon/variants", json={
        "name": "X", "fuel_type": "Petrol", "transmission": "MT",
        "ex_showroom_price_inr": -5, "source_url": "https://e.com",
        "last_verified": "2026-10-09T10:00:00"})
    assert r.status_code == 422


def test_duplicate_variant_409(client):
    body = {"name": "Dup", "fuel_type": "Petrol", "transmission": "MT"}
    assert client.post("/models/tata/nexon/variants", json=body).status_code == 201
    assert client.post("/models/tata/nexon/variants", json=body).status_code == 409


def test_database_itself_blocks_unsourced_price(session):
    """Even if app code is bypassed, the DB constraint must hold."""
    m = session.scalars(select(models.CarModel)).first()
    session.add(models.Variant(model_id=m.id, name="Bad", fuel_type="Petrol",
                               transmission="MT", ex_showroom_price_inr=900000))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_fuel_type_enum_validation(client):
    valid_body = {"name": "EV Variant", "fuel_type": "EV", "transmission": "AT"}
    assert client.post("/models/tata/nexon/variants", json=valid_body).status_code == 201

    invalid_body = {"name": "Solar Variant", "fuel_type": "Solar", "transmission": "MT"}
    r = client.post("/models/tata/nexon/variants", json=invalid_body)
    assert r.status_code == 422


def test_transmission_enum_validation(client):
    valid_body = {"name": "DCT Variant", "fuel_type": "Petrol", "transmission": "DCT"}
    assert client.post("/models/tata/nexon/variants", json=valid_body).status_code == 201

    invalid_body = {"name": "Manual Variant", "fuel_type": "Petrol", "transmission": "Manual"}
    r = client.post("/models/tata/nexon/variants", json=invalid_body)
    assert r.status_code == 422


def test_all_fuel_and_transmission_enums_accepted(client):
    combinations = [
        ("Diesel", "AT"),
        ("CNG", "MT"),
        ("Hybrid", "CVT"),
        ("EV", "AMT"),
    ]
    for i, (fuel, trans) in enumerate(combinations):
        body = {"name": f"Variant {i}", "fuel_type": fuel, "transmission": trans}
        r = client.post("/models/tata/curvv/variants", json=body)
        assert r.status_code == 201
        assert r.json()["fuel_type"] == fuel
        assert r.json()["transmission"] == trans


def test_brands_pagination(client):
    all_brands = client.get("/brands").json()
    assert len(all_brands) == 6

    page = client.get("/brands", params={"limit": 2, "offset": 1}).json()
    assert len(page) == 2
    assert page == all_brands[1:3]

    assert client.get("/brands", params={"limit": 201}).status_code == 422
    assert client.get("/brands", params={"limit": 0}).status_code == 422
    assert client.get("/brands", params={"offset": -1}).status_code == 422


def test_models_pagination(client):
    all_models = client.get("/models").json()
    assert len(all_models) == 10

    page = client.get("/models", params={"limit": 3, "offset": 2}).json()
    assert len(page) == 3
    assert page == all_models[2:5]

    assert client.get("/models", params={"limit": 201}).status_code == 422
    assert client.get("/models", params={"limit": 0}).status_code == 422
    assert client.get("/models", params={"offset": -1}).status_code == 422


def test_database_blocks_invalid_fuel_type_and_transmission(session):
    m = session.scalars(select(models.CarModel)).first()
    session.add(models.Variant(model_id=m.id, name="BadFuel", fuel_type="petrol",
                               transmission="MT"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(models.Variant(model_id=m.id, name="BadTrans", fuel_type="Petrol",
                               transmission="Manual"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_variant_out_from_unknown_fuel_type():
    from app.schemas import VariantOut

    class FakeVariant:
        id = 1
        name = "Concept"
        fuel_type = "Hydrogen"
        transmission = "Direct"
        ex_showroom_price_inr = None
        source_url = None
        last_verified = None

    vo = VariantOut.model_validate(FakeVariant())
    assert vo.id == 1
    assert vo.fuel_type == "Hydrogen"
    assert vo.transmission == "Direct"


def test_source_url_provenance_validation(client):
    valid_payload = {
        "name": "UrlTest",
        "fuel_type": "Petrol",
        "transmission": "MT",
        "ex_showroom_price_inr": 800000,
        "last_verified": "2026-10-09T10:00:00",
    }
    r_lol = client.post("/models/tata/nexon/variants",
                        json={**valid_payload, "source_url": "lol"})
    assert r_lol.status_code == 422

    r_ftp = client.post("/models/tata/nexon/variants",
                        json={**valid_payload, "source_url": "ftp://x.com"})
    assert r_ftp.status_code == 422

    r_ok = client.post("/models/tata/nexon/variants",
                       json={**valid_payload, "source_url": "https://example.com/p"})
    assert r_ok.status_code == 201


def test_last_verified_future_and_past_validation(client):
    from datetime import datetime, timezone, timedelta

    valid_payload = {
        "name": "TimeTest",
        "fuel_type": "Petrol",
        "transmission": "MT",
        "ex_showroom_price_inr": 800000,
        "source_url": "https://example.com/p",
    }
    r_future = client.post("/models/tata/nexon/variants",
                           json={**valid_payload, "last_verified": "2099-01-01T00:00:00"})
    assert r_future.status_code == 422

    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r_past = client.post("/models/tata/nexon/variants",
                         json={**valid_payload, "last_verified": one_hour_ago})
    assert r_past.status_code == 201


def test_case_insensitive_filtering(client):
    suv_lower = client.get("/models", params={"body_type": "suv"}).json()
    suv_upper = client.get("/models", params={"body_type": "SUV"}).json()
    assert len(suv_lower) == 7
    assert suv_lower == suv_upper

    tata_lower = client.get("/models", params={"brand": "tata"}).json()
    tata_upper = client.get("/models", params={"brand": "TATA"}).json()
    assert len(tata_upper) == 2
    assert tata_lower == tata_upper


def test_last_verified_utc_normalization(client):
    base = {
        "fuel_type": "Petrol",
        "transmission": "MT",
        "ex_showroom_price_inr": 800000,
        "source_url": "https://example.com/p",
    }
    # "2026-10-09T10:00:00+05:30" is accepted and returned as "2026-10-09T04:30:00"
    r1 = client.post("/models/tata/nexon/variants",
                     json={**base, "name": "TZ_Offset", "last_verified": "2026-10-09T10:00:00+05:30"})
    assert r1.status_code == 201
    assert r1.json()["last_verified"] == "2026-10-09T04:30:00"

    # "2026-10-09T10:00:00Z" is returned as "2026-10-09T10:00:00"
    r2 = client.post("/models/tata/nexon/variants",
                     json={**base, "name": "TZ_Zulu", "last_verified": "2026-10-09T10:00:00Z"})
    assert r2.status_code == 201
    assert r2.json()["last_verified"] == "2026-10-09T10:00:00"

    # "2026-10-09T10:00:00" (naive) is returned unchanged
    r3 = client.post("/models/tata/nexon/variants",
                     json={**base, "name": "TZ_Naive", "last_verified": "2026-10-09T10:00:00"})
    assert r3.status_code == 201
    assert r3.json()["last_verified"] == "2026-10-09T10:00:00"
