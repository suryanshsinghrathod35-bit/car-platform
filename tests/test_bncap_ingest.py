import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import select

from app import models
from app.bncap.ingest import (FetchError, HttpFetcher, discover, dir_pages,
                              run_ingestion)
from tests.conftest import FIXTURES

DZ = "https://www.bncap.in/vehicle/maruti-dzire-gasoline/"
NX = "https://www.bncap.in/vehicle/tata-nexon/"


class FakeFetcher:
    def __init__(self, pages): self.pages, self.calls = pages, []
    def get(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise FetchError(f"HTTP 404 for {url}")
        return self.pages[url]


def pages_of(fetcher, urls):
    return [(u, (lambda u=u: fetcher.get(u))) for u in urls]


def test_ingest_creates_rows_and_maps_models(db, html):
    f = FakeFetcher({DZ: html["dzire"], NX: html["nexon"]})
    res = run_ingestion(db, pages_of(f, [DZ, NX]))
    assert (res.seen, res.created, res.failed, res.unmapped) == (2, 2, 0, 0)
    rows = {r.external_id: r for r in db.scalars(select(models.SafetyRating))}
    assert rows["tata-nexon"].car_model.slug == "nexon"
    assert rows["maruti-dzire-gasoline"].car_model.brand.slug == "maruti-suzuki"
    assert rows["tata-nexon"].source_url == NX
    assert rows["tata-nexon"].fetched_at is not None


def test_second_run_is_unchanged_and_only_touches_last_checked(db, html):
    f = FakeFetcher({DZ: html["dzire"]})
    run_ingestion(db, pages_of(f, [DZ]))
    first = db.scalars(select(models.SafetyRating)).one()
    fetched, checked = first.fetched_at, first.last_checked_at
    res = run_ingestion(db, pages_of(f, [DZ]))
    assert (res.created, res.updated, res.unchanged) == (0, 0, 1)
    assert db.scalars(select(models.SafetyRating)).one().fetched_at == fetched
    assert db.scalars(select(models.SafetyRating)).one().last_checked_at >= checked
    assert len(db.scalars(select(models.SafetyRating)).all()) == 1


def test_changed_page_updates_in_place(db, html):
    run_ingestion(db, pages_of(FakeFetcher({DZ: html["dzire"]}), [DZ]))
    changed = html["dzire"].replace("29.46 / 32.00 Adult", "30.10 / 32.00 Adult")
    res = run_ingestion(db, pages_of(FakeFetcher({DZ: changed}), [DZ]))
    assert (res.created, res.updated) == (0, 1)
    row = db.scalars(select(models.SafetyRating)).one()
    assert row.aop_score == 30.10


def test_unmapped_page_is_stored_with_null_model(db, html):
    ev = html["nexon"].replace("/vehicle/tata-nexon/", "/vehicle/tata-nexon-ev/")
    url = "https://www.bncap.in/vehicle/tata-nexon-ev/"
    res = run_ingestion(db, pages_of(FakeFetcher({url: ev}), [url]))
    assert (res.created, res.unmapped) == (1, 1)
    assert db.scalars(select(models.SafetyRating)).one().model_id is None


def test_one_bad_page_does_not_stop_the_run(db, html):
    bad = "https://www.bncap.in/vehicle/broken/"
    f = FakeFetcher({bad: "<html>oops</html>", DZ: html["dzire"], NX: html["nexon"]})
    res = run_ingestion(db, pages_of(f, [DZ, bad, NX]))
    assert (res.created, res.failed, res.aborted) == (2, 1, False)
    assert "broken" in res.errors[0]


def test_run_aborts_after_consecutive_failures(db, html):
    urls = [f"https://www.bncap.in/vehicle/bad-{i}/" for i in range(8)] + [DZ]
    f = FakeFetcher({**{u: "<html>x</html>" for u in urls}, DZ: html["dzire"]})
    res = run_ingestion(db, pages_of(f, urls), max_consecutive_failures=3)
    assert res.aborted and res.failed == 3 and res.seen == 3
    assert db.scalars(select(models.SafetyRating)).all() == []


def test_run_is_logged(db, html):
    run_ingestion(db, pages_of(FakeFetcher({DZ: html["dzire"]}), [DZ]))
    run = db.scalars(select(models.IngestionRun)).one()
    assert (run.seen, run.created, run.failed) == (1, 1, 0) and run.finished_at >= run.started_at


def test_raw_snapshot_saved_only_when_content_changes(db, html, tmp_path):
    f = FakeFetcher({DZ: html["dzire"]})
    run_ingestion(db, pages_of(f, [DZ]), raw_dir=tmp_path)
    assert len(list(tmp_path.glob("maruti-dzire-gasoline__*.html"))) == 1
    run_ingestion(db, pages_of(f, [DZ]), raw_dir=tmp_path)
    assert len(list(tmp_path.glob("*.html"))) == 1


def test_discover_uses_index_then_vehicle_sitemaps():
    idx = (FIXTURES / "sitemap_index_sample.xml").read_text()
    veh = (FIXTURES / "sitemap_vehicle_sample.xml").read_text()
    f = FakeFetcher({"https://www.bncap.in/wp-sitemap.xml": idx,
                     "https://www.bncap.in/wp-sitemap-posts-vehicle-1.xml": veh})
    urls = discover(f)
    assert len(urls) == 3 and DZ in urls and NX in urls
    assert not any("page-1" in c for c in f.calls)      # never fetched unrelated sitemaps


def test_offline_dir_mode_ingests_saved_pages(db):
    expected = len([p for p in FIXTURES.glob("*.html") if p.stem != "list"])   # vehicle pages only
    assert expected >= 6
    res = run_ingestion(db, dir_pages(FIXTURES))
    assert (res.created, res.failed) == (expected, 0)   # list page and sitemaps are skipped


# ---------------- HttpFetcher against a real local server ----------------

@pytest.fixture()
def server():
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            seen.append((self.path, self.headers.get("User-Agent")))
            if self.path == "/drop":                  # close without answering: a connection reset
                self.close_connection = True
                return
            if self.path == "/flaky":                 # reset on the first request, then fine
                if sum(1 for p, _ in seen if p == "/flaky") == 1:
                    self.close_connection = True
                    return
                body = b"<html>recovered</html>"
            elif self.path == "/robots.txt":
                body = b"User-agent: *\nDisallow: /private/\n"
            elif self.path == "/boom":
                self.send_response(500); self.end_headers(); return
            else:
                body = b"<html>hello</html>"
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers(); self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", seen
    srv.shutdown()


def make(**kw):
    return HttpFetcher("me@example.com", delay=0, allow_http=True, sleep=lambda s: None, **kw)


def test_fetcher_identifies_itself_and_fetches(server):
    base, seen = server
    assert make().get(base + "/page") == "<html>hello</html>"
    assert all(ua.startswith("CarPlatformBot/0.1 (+me@example.com)") for _, ua in seen)


def test_fetcher_obeys_robots_txt(server):
    base, seen = server
    with pytest.raises(FetchError, match="robots"):
        make().get(base + "/private/secret")
    assert ("/private/secret", seen[-1][1]) not in seen      # never even requested


def test_fetcher_requires_contact_and_https():
    with pytest.raises(ValueError):
        HttpFetcher("")
    with pytest.raises(FetchError, match="non-https"):
        HttpFetcher("me@example.com").get("http://www.bncap.in/")


def test_fetcher_gives_up_after_retries(server):
    base, seen = server
    with pytest.raises(FetchError):
        make(retries=1).get(base + "/boom")
    assert sum(1 for p, _ in seen if p == "/boom") == 2


def test_fetcher_fails_closed_if_robots_unreadable():
    f = make()
    f._request = lambda url: (_ for _ in ()).throw(FetchError("HTTP 503 for robots"))
    with pytest.raises(FetchError, match="robots"):
        f.get("http://127.0.0.1:9/x")


# ---- regression: "WinError 10054 / connection reset" crashed the run with a traceback ----

def test_fetcher_retries_after_a_connection_reset(server):
    base, seen = server
    assert make(retries=2).get(base + "/flaky") == "<html>recovered</html>"
    assert sum(1 for p, _ in seen if p == "/flaky") == 2


def test_fetcher_turns_repeated_resets_into_fetcherror_not_a_crash(server):
    base, seen = server
    with pytest.raises(FetchError, match="giving up"):
        make(retries=2).get(base + "/drop")
    assert sum(1 for p, _ in seen if p == "/drop") == 3          # 1 try + 2 retries, then stop


def test_a_reset_page_is_counted_as_failed_and_the_run_continues(db, html):
    class Resetting(FakeFetcher):
        def get(self, url):
            if "flaky" in url:
                raise FetchError(f"giving up on {url}: [WinError 10054]")
            return super().get(url)
    f = Resetting({DZ: html["dzire"]})
    flaky = "https://www.bncap.in/vehicle/flaky/"
    res = run_ingestion(db, pages_of(f, [flaky, DZ]))
    assert (res.created, res.failed, res.aborted) == (1, 1, False)
