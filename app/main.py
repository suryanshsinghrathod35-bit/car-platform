from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from . import models, schemas
from .db import Base, engine, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Indian Car Platform", lifespan=lifespan)


def _model_out(m: models.CarModel) -> dict:
    return dict(id=m.id, name=m.name, slug=m.slug, body_type=m.body_type,
                segment=m.segment, brand_name=m.brand.name, brand_slug=m.brand.slug)


def _get_model(db: Session, brand_slug: str, model_slug: str) -> models.CarModel:
    m = db.scalars(
        select(models.CarModel).join(models.Brand)
        .where(models.Brand.slug == brand_slug, models.CarModel.slug == model_slug)
        .options(joinedload(models.CarModel.brand), joinedload(models.CarModel.variants))
    ).unique().first()
    if not m:
        raise HTTPException(404, "model not found")
    return m


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/brands", response_model=list[schemas.BrandOut])
def list_brands(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(models.Brand)
        .order_by(models.Brand.name)
        .offset(offset)
        .limit(limit)
    ).all()


@app.get("/models", response_model=list[schemas.CarModelOut])
def list_models(
    brand: str | None = None,
    body_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(models.CarModel).join(models.Brand).options(joinedload(models.CarModel.brand))
    if brand:
        q = q.where(
            or_(
                func.lower(models.Brand.slug) == brand.lower(),
                func.lower(models.Brand.name) == brand.lower(),
            )
        )
    if body_type:
        q = q.where(func.lower(models.CarModel.body_type) == body_type.lower())
    q = q.order_by(models.Brand.name, models.CarModel.name).offset(offset).limit(limit)
    return [_model_out(m) for m in db.scalars(q).unique().all()]


@app.get("/models/{brand}/{model}", response_model=schemas.CarModelDetail)
def model_detail(brand: str, model: str, db: Session = Depends(get_db)):
    m = _get_model(db, brand, model)
    ratings = db.scalars(select(models.SafetyRating)
                         .where(models.SafetyRating.model_id == m.id)
                         .order_by(models.SafetyRating.external_id)).all()
    return {**_model_out(m), "variants": m.variants, "safety_ratings": ratings}


@app.get("/safety/bncap", response_model=list[schemas.SafetyRatingSummary])
def list_bncap(
    mapped: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(models.SafetyRating).where(models.SafetyRating.agency == "BNCAP")
    if mapped is True:
        q = q.where(models.SafetyRating.model_id.is_not(None))
    elif mapped is False:
        q = q.where(models.SafetyRating.model_id.is_(None))
    return db.scalars(q.order_by(models.SafetyRating.external_id).offset(offset).limit(limit)).all()


@app.get("/safety/bncap/{external_id}", response_model=schemas.SafetyRatingDetail)
def bncap_detail(external_id: str, db: Session = Depends(get_db)):
    r = db.scalars(select(models.SafetyRating).where(
        models.SafetyRating.agency == "BNCAP",
        models.SafetyRating.external_id == external_id)).first()
    if not r:
        raise HTTPException(404, "rating not found")
    return r


@app.post("/models/{brand}/{model}/variants",
          response_model=schemas.VariantOut, status_code=201)
def add_variant(brand: str, model: str, body: schemas.VariantIn,
                db: Session = Depends(get_db)):
    m = _get_model(db, brand, model)
    v = models.Variant(model_id=m.id, **body.model_dump())
    db.add(v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "variant already exists")
    db.refresh(v)
    return v
