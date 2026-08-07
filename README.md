# About

An unofficial RSS feed for https://www.officialcharts.com/new-releases/, which
doesn't have one of its own.

A GitHub Action checks the page twice a day. It never saves or commits the
page itself — it only hashes the three "New Music Friday `<Type>` Releases -
`<date>`" heading lines. When that hash changes (i.e. the site is showing a
new week's releases), it records the date and appends an entry to
[`feed.xml`](feed.xml). No article text, titles, artist names or chart data
are ever stored in this repo — see [`check.py`](check.py).

Every feed entry links back to the same officialcharts.com page (there's
nothing else to link to), so each `<item>` uses a `guid` based on detection
time rather than the link, otherwise feed readers would treat every entry as
a duplicate of the first.

## Subscribing

Once pushed, the feed is readable directly from GitHub, or (better — correct
content-type, CDN-cached) via jsDelivr:

```
https://cdn.jsdelivr.net/gh/<you>/<repo>@main/feed.xml
```

## Notes

- Schedule: `.github/workflows/check-new-releases.yml`, twice daily. Adjust
  the cron lines if that's too often/infrequent.
- The fetch in `check.py` sends browser-like headers because the site's
  CloudFront/WAF setup 403s a bare request otherwise. Worth testing the
  first scheduled run manually (`workflow_dispatch`, or the "Run workflow"
  button in the Actions tab) in case GitHub's runner IPs get treated
  differently than this worked from.
- If officialcharts.com changes its page structure, `check.py` will fail
  loudly (non-zero exit) rather than silently going stale — GitHub emails
  you on a failed scheduled run by default.
