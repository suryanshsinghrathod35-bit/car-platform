"""Parsers for bncap.in. Pure functions: text in, plain data out. No network, no database.

Rule: never guess. If the page is not what we expect, raise ParseError.
"""
from __future__ import annotations

import html as _html
import re

from bs4 import BeautifulSoup


class ParseError(ValueError):
    """The page does not look like what we expect."""


NUM = r"(\d+(?:\.\d+)?)"
MONTHS = ("January|February|March|April|May|June|July|August|"
          "September|October|November|December")


def _clean(s: str) -> str:
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _t(el) -> str:
    return _clean(el.get_text(" ", strip=True))


def _rows(table) -> list[list[str]]:
    out = []
    for tr in table.find_all("tr"):
        cells = [_t(c) for c in tr.find_all(["th", "td"])]
        if any(cells):
            out.append(cells)
    return out


def _slug_from_url(url: str | None) -> str | None:
    m = re.search(r"/vehicle/([^/?#]+)/?", url or "")
    return m.group(1) if m else None


def _pair(txt: str, label: str) -> tuple[float, float] | tuple[None, None]:
    """'14.17 out of 16.00 <label>' -> (14.17, 16.0)"""
    m = re.search(rf"{NUM} out of {NUM} {label}", txt, re.I)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def _pair_max(txt: str, label: str) -> tuple[float, float] | tuple[None, None]:
    """'23.57 (max. 24.00) Dynamic score' -> (23.57, 24.0)"""
    m = re.search(rf"{NUM} \(max\. {NUM}\) {label}", txt, re.I)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def parse_vehicle_page(html: str, source_url: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    canonical = soup.find("link", rel="canonical")
    slug = _slug_from_url((canonical.get("href") if canonical else None) or source_url)
    if not slug:
        raise ParseError("not a vehicle page: no /vehicle/<slug>/ canonical URL")

    # Stars live in schema.org rating widgets: first = adult, second = child (DOM order).
    stars = []
    for w in soup.find_all(attrs={"data-widget_type": "rating.default"}):
        rv = w.find(attrs={"itemprop": "ratingValue"})
        if rv is not None and rv.get("content", "").strip().isdigit():
            stars.append(int(rv["content"]))
    if len(stars) < 2:
        raise ParseError(f"expected 2 star-rating widgets, found {len(stars)}")
    adult_stars, child_stars = stars[0], stars[1]
    if not (0 <= adult_stars <= 5 and 0 <= child_stars <= 5):
        raise ParseError(f"star value out of range: {stars}")

    for s in soup(["script", "style"]):
        s.decompose()

    h2 = soup.find("h2")
    title = _t(h2) if h2 else ""
    if not title:
        raise ParseError("no title found")

    warnings: list[str] = []
    # Validity period. Current cars say "June 2025 - Onwards"; discontinued ones say
    # "May 2024- February 2026*" and add a note ("*Sales discontinued ...").
    period_re = re.compile(
        rf"^(?:{MONTHS})\s+\d{{4}}\s*-\s*(?:Onwards|(?:{MONTHS})\s+\d{{4}})\*?$", re.I)
    period = note = is_current = None
    h2_texts = [_t(h) for h in soup.find_all("h2")]
    for t in h2_texts:
        if period_re.match(t):
            period = t.rstrip("*").strip()
            is_current = period.lower().endswith("onwards")
            break
    if period is None:                      # looser fallback: any heading that says "Onwards"
        loose = next((t for t in h2_texts if "onwards" in t.lower()), None)
        if loose:
            period, is_current = loose.rstrip("*").strip(), True
    note = next((t.lstrip("*").strip() for t in h2_texts if t.startswith("*")), None)
    if period is None:
        warnings.append("period label not found")

    totals = {}
    for h in soup.find_all("h6"):
        m = re.match(rf"{NUM}\s*/\s*{NUM}\s+(Adult|Child)$", _t(h), re.I)
        if m:
            totals[m.group(3).lower()] = (float(m.group(1)), float(m.group(2)))
    if "adult" not in totals or "child" not in totals:
        raise ParseError("adult/child score headings not found")
    (aop, aop_max), (cop, cop_max) = totals["adult"], totals["child"]
    for name, sc, mx in (("AOP", aop, aop_max), ("COP", cop, cop_max)):
        if not (0 <= sc <= mx and mx > 0):
            raise ParseError(f"{name} score {sc}/{mx} is not sane")

    txt = _t(soup)
    frontal, frontal_max = _pair(txt, "Frontal Offset Deformable Barrier Test")
    side, side_max = _pair(txt, "Side Movable Deformable Barrier Test")
    pm = re.search(r"Side pole impact test \(Pole\)\s*:\s*(NOT OK|OK|N/?A|PASS|FAIL)", txt, re.I)
    pole = pm.group(1).upper() if pm else None
    dyn, dyn_max = _pair_max(txt, "Dynamic score")
    crs, crs_max = _pair_max(txt, "CRS installation score")
    veh, veh_max = _pair_max(txt, "Vehicle assessment score")
    for label, val in (("frontal", frontal), ("side", side), ("pole", pole),
                       ("child dynamic", dyn), ("CRS install", crs), ("vehicle assessment", veh)):
        if val is None:
            warnings.append(f"{label} breakdown not found")
    if None not in (frontal, side) and abs(frontal + side - aop) > 0.02:
        warnings.append(f"adult parts {frontal}+{side} do not add up to {aop}")
    if None not in (dyn, crs, veh) and abs(dyn + crs + veh - cop) > 0.02:
        warnings.append(f"child parts {dyn}+{crs}+{veh} do not add up to {cop}")

    spec, equipment, restraints, applic_tables = {}, {}, [], []
    for table in soup.find_all("table"):
        rows = _rows(table)
        if not rows:
            continue
        first = rows[0]
        lowered = {c.lower() for c in first}
        flat = _t(table)
        if first[0].lower().startswith("tested vehicle model"):
            spec = {r[0]: r[1] for r in rows if len(r) >= 2}
        elif {"driver", "passenger", "rear"} <= lowered:
            section = "General"
            for cells in rows[1:]:
                label, vals = cells[0], (cells[1:] + ["", "", ""])[:3]
                if not any(vals):
                    section = label
                    continue
                d, p, r = vals
                item = {"all": d} if (d and not p and not r) else {
                    "driver": d, "passenger": p, "rear": r}
                equipment.setdefault(section, {})[label] = item
        elif "child restraint" in lowered and "dynamic score" in lowered:
            for cells in rows[1:]:
                if len(cells) < 6:
                    continue
                fm = re.search(rf"Front {NUM} \({NUM} max\)", cells[2])
                sm = re.search(rf"Side {NUM} \({NUM} max\)", cells[2])
                restraints.append({
                    "child": cells[0], "restraint": cells[1],
                    "front": float(fm.group(1)) if fm else None,
                    "side": float(sm.group(1)) if sm else None,
                    "crs_type": cells[3], "adjust": cells[4], "position": cells[5]})
        elif re.search(r"rating applies|Revision|Sr\.? ?No|Month & Year of Assessment|Ratings Applicability", flat, re.I):
            applic_tables.append(rows)
    if not spec:
        warnings.append("specifications table not found")
    if not equipment:
        warnings.append("safety equipment table not found")
    if not applic_tables:
        warnings.append("ratings applicability tables not found")
    elif not any(len(r) > 1 for rows in applic_tables for r in rows):
        warnings.append("no applicable-variant rows found")

    applic_text = " ".join(" ".join(" ".join(r) for r in rows) for rows in applic_tables)
    # The assessment date is a table cell that is *only* "<Month> <Year>". (A looser search
    # also hits "AIS-197 Version- September 2023" in the heading, which is not the date.)
    assessed_on = next((c for rows in applic_tables for r in rows for c in r
                        if re.fullmatch(rf"(?:{MONTHS})\s+\d{{4}}", c)), None)
    rev = [(int(n), d) for n, d in re.findall(r"Revision\s*(\d+)\s*-\s*([A-Za-z]+\.?\s+\d{4})", applic_text)]
    revision, revision_text = max(rev) if rev else (None, None)
    if assessed_on is None:
        warnings.append("assessment date not found")

    pdf = next((a["href"] for a in soup.find_all("a", href=True)
                if a["href"].lower().split("?")[0].endswith(".pdf")), None)

    def _num(key, pattern=r"\d+"):
        m = re.search(pattern, spec.get(key, ""))
        return int(m.group(0)) if m else None

    return {
        "external_id": slug, "title": title, "period_label": period,
        "period_note": note, "is_current": is_current,
        "adult_stars": adult_stars, "child_stars": child_stars,
        "aop_score": aop, "aop_max": aop_max, "cop_score": cop, "cop_max": cop_max,
        "frontal_score": frontal, "frontal_max": frontal_max,
        "side_score": side, "side_max": side_max, "pole_result": pole,
        "cop_dynamic": dyn, "cop_dynamic_max": dyn_max,
        "cop_crs_install": crs, "cop_crs_install_max": crs_max,
        "cop_vehicle_assess": veh, "cop_vehicle_assess_max": veh_max,
        "tested_variant": spec.get("Tested Vehicle Model & Variant"),
        "body_type": spec.get("Body Type"),
        "crash_test_weight_kg": _num("Crash Test Weight (kg)"),
        "country_of_origin": spec.get("Country of Origin"),
        "publication_year": _num("Year of Publication", r"\d{4}"),
        "assessed_on_text": assessed_on,
        "revision": revision, "revision_text": revision_text,
        "fact_sheet_url": pdf,
        "equipment": equipment, "child_restraints": restraints,
        "applicability": applic_tables, "parse_warnings": warnings,
    }


def parse_list_page(html: str) -> list[dict]:
    """The ratings index page -> [{'url':..., 'title':...}] in page order, de-duplicated."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.select("a.listingtitle[href]"):
        url = a["href"].strip()
        if "/vehicle/" in url and url not in seen:
            seen.add(url)
            out.append({"url": url, "title": _t(a)})
    return out


def _locs(xml: str) -> list[tuple[str, str | None]]:
    # Regex, not an XML parser: sitemaps are untrusted input, and this is immune to XXE.
    out = []
    for block in re.findall(r"<(?:url|sitemap)>(.*?)</(?:url|sitemap)>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        if loc:
            out.append((_html.unescape(loc.group(1)), mod.group(1) if mod else None))
    return out


def parse_sitemap_index(xml: str) -> list[str]:
    """wp-sitemap.xml -> URLs of the vehicle sitemaps."""
    return [u for u, _ in _locs(xml) if "-posts-vehicle-" in u]


def parse_vehicle_sitemap(xml: str) -> list[tuple[str, str | None]]:
    """A vehicle sitemap -> [(url, lastmod)]."""
    return [(u, m) for u, m in _locs(xml) if "/vehicle/" in u]
