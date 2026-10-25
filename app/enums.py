from enum import StrEnum


class FuelType(StrEnum):
    PETROL = "Petrol"
    DIESEL = "Diesel"
    CNG = "CNG"
    HYBRID = "Hybrid"
    EV = "EV"


class Transmission(StrEnum):
    MT = "MT"
    AT = "AT"
    DCT = "DCT"
    CVT = "CVT"
    AMT = "AMT"
