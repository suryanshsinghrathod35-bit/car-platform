"""Fetch -> save raw -> parse -> validate -> upsert -> log. Network access is injectable."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..timeutil import utcnow
from .mapping import BNCAP_TO_MODEL
from .parser import (ParseError, parse_sitemap_index, parse_vehicle_page,
                     parse_vehicle_sitemap)

BASE_URL = "https://www.bncap.in"
AGENCY = "BNCAP"


class FetchError(RuntimeError):
    pass


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


class HttpFetcher:
    """Polite fetcher: identifies itself, obeys robots.txt (fails closed), rate-limits, retries."""
    MAX_BYTES = 8_000_000

    def __init__(self, contact: str, *, delay: float = 3.0, timeout: float = 20.0,
                 retries: int = 2, allow_http: bool = False, sleep=time.sleep):
        if not contact or not ("@" in contact or contact.startswith("http")):
            raise ValueError("contact (an email or URL) is required, so the site owner can reach you")
        self.user_agent = f"CarPlatformBot/0.1 (+{contact})"
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self.allow_http, self._sleep = allow_http, sleep
        self._robots: dict[str, RobotFileParser] = {}
        self._last: float | None = None

    def _request(self, url: str) -> str:
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            if self._last is not None:
                wait = self.delay - (time.monotonic() - self._last)
                if wait > 0:
                    self._sleep(wait)
            req = urllib.request.Request(url, headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read(self.MAX_BYTES + 1)
                    self._last = time.monotonic()
                    if len(raw) > self.MAX_BYTES:
                        raise FetchError(f"response too large: {url}")
                    return raw.decode(resp.headers.get_content_charset() or "utf-8", "replace")
            except urllib.error.HTTPError as e:
                self._last = time.monotonic()
                if e.code == 429 or e.code >= 500:
                    last_err = e
                    self._sleep(min(60, 2 ** attempt * max(self.delay, 1.0)))
                    continue
                raise FetchError(f"HTTP {e.code} for {url}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                self._sleep(min(60, 2 ** attempt * max(self.delay, 1.0)))
        raise FetchError(f"giving up on {url}: {last_err}")

    def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                rp.parse(self._request(origin + "/robots.txt").splitlines())
            except FetchError as e:
                if "HTTP 404" in str(e):
                    rp.parse([])            # no robots.txt means no restrictions
                else:
                    raise FetchError(f"cannot read robots.txt, so not fetching: {e}") from e
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(self.user_agent, url)

    def get(self, url: str) -> str:
        scheme = urlparse(url).scheme
        if scheme != "https" and not (self.allow_http and scheme == "http"):
            raise FetchError(f"refusing non-https URL: {url}")
        if not self._allowed(url):
            raise FetchError(f"blocked by robots.txt: {url}")
        return self._request(url)


def discover(fetcher: Fetcher, base_url: str = BASE_URL) -> list[str]:
    """Vehicle page URLs, via the site's own sitemap (index first, so new sitemap files are found)."""
    urls: list[str] = []
    for sm in parse_sitemap_index(fetcher.get(f"{base_url}/wp-sitemap.xml")):
        for url, _ in parse_vehicle_sitemap(fetcher.get(sm)):
            if url.startswith(base_url + "/vehicle/") and url not in urls:
                urls.append(url)
    return urls


@dataclass
class IngestResult:
    seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    unmapped: int = 0
    aborted: bool = False
    errors: list[str] = field(default_factory=list)


def _resolve_model_id(db: Session, external_id: str) -> int | None:
    target = BNCAP_TO_MODEL.get(external_id)
    if not target:
        return None
    return db.scalars(
        select(models.CarModel.id).join(models.Brand)
        .where(models.Brand.slug == target[0], models.CarModel.slug == target[1])).first()


