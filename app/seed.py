"""Seeds only slow-changing identity facts. Prices/variants come from Phase 2 ingestion."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models

SEED = [
    ("Tata", "tata", "Nexon", "nexon", "SUV", "Compact SUV"),
    ("Tata", "tata", "Curvv", "curvv", "SUV", "SUV Coupe"),
    ("Hyundai", "hyundai", "Creta", "creta", "SUV", "Midsize SUV"),
    ("Hyundai", "hyundai", "Venue", "venue", "SUV", "Compact SUV"),
    ("Kia", "kia", "Seltos", "seltos", "SUV", "Midsize SUV"),
    ("Mahindra", "mahindra", "Thar Roxx", "thar-roxx", "SUV", "Lifestyle Off-roader"),
    ("Mahindra", "mahindra", "XUV 3XO", "xuv-3xo", "SUV", "Compact SUV"),
    ("Maruti Suzuki", "maruti-suzuki", "Swift", "swift", "Hatchback", "Premium Hatchback"),
    ("Maruti Suzuki", "maruti-suzuki", "Dzire", "dzire", "Sedan", "Compact Sedan"),
    ("Honda", "honda", "City", "city", "Sedan", "Midsize Sedan"),
]


def seed(db: Session) -> None:
    for bname, bslug, mname, mslug, body, seg in SEED:
        brand = db.scalars(select(models.Brand).where(models.Brand.slug == bslug)).first()
        if not brand:
            brand = models.Brand(name=bname, slug=bslug)
            db.add(brand)
            db.flush()
        exists = db.scalars(select(models.CarModel).where(
            models.CarModel.brand_id == brand.id, models.CarModel.slug == mslug)).first()
        if not exists:
            db.add(models.CarModel(brand_id=brand.id, name=mname, slug=mslug,
                                   body_type=body, segment=seg))
    db.commit()


if __name__ == "__main__":
    from .db import Base, SessionLocal, engine
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed(s)
    print("seeded")
