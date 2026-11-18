#!/usr/bin/env python3
"""Print all 2026 Griffins-track games as box-drawing table rows."""
import glob, json

EVSHORT = [
    ("MLK Showcase", "MLK Showcase"),
    ("HHH: MLK Weekend", "HHH Future Stars"),
    ("Groundhog Day Top 30", "Groundhog Top 30"),
    ("The Kick-Off", "Kick-Off"),
    ("NORCAL HEAT CHECK", "Heat Check"),
    ("NorCal Spring Battle", "Spring Battle"),
    ("Alicia Renee Anderson", "Anderson Mem."),
    ("Hoop It Up", "Hoop It Up"),
    ("Las Vegas Memorial Day", "Vegas"),
    ("South Bay Invitational", "S. Bay Invit."),
    ("Summer Jam", "Summer Jam"),
    ("BAY AREA LIVE", "Bay Area Live"),
    ("HALLOWEEN INVITATIONAL", "Halloween"),
]

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def ev_name(tid, title):
    for pat, short in EVSHORT:
        if pat.lower() in title.lower():
            return short
    return title[:30] or ("BT " + tid)


titles = {}
for f in glob.glob("data/[0-9]*.json") + glob.glob("data/bt_*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    tid = str(d.get("tournament_id", d.get("event_id")))
    t = ((d.get("metadata") or {}).get("title", "") or
         d.get("event_name", "")).replace("&#39;", "'")
    titles[tid] = (ev_name(tid, t), t)

rows = []
for f in glob.glob("data/[0-9]*.json") + glob.glob("data/bt_*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    tid = str(d.get("tournament_id", d.get("event_id")))
    for g in d.get("games", []):
        h = g.get("HomeTeamName") or g.get("top") or ""
        a = g.get("AwayTeamName") or g.get("bottom") or ""
        dt = g.get("DateFormatted") or g.get("date") or ""
        if "/2026" not in dt and not dt.startswith("2026"):
            continue
        div = (g.get("_division_name") or g.get("DivisionName") or
               g.get("division_name") or "")
        is_grif = "TM Griffins" in h or "TM Griffins" in a
        is_tm12 = ((h == "TM Basketball" or a == "TM Basketball") and
                   ("12u" in div.lower() or "6th" in div.lower()))
        if not (is_grif or is_tm12):
            continue
        tm = (g.get("TimeFormatted") or g.get("start_hour") or "")
        tm = tm.replace(" PDT", "").replace(" PST", "")
        st = g.get("Status") or ("Final" if g.get("has_result") else "") or "sched"
        rows.append({"date": dt, "time": tm, "tid": tid, "gt": g.get("GameTypeName") or "",
                     "h": h, "hs": g.get("HomeTeamScoreDisplay", g.get("score_home_team")),
                     "a": a, "aws": g.get("AwayTeamScoreDisplay", g.get("score_away_team")),
                     "st": st, "grif": is_grif})


def skey(r):
    try:
        m, dd, y = r["date"].split("/")
        return (y, m.zfill(2), dd.zfill(2), r["time"])
    except Exception:
        return (r["date"], r["time"], "", "")


rows.sort(key=skey)
W = (18, 35, 31, 9)
print("  ┌" + "─" * W[0] + "┬" + "─" * W[1] + "┬" + "─" * W[2] + "┬" + "─" * W[3] + "┐")
for i, r in enumerate(rows):
    try:
        m, dd, y = r["date"].split("/")
        dstr = f"{MON[int(m) - 1]} {int(dd)}, {r['time']}"
    except Exception:
        dstr = r["date"]
    game = f"{titles.get(r['tid'], (r['tid'], ''))[0]} {r['gt']}".strip()[:W[1]]
    tm_home = "TM Griffins" in r["h"] or r["h"] == "TM Basketball"
    opp = r["a"] if tm_home else r["h"]
    pre = "vs " if tm_home else "@ "
    if r["st"] != "Final":
        res = "sched"
    else:
        try:
            ths, tas = int(r["hs"]), int(r["aws"])
            mine, theirs = (ths, tas) if tm_home else (tas, ths)
            res = f"{'W' if mine > theirs else 'L'} {mine}–{theirs}"
        except Exception:
            res = f"{r['hs']}–{r['aws']}"
    mark = "" if r["grif"] else " *"
    cells = [dstr[:W[0]], game, (pre + opp)[:W[2]], (res + mark)[:W[3]]]
    print("  │ " + " │ ".join(c.ljust(w - 1) for c, w in zip(cells, W)) + "│")
    if i < len(rows) - 1:
        print("  ├" + "─" * W[0] + "┼" + "─" * W[1] + "┼" + "─" * W[2] + "┼" + "─" * W[3] + "┤")
print("  └" + "─" * W[0] + "┴" + "─" * W[1] + "┴" + "─" * W[2] + "┴" + "─" * W[3] + "┘")
print("  * = 12U/girls TM Basketball label (likely different roster, not named Griffins)")
