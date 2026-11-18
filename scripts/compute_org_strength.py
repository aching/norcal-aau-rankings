#!/usr/bin/env python3
"""Compute organizer strength metrics from corpus + boards.

Metric (user-confirmed):
  organizer strength = mean ranked-team score over all resolved ranked
  participant appearances in their scraped events (last 365 days).
  Min 20 appearances to rank.
  Per-division tables: same mean grouped by normalized division name
  (min 5 appearances).

Writes data/org_strength.json:
  {org: {"avg": float, "n": int, "events": int,
         "divisions": [{"div": str, "avg": float, "n": int}]},
   ...}
Only orgs meeting the minimum are included.
"""
import json
import glob
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from team_identity import resolve
from build_organizers import load_ee_history, CANONICAL, canon_org


def norm_div(div):
    d = (div or "").strip()
    d = re.sub(r"^(boys|girls)\s*[-–:]\s*", "", d, flags=re.I)
    d = re.sub(r"\s+", " ", d).strip()
    return d or "?"


def ranked_scores():
    ranked = {}
    for cohort in ("11u", "12u", "13u", "14u"):
        p = HERE.parent / "site" / f"{cohort}.html"
        if not p.exists():
            continue
        m = re.search(r"const DATA = (\[.*?\]);\nlet sortKey", p.read_text(), re.S)
        if not m:
            continue
        for r in json.loads(m.group(1)):
            if r.get("rank"):
                ranked[r["team"]] = r["score"]
    return ranked


def main():
    ranked = ranked_scores()
    print(f"ranked teams with scores: {len(ranked)}")
    orgs = load_ee_history()
    canon_hist = defaultdict(list)
    for org, evs in orgs.items():
        canon_hist[canon_org(org)].extend(evs)
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    corp = {}
    for f in glob.glob(str(HERE.parent / "data" / "[0-9]*.json")):
        try:
            d = json.load(open(f))
            tid = d.get("tournament_id") or int(Path(f).stem)
            corp[tid] = d.get("games", [])
        except Exception:
            pass
    out = {}
    for org, evs in canon_hist.items():
        recent = [e for e in evs if (e.get("start") or "") >= cutoff]
        scores, nev = [], 0
        divscores = defaultdict(list)
        for e in recent:
            games = corp.get(e["id"], [])
            if not games:
                continue
            nev += 1
            seen_teams = set()
            for g in games:
                div = g.get("_division_name") or g.get("DivisionName") or "?"
                nd = norm_div(div)
                for k in ("HomeTeamName", "AwayTeamName"):
                    n = g.get(k)
                    if not n:
                        continue
                    tid, _ = resolve(n, div)
                    if tid in ranked and (e["id"], tid) not in seen_teams:
                        seen_teams.add((e["id"], tid))
                        scores.append(ranked[tid])
                        divscores[nd].append(ranked[tid])
        if len(scores) < 20:
            continue
        divs = sorted(
            ({"div": d, "avg": sum(v) / len(v), "n": len(v)}
             for d, v in divscores.items() if len(v) >= 5),
            key=lambda x: -x["avg"],
        )
        out[org] = {
            "avg": sum(scores) / len(scores),
            "n": len(scores),
            "events": nev,
            "divisions": divs,
        }
    outp = HERE.parent / "data" / "org_strength.json"
    outp.write_text(json.dumps(out, indent=1))
    ranked_orgs = sorted(out.items(), key=lambda kv: -kv[1]["avg"])
    print(f"ranked {len(ranked_orgs)} organizers -> {outp}")
    for org, s in ranked_orgs[:15]:
        print(f"  {s['avg']:.3f}  {org[:45]:45} n={s['n']} ev={s['events']}")


if __name__ == "__main__":
    main()
