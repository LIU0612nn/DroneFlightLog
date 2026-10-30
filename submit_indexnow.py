"""Submit URLs to IndexNow (Bing, Yandex, Seznam, Naver).

IndexNow is a plain HTTP push: you tell the search engine "this URL changed,
come and look". There is no quota to burn and no account needed - just a key
file hosted on the site.

The key file is served by app.py at /<INDEXNOW_KEY>.txt.

Usage
-----
    python submit_indexnow.py                    # every URL in sitemap.xml
    python submit_indexnow.py URL [URL ...]      # only these URLs
    python submit_indexnow.py --dry-run          # check setup, send nothing
    python submit_indexnow.py --site http://127.0.0.1:5055 --dry-run

Exit codes: 0 = all endpoints accepted, 1 = at least one endpoint refused.
"""
import argparse
import os
import re
import sys

import requests

DEFAULT_SITE = "https://drone-flight-report.com"
DEFAULT_KEY = "227dce2d9bae4cb3a113c6c392e85b1f"

ENDPOINTS = [
    "https://api.indexnow.org/indexnow",   # shared endpoint (Bing, Yandex, ...)
    "https://www.bing.com/indexnow",       # Bing directly
]

# IndexNow accepts at most 10,000 URLs per request.
BATCH = 10000


def resolve_key():
    return (os.environ.get("INDEXNOW_KEY") or DEFAULT_KEY).strip()


def sitemap_urls(site):
    response = requests.get(site.rstrip("/") + "/sitemap.xml", timeout=20)
    response.raise_for_status()
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", response.text)


def check_key_file(site, key):
    """The key file must be reachable and contain exactly the key."""
    url = "%s/%s.txt" % (site.rstrip("/"), key)
    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException as exc:
        print("  [FAIL] key file unreachable: %s (%s)" % (url, exc))
        return False

    if response.status_code != 200:
        print("  [FAIL] key file returned %s: %s" % (response.status_code, url))
        return False

    body = response.text.strip()
    if body != key:
        print("  [FAIL] key file content mismatch (got %r)" % body[:60])
        return False

    print("  [ OK ] key file live: %s" % url)
    return True


def submit(endpoint, host, key, key_location, urls, dry_run):
    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }

    if dry_run:
        print("  [SKIP] would POST %d URL(s) to %s" % (len(urls), endpoint))
        return True

    try:
        response = requests.post(endpoint, json=payload, timeout=30)
    except requests.RequestException as exc:
        print("  [FAIL] %s -> %s" % (endpoint, exc))
        return False

    code = response.status_code

    if code in (200, 202):
        print("  [ OK ] %s -> %s" % (endpoint, code))
        return True

    hints = {
        400: "bad request - check host/key format",
        403: "key not valid yet (deploy the key file first)",
        422: "URLs do not belong to host, or the key file was not found",
        429: "too many requests - retry tomorrow",
    }
    print("  [FAIL] %s -> %s (%s)" % (endpoint, code, hints.get(code, response.text[:120])))
    return False


def main():
    parser = argparse.ArgumentParser(description="Submit URLs to IndexNow")
    parser.add_argument("urls", nargs="*", help="URLs to submit (default: sitemap)")
    parser.add_argument("--site", default=DEFAULT_SITE, help="site origin")
    parser.add_argument("--key", default=None, help="IndexNow key")
    parser.add_argument("--dry-run", action="store_true", help="validate only")
    args = parser.parse_args()

    site = args.site.rstrip("/")
    host = re.sub(r"^https?://", "", site).split("/")[0]
    key = (args.key or resolve_key()).strip()

    print("Host:  %s" % host)
    print("Key:   %s" % key)

    if not args.dry_run and not check_key_file(site, key):
        print("\nAborting: the key file must be live before submitting.")
        return 1

    urls = args.urls
    if not urls:
        try:
            urls = sitemap_urls(site)
        except Exception as exc:
            print("Could not read sitemap: %s" % exc)
            return 1

    if not urls:
        print("No URLs to submit.")
        return 1

    print("URLs:  %d" % len(urls))

    key_location = "%s/%s.txt" % (site, key)
    ok = True

    for start in range(0, len(urls), BATCH):
        batch = urls[start:start + BATCH]
        for endpoint in ENDPOINTS:
            ok = submit(endpoint, host, key, key_location, batch, args.dry_run) and ok

    print("\nDone." if ok else "\nFinished with errors.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
