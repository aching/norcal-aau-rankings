#!/usr/bin/env python3
"""Page through CA events listing and save metadata to data/events_ca.json."""
import json, re, sys, time, urllib.parse, urllib.request, http.cookiejar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_state import record
from storage import atomic_write_json

UA = "AAU-Basketball-Aggregator/0.1 (avery@aptoslabs.com)"
BASE = "https://basketball.exposureevents.com"
PAGE_URL = f"{BASE}/youth-basketball-events/california"
RATE = 1.5


def main(start_date=None, end_date=None, out_name="events_ca.json"):
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]

    # Get token + cookies
    with opener.open(urllib.request.Request(PAGE_URL, headers={"User-Agent": UA}), timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = re.search(r"tokenValue:\s*'([^']+)'", html)
    token = m.group(1)
    print(f"Token: {token[:30]}…  window: {start_date} → {end_date}")

    all_results = []
    page = 1
    while True:
        body_obj = {"Page": page, "sportType": 1}
        if start_date: body_obj["StartDateString"] = start_date
        if end_date:   body_obj["EndDateString"] = end_date
        body = json.dumps(body_obj).encode()
        req = urllib.request.Request(PAGE_URL, data=body, method="POST", headers={
            "User-Agent": UA,
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Exposure-Token": token,
            "Referer": PAGE_URL,
            "Accept": "application/json",
        })
        with opener.open(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        if isinstance(data, list):
            print(f"  ERROR response: {data}"); break
        results = data.get("Results") or []
        total = data["Total"]
        all_results.extend(results)
        print(f"  page {page}: got {len(results)}, total seen {len(all_results)}/{total}")
        if len(all_results) >= total or not results:
            break
        page += 1
        time.sleep(RATE)

    # Project to a compact shape
    compact = []
    for r in all_results:
        compact.append({
            "Id": r["Id"],
            "Name": r["Name"],
            "Slug": r.get("Slug"),
            "Link": r.get("Link"),
            "StartDate": r["StartDate"][:10] if r.get("StartDate") else None,
            "EndDate": r["EndDate"][:10] if r.get("EndDate") else None,
            "DateFormatted": r.get("DateFormatted"),
            "Location": r.get("Location"),
            "City": r.get("City"),
            "State": r.get("StateRegion"),
            "OrganizationId": r.get("OrganizationId"),
            "OrganizationName": r.get("OrganizationName"),
            "Type": r.get("Type"),
            "Gender": r.get("Gender"),
            "Ability": r.get("Ability"),
            "Gradess": r.get("YouthAgeGradesBoth"),
        })

    Path("data").mkdir(exist_ok=True)
    out = Path("data") / out_name
    atomic_write_json(out, compact)
    print(f"Saved {len(compact)} events -> {out}")
    record("exposureevents", "discovery",
           {"window": [start_date, end_date], "out_file": out_name, "events": len(compact)},
           started_at=started)


if __name__ == "__main__":
    import sys
    sd = sys.argv[1] if len(sys.argv) > 1 else None
    ed = sys.argv[2] if len(sys.argv) > 2 else None
    name = sys.argv[3] if len(sys.argv) > 3 else "events_ca.json"
    main(sd, ed, name)
