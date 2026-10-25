"""Hand-curated map: bncap.in page slug -> (brand_slug, model_slug) in OUR database.

Deliberately explicit. No fuzzy name matching: a wrong match would attach one car's
crash-test result to a different car. Pages not listed here are still stored, with
model_id = NULL, and counted as 'unmapped' in the ingestion run.

Not mapped on purpose: EV pages such as tata-nexon-ev and tata-curvv-ev. They are separate
cars with separate ratings, and our car_models table has no powertrain concept yet.
"""
BNCAP_TO_MODEL: dict[str, tuple[str, str]] = {
    "tata-nexon": ("tata", "nexon"),
    "tata-curvv": ("tata", "curvv"),
    "maruti-dzire-gasoline": ("maruti-suzuki", "dzire"),
    "hyundai-venue": ("hyundai", "venue"),
    "kia-seltos": ("kia", "seltos"),
    "mahindra-thar-roxx": ("mahindra", "thar-roxx"),
    "mahindra-xuv-3xo": ("mahindra", "xuv-3xo"),
}
