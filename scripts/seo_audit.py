"""Audit the site's sitemap, indexable pages, JSON-LD, and internal links.

Run against this checkout (no network): python scripts/seo_audit.py
Run against production: python scripts/seo_audit.py --base-url https://drone-flight-report.com
This checks discoverability, not whether Google has indexed a URL.
"""

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.h1 = []
        self.description = ""
        self.robots = ""
        self.canonical = ""
        self.links = []
        self.json_ld = []
        self._capture = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("title", "h1"):
            self._capture, self._buffer = tag, []
        elif tag == "script" and attrs.get("type") == "application/ld+json":
            self._capture, self._buffer = "json_ld", []
        elif tag == "meta":
            if attrs.get("name", "").lower() == "description":
                self.description = attrs.get("content", "")
            elif attrs.get("name", "").lower() == "robots":
                self.robots = attrs.get("content", "")
        elif tag == "link" and attrs.get("rel", "").lower() == "canonical":
            self.canonical = attrs.get("href", "")
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, data):
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if self._capture == tag or (tag == "script" and self._capture == "json_ld"):
            value = "".join(self._buffer).strip()
            if self._capture == "title":
                self.title = value
            elif self._capture == "h1":
                self.h1.append(value)
            else:
                self.json_ld.append(value)
            self._capture, self._buffer = None, []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Audit public HTTP pages instead of the local Flask app")
    args = parser.parse_args()
    if args.base_url:
        base = args.base_url.rstrip("/")

        def fetch(path):
            request = Request(base + path, headers={"User-Agent": "DroneFlightReport-SEO-Audit/1.0"})
            with urlopen(request, timeout=20) as response:
                return response.status, response.read().decode("utf-8", "replace")
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import app, SITE_URL
        base = SITE_URL.rstrip("/")
        client = app.test_client()

        def fetch(path):
            response = client.get(path)
            return response.status_code, response.get_data(as_text=True)

    problems = []
    status, robots = fetch("/robots.txt")
    if status != 200 or "Sitemap: " + base + "/sitemap.xml" not in robots:
        problems.append("robots.txt does not advertise the canonical sitemap")
    status, xml = fetch("/sitemap.xml")
    if status != 200:
        problems.append("sitemap.xml did not return HTTP 200")
        paths = []
    else:
        root = ET.fromstring(xml)
        locs = [node.text for node in root.findall(".//{*}loc")]
        paths = [urlparse(loc).path or "/" for loc in locs]
        if len(locs) != len(set(locs)):
            problems.append("sitemap contains duplicate URLs")
        for loc in locs:
            if not loc.startswith(base + "/"):
                problems.append("sitemap URL is outside canonical host: " + loc)

    titles = Counter()
    inbound = Counter()
    for path in paths:
        try:
            status, html = fetch(path)
        except Exception as exc:
            problems.append(f"{path}: fetch failed: {exc}")
            continue
        if status != 200:
            problems.append(f"{path}: HTTP {status}")
            continue
        page = PageParser()
        page.feed(html)
        if not page.title or not page.description or len(page.h1) != 1:
            problems.append(f"{path}: missing title/description or not exactly one H1")
        titles[page.title] += 1
        if page.canonical != base + path:
            problems.append(f"{path}: canonical {page.canonical!r} does not match sitemap")
        if "noindex" in page.robots.lower():
            problems.append(f"{path}: sitemap URL has noindex")
        types = set()
        for raw in page.json_ld:
            try:
                data = json.loads(raw)
                nodes = data if isinstance(data, list) else [data]
                types.update(node.get("@type") for node in nodes if isinstance(node, dict))
            except (ValueError, TypeError) as exc:
                problems.append(f"{path}: invalid JSON-LD: {exc}")
        expected = "WebSite" if path == "/" else "BreadcrumbList"
        if expected not in types:
            problems.append(f"{path}: missing {expected} JSON-LD")
        for href in page.links:
            target = urljoin(base + path, href)
            parsed = urlparse(target)
            if parsed.netloc == urlparse(base).netloc:
                inbound[parsed.path or "/"] += 1
    for title, count in titles.items():
        if title and count > 1:
            problems.append(f"duplicate title on {count} pages: {title}")
    for path in paths:
        if path != "/" and inbound[path] == 0:
            problems.append(f"{path}: no internal links from sitemap pages")

    print(f"Audited {len(paths)} sitemap URLs at {base}")
    for issue in problems:
        print("FAIL: " + issue)
    print(f"Result: {len(problems)} issue(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
