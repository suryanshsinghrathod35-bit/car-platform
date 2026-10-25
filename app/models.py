from datetime import datetime
from sqlalchemy import (CheckConstraint, ForeignKey, Integer, String,
                        UniqueConstraint, DateTime)
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