def upsert_rating(db: Session, parsed: dict, source_url: str, now=None) -> tuple[str, bool]:
    """Returns (status, mapped) where status is created | updated | unchanged."""
    now = now or utcnow()
    digest = hashlib.sha256(
        json.dumps(parsed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    model_id = _resolve_model_id(db, parsed["external_id"])
    row = db.scalars(select(models.SafetyRating).where(
        models.SafetyRating.agency == AGENCY,
        models.SafetyRating.external_id == parsed["external_id"])).first()
    if row is None:
        db.add(models.SafetyRating(agency=AGENCY, model_id=model_id, source_url=source_url,
                                   content_sha256=digest, fetched_at=now,
                                   last_checked_at=now, **parsed))
        status = "created"
    elif row.content_sha256 != digest:
        for k, v in parsed.items():
            setattr(row, k, v)
        row.model_id, row.source_url, row.content_sha256 = model_id, source_url, digest
        row.fetched_at = row.last_checked_at = now
        status = "updated"
    else:
        row.model_id = model_id
        row.last_checked_at = now
        status = "unchanged"
    db.flush()
    return status, model_id is not None


def _save_raw(raw_dir: Path | None, slug: str, html: str, now) -> None:
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{slug}__{now:%Y%m%dT%H%M%SZ}.html").write_text(html, encoding="utf-8")


def run_ingestion(db: Session, pages, *, raw_dir: Path | None = None,
                  max_consecutive_failures: int = 5, source: str = "bncap") -> IngestResult:
    """`pages` yields (source_url, get_html) pairs. One bad page never stops the run, but a run
    of consecutive failures aborts it (the site has probably changed, so stop writing)."""
    res, started, streak = IngestResult(), utcnow(), 0
    for url, get_html in pages:
        res.seen += 1
        try:
            html = get_html()
            parsed = parse_vehicle_page(html, url)
            status, mapped = upsert_rating(db, parsed, url)
            db.commit()
        except (ParseError, FetchError) as e:
            db.rollback()
            res.failed += 1
            streak += 1
            res.errors.append(f"{url}: {e}")
            if streak >= max_consecutive_failures:
                res.aborted = True
                break
            continue
        streak = 0
        setattr(res, status, getattr(res, status) + 1)
        if not mapped:
            res.unmapped += 1
        if status != "unchanged":
            _save_raw(raw_dir, parsed["external_id"], html, utcnow())
    db.add(models.IngestionRun(
        source=source, started_at=started, finished_at=utcnow(), seen=res.seen,
        created=res.created, updated=res.updated, unchanged=res.unchanged,
        failed=res.failed, unmapped=res.unmapped, aborted=res.aborted,
        notes="\n".join(res.errors[:50]) or None))
    db.commit()
    return res


def live_pages(fetcher: Fetcher, limit: int | None = None):
    urls = discover(fetcher)
    for url in (urls[:limit] if limit else urls):
        yield url, (lambda u=url: fetcher.get(u))


def dir_pages(path: Path):
    """Saved pages from a folder (offline/demo). The source URL is the page's own canonical
    URL on bncap.in; files that are not vehicle pages (e.g. the list page) are skipped.
    Note: timestamps will reflect when you ingested the file, not when it was saved."""
    from bs4 import BeautifulSoup
    from .parser import _slug_from_url
    for f in sorted(path.glob("*.html")):
        text = f.read_text(encoding="utf-8")
        link = BeautifulSoup(text, "html.parser").find("link", rel="canonical")
        url = link.get("href") if link else None
        if _slug_from_url(url):
            yield url, (lambda t=text: t)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Bharat NCAP ratings into the database.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true",
                   help="fetch from bncap.in (needs env BNCAP_BOT_CONTACT=<your email or URL>)")
    g.add_argument("--from-dir", type=Path, help="ingest saved .html pages from a folder (offline)")
    ap.add_argument("--limit", type=int, help="only the first N pages (live mode)")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests (min 2)")
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw/bncap"))
    a = ap.parse_args()

    from ..db import Base, SessionLocal, engine
    from ..seed import seed
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        if a.live:
            if a.delay < 2:
                ap.error("--delay must be at least 2 seconds")
            contact = os.getenv("BNCAP_BOT_CONTACT", "")
            if not contact:
                ap.error("set BNCAP_BOT_CONTACT to your email or website, e.g. "
                         "$env:BNCAP_BOT_CONTACT='you@example.com' (PowerShell)")
            pages = live_pages(HttpFetcher(contact, delay=a.delay), a.limit)
        else:
            pages = dir_pages(a.from_dir)
        res = run_ingestion(db, pages, raw_dir=a.raw_dir)
    print(f"seen={res.seen} created={res.created} updated={res.updated} unchanged={res.unchanged} "
          f"failed={res.failed} unmapped={res.unmapped} aborted={res.aborted}")
    for e in res.errors:
        print("  ERROR", e)


if __name__ == "__main__":
    main()
