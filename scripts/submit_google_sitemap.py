"""Submit the existing sitemap to a verified Google Search Console property.

Requires an OAuth access token with the webmasters scope. Keep that token in
GOOGLE_SEARCH_CONSOLE_ACCESS_TOKEN; never put it in source code or a URL.
Example:
  python scripts/submit_google_sitemap.py --property sc-domain:drone-flight-report.com --submit

Submission requests discovery; it does not guarantee indexing or ranking.
"""

import argparse
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


SITEMAP = "https://drone-flight-report.com/sitemap.xml"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--property", required=True,
                        help="Exact Search Console property, such as sc-domain:drone-flight-report.com")
    parser.add_argument("--submit", action="store_true", help="Send the authenticated PUT request")
    args = parser.parse_args()
    if not args.submit:
        print("Ready to submit", SITEMAP, "for", args.property)
        print("Add --submit after setting GOOGLE_SEARCH_CONSOLE_ACCESS_TOKEN.")
        return 0
    token = os.environ.get("GOOGLE_SEARCH_CONSOLE_ACCESS_TOKEN", "").strip()
    if not token:
        parser.error("GOOGLE_SEARCH_CONSOLE_ACCESS_TOKEN is missing; sign in as a verified property owner or full user")
    endpoint = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        + quote(args.property, safe="")
        + "/sitemaps/"
        + quote(SITEMAP, safe="")
    )
    request = Request(endpoint, method="PUT", headers={"Authorization": "Bearer " + token})
    try:
        with urlopen(request, timeout=20) as response:
            print("Search Console sitemap submission HTTP", response.status)
    except HTTPError as exc:
        print("Search Console rejected the request: HTTP", exc.code)
        print("Check the exact property name, verified access, token scope and sitemap URL.")
        return 1
    except URLError as exc:
        print("Could not reach Search Console API:", exc.reason)
        return 1
    print("Now check the Sitemaps and Pages reports in Search Console; indexing is not immediate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
