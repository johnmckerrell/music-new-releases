#!/usr/bin/env python3
"""
Check officialcharts.com/new-releases/ for a new release week and update
the RSS feed if one is detected.

We never store the fetched page anywhere. We only keep:
  - a sha256 hash of the three "New Music Friday <Type> Releases - <date>"
    heading lines (this changes exactly when the site starts showing a new
    week's releases, and does not change for e.g. mid-week copy edits to
    the article text or the unrelated singles-chart widget on the page)
  - the human-readable date parsed out of those headings

No article text, titles, artist names or chart data are ever written to
this repo.
"""

import gzip
import hashlib
import html
import json
import os
import re
import sys
import zlib
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.sax.saxutils import escape

URL = "https://www.officialcharts.com/new-releases/"
STATE_PATH = "state.json"
FEED_PATH = "feed.xml"
HISTORY_LIMIT = 50

# officialcharts.com sits behind a CloudFront/WAF setup that 403s a bare
# request (even with a plain "Mozilla/5.0" UA) but accepts a request that
# looks like a normal browser navigation. This header set is chosen to pass
# that check, not to disguise what this is -- it's a low-frequency,
# read-only fetch of one public page.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    # Deliberately not offering "br": stdlib has no brotli decoder.
    "Accept-Encoding": "gzip, deflate",
}

HEADING_RE = re.compile(r"^New Music Friday .+ [Rr]eleases - .+$")
HEADING_DATE_RE = re.compile(r"-\s*([A-Za-z]+ \d{1,2} \d{4})\s*$")


def fetch(url):
    req = Request(url, headers=REQUEST_HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
            encoding = resp.headers.get("Content-Encoding", "")
    except HTTPError as e:
        sys.exit(f"ERROR: fetch failed with HTTP {e.code} {e.reason} -- "
                  f"the page may be blocking this request, check headers/UA")
    except URLError as e:
        sys.exit(f"ERROR: fetch failed: {e.reason}")

    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def visible_lines(page_html):
    page_html = re.sub(r"<script.*?</script>", "", page_html, flags=re.DOTALL)
    page_html = re.sub(r"<style.*?</style>", "", page_html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", page_html)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_week_of(heading):
    m = HEADING_DATE_RE.search(heading)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def human_week(week_of):
    if not week_of:
        return "an unknown date"
    dt = datetime.strptime(week_of, "%Y-%m-%d")
    return f"{dt.day} {dt.strftime('%B %Y')}"


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"lastHash": None, "history": []}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def rfc822(iso_str):
    dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def render_feed(state):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    self_url = f"https://cdn.jsdelivr.net/gh/{repo}@main/{FEED_PATH}" if repo else FEED_PATH

    items = []
    for entry in state["history"]:
        week_label = human_week(entry.get("weekOf"))
        title = f"New releases updated — {week_label}"
        description = (
            "The Official Charts New Releases page appears to have been "
            f"updated for the week of {week_label}. This is an unofficial, "
            "unaffiliated notification feed and reproduces no chart "
            "content -- follow the link for the actual page."
        )
        items.append(
            "  <item>\n"
            f"    <title>{escape(title)}</title>\n"
            f"    <link>{escape(URL)}</link>\n"
            f"    <guid isPermaLink=\"false\">{escape(entry['detectedAt'])}</guid>\n"
            f"    <pubDate>{rfc822(entry['detectedAt'])}</pubDate>\n"
            f"    <description>{escape(description)}</description>\n"
            "  </item>"
        )

    last_build = (
        rfc822(state["history"][0]["detectedAt"])
        if state["history"]
        else rfc822(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        "  <title>Official Charts New Releases — unofficial update feed</title>\n"
        f"  <link>{escape(URL)}</link>\n"
        f'  <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />\n'
        "  <description>Unofficial, unaffiliated notification feed. Pings when the "
        "Official Charts “New Releases” page appears to show a new week's "
        "releases. No chart content is reproduced here — follow the link for the "
        "actual page.</description>\n"
        "  <language>en-gb</language>\n"
        f"  <lastBuildDate>{last_build}</lastBuildDate>\n"
        + ("\n".join(items) + "\n" if items else "")
        + "</channel>\n"
        "</rss>\n"
    )

    with open(FEED_PATH, "w") as f:
        f.write(xml)


def main():
    page_html = fetch(URL)
    lines = visible_lines(page_html)
    headings = sorted(l for l in lines if HEADING_RE.match(l))

    if not headings:
        sys.exit(
            "ERROR: no 'New Music Friday ... Releases' headings found -- "
            "the page structure has probably changed and the extraction "
            "logic in check.py needs updating"
        )

    digest = hashlib.sha256("\n".join(headings).encode("utf-8")).hexdigest()
    week_of = parse_week_of(headings[0])

    state = load_state()
    if state.get("lastHash") == digest:
        print("No change detected.")
        return

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["lastHash"] = digest
    state.setdefault("history", []).insert(0, {"detectedAt": now_iso, "weekOf": week_of})
    state["history"] = state["history"][:HISTORY_LIMIT]

    save_state(state)
    render_feed(state)
    print(f"Change detected -- weekOf={week_of} hash={digest[:12]}")


if __name__ == "__main__":
    main()
