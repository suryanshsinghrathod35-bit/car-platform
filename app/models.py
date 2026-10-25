from datetime import datetime
from sqlalchemy import (JSON, CheckConstraint, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base
from .enums import FuelType, Transmission

_fuel_types = ", ".join(repr(e.value) for e in FuelType)
_transmissions = ", ".join(repr(e.value) for e in Transmission)


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    models: Mapped[list["CarModel"]] = relationship(back_populates="brand")


class CarModel(Base):
    __tablename__ = "car_models"
    __table_args__ = (UniqueConstraint("brand_id", "slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(80))
    body_type: Mapped[str] = mapped_column(String(40))
    segment: Mapped[str] = mapped_column(String(60))
    brand: Mapped[Brand] = relationship(back_populates="models")
    variants: Mapped[list["Variant"]] = relationship(back_populates="car_model")


class Variant(Base):
    """Facts layer. Any price MUST carry a source_url and last_verified."""
    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("model_id", "name", "fuel_type", "transmission"),
        CheckConstraint(
            "ex_showroom_price_inr IS NULL OR "
            "(ex_showroom_price_inr > 0 AND source_url IS NOT NULL "
            "AND last_verified IS NOT NULL)",
            name="price_requires_provenance",
        ),
        CheckConstraint(
            f"fuel_type IN ({_fuel_types})",
            name="fuel_type_valid",
        ),
        CheckConstraint(
            f"transmission IN ({_transmissions})",
            name="transmission_valid",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("car_models.id"))
    name: Mapped[str] = mapped_column(String(80))
    fuel_type: Mapped[str] = mapped_column(String(20))
    transmission: Mapped[str] = mapped_column(String(20))
    ex_showroom_price_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    car_model: Mapped[CarModel] = relationship(back_populates="variants")


class SafetyRating(Base):
    """One official crash-test result page. Absence of a row means 'no rating on record',
    never zero stars."""
    __tablename__ = "safety_ratings"
    __table_args__ = (
        UniqueConstraint("agency", "external_id"),
        CheckConstraint("agency IN ('BNCAP', 'GNCAP')", name="agency_valid"),
        CheckConstraint("adult_stars BETWEEN 0 AND 5 AND child_stars BETWEEN 0 AND 5",
                        name="stars_range"),
        CheckConstraint("aop_max > 0 AND aop_score >= 0 AND aop_score <= aop_max",
                        name="aop_range"),
        CheckConstraint("cop_max > 0 AND cop_score >= 0 AND cop_score <= cop_max",
                        name="cop_range"),
        CheckConstraint("source_url LIKE 'http%'", name="source_url_http"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("car_models.id"), nullable=True)
    agency: Mapped[str] = mapped_column(String(10))
    external_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    period_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    adult_stars: Mapped[int] = mapped_column(Integer)
    child_stars: Mapped[int] = mapped_column(Integer)
    aop_score: Mapped[float] = mapped_column(Float)
    aop_max: Mapped[float] = mapped_column(Float)
    cop_score: Mapped[float] = mapped_column(Float)
    cop_max: Mapped[float] = mapped_column(Float)
    frontal_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    frontal_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    side_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    side_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    pole_result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cop_dynamic: Mapped[float | None] = mapped_column(Float, nullable=True)
    cop_dynamic_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    cop_crs_install: Mapped[float | None] = mapped_column(Float, nullable=True)
    cop_crs_install_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    cop_vehicle_assess: Mapped[float | None] = mapped_column(Float, nullable=True)
    cop_vehicle_assess_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    tested_variant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    crash_test_weight_kg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(80), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessed_on_text: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_text: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fact_sheet_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)
    child_restraints: Mapped[list] = mapped_column(JSON, default=list)
    applicability: Mapped[list] = mapped_column(JSON, default=list)
    parse_warnings: Mapped[list] = mapped_column(JSON, default=list)
    # provenance: where it came from and when we last looked (naive UTC)
    source_url: Mapped[str] = mapped_column(String(500))
    content_sha256: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime)
    car_model: Mapped["CarModel | None"] = relationship()


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seen: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    unmapped: Mapped[int] = mapped_column(Integer, default=0)
    aborted: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
