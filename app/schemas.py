from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .enums import FuelType, Transmission


class VariantIn(BaseModel):
    name: str
    fuel_type: FuelType
    transmission: Transmission
    ex_showroom_price_inr: int | None = None
    source_url: str | None = None
    last_verified: datetime | None = None

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str | None) -> str | None:
        if v is not None:
            if len(v) > 500:
                raise ValueError("source_url must be at most 500 characters")
            parsed = urlparse(v)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("source_url must parse as http or https with a non-empty host")
        return v

    @field_validator("last_verified")
    @classmethod
    def validate_last_verified(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            now_utc = datetime.now(timezone.utc)
            if v.tzinfo is None:
                v_utc = v.replace(tzinfo=timezone.utc)
                v_naive = v
            else:
                v_utc = v.astimezone(timezone.utc)
                v_naive = v_utc.replace(tzinfo=None)
            if v_utc > now_utc + timedelta(minutes=5):
                raise ValueError("last_verified cannot be more than 5 minutes in the future")
            return v_naive
        return v

    @model_validator(mode="after")
    def price_needs_provenance(self):
        if self.ex_showroom_price_inr is not None:
            if self.ex_showroom_price_inr <= 0:
                raise ValueError("price must be positive")
            if not self.source_url or not self.last_verified:
                raise ValueError("a price requires source_url and last_verified")
        return self


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    fuel_type: str
    transmission: str
    ex_showroom_price_inr: int | None = None
    source_url: str | None = None
    last_verified: datetime | None = None


class CarModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    body_type: str
    segment: str
    brand_name: str
    brand_slug: str


class CarModelDetail(CarModelOut):
    variants: list[VariantOut] = []


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
