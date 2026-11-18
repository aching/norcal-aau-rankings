#!/usr/bin/env python3
"""
Scout an opponent: find their games across the full data set, summarize record,
recent form, and any head-to-head vs a specified "our" team pattern.
"""
import json, glob, re, sys
from collections import defaultdict, Counter
from pathlib import Path


def date_iso(s):
    try:
        m, d, y = s.split("/")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return "0000-00-00"


CURRENT_TID = "257525"  # the tournament we're scouting; exclude from historical analysis


def iter_games(exclude_current=True, div_filter=None):
    for f in sorted(glob.glob("data/[0-9]*.json")):
        d = json.load(open(f))
        tid = str(d["tournament_id"])
        if exclude_current and tid == CURRENT_TID:
            continue
        meta = ((d.get("metadata") or {}).get("title", "").replace("&#39;", "'")
                .split(" - Schedule")[0].split(" - ")[0])
        for g in d["games"]:
            if div_filter:
                div = g.get("_division_name") or g.get("DivisionName") or ""
                if not div_filter.search(div):
                    continue
            yield tid, meta, g


def find_games(team_pat, div_filter=None):
    out = []
    for tid, meta, g in iter_games(div_filter=div_filter):
        home = g.get("HomeTeamName") or ""
        away = g.get("AwayTeamName") or ""
        if team_pat.search(home):
            out.append((tid, meta, g, True, home, away))
        elif team_pat.search(away):
            out.append((tid, meta, g, False, away, home))
    return out


def find_h2h(our_pat, opp_pat, div_filter=None):
    out = []
    for tid, meta, g in iter_games(div_filter=div_filter):
        h, a = g.get("HomeTeamName") or "", g.get("AwayTeamName") or ""
        if our_pat.search(h) and opp_pat.search(a):
            out.append((tid, meta, g, True, h, a))
        elif our_pat.search(a) and opp_pat.search(h):
            out.append((tid, meta, g, False, a, h))
    return out


def summarize(games, our_label):
    rows = []
    w = l = 0
    pf = pa = 0; scored_n = 0
    for tid, meta, g, is_home, our_name, opp_name in games:
        won = g.get("HomeTeamIsWinner") if is_home else g.get("AwayTeamIsWinner")
        status = g.get("Status") or ""
        our_sc = g.get("HomeTeamScoreDisplay" if is_home else "AwayTeamScoreDisplay") or ""
        opp_sc = g.get("AwayTeamScoreDisplay" if is_home else "HomeTeamScoreDisplay") or ""
        date = g.get("DateFormatted") or ""
        round_ = g.get("GameTypeName") or ""
        div = g.get("_division_name") or g.get("DivisionName") or ""
        wl = "W" if won else ("L" if won is False and status == "Final" else "-")
        if won: w += 1
        elif won is False and status == "Final": l += 1
        try:
            if our_sc and opp_sc:
                pf += int(our_sc); pa += int(opp_sc); scored_n += 1
        except ValueError:
            pass
        rows.append({
            "date": date, "date_iso": date_iso(date),
            "tid": tid, "tournament": meta, "round": round_,
            "div": div, "our_name": our_name, "opp": opp_name,
            "our_sc": our_sc, "opp_sc": opp_sc, "wl": wl, "status": status,
        })
    rows.sort(key=lambda r: (r["date_iso"], r["tid"]))
    return {
        "rows": rows, "wins": w, "losses": l,
        "ppg_for": pf / scored_n if scored_n else None,
        "ppg_against": pa / scored_n if scored_n else None,
        "margin": (pf - pa) / scored_n if scored_n else None,
    }


def render_opp_section(opp_label, opp_pat, our_label, our_pat, scheduled, div_filter=None, div_note=""):
    games = find_games(opp_pat, div_filter=div_filter)
    if not games:
        return f"### vs {opp_label}\n*Scheduled: {scheduled}.* {div_note}\n\nNo prior games found in our data — they're new to our dataset.\n"

    s = summarize(games, opp_label)
    rows = s["rows"]
    last_n = rows[-5:]
    tournaments_played = len({r["tid"] for r in rows})

    # H2H (apply same division filter so we compare apples to apples)
    h2h_games = find_h2h(our_pat, opp_pat, div_filter=div_filter)
    h2h_sum = summarize(h2h_games, our_label) if h2h_games else None

    lines = [f"### vs {opp_label}",
             f"*Scheduled: {scheduled}*  {div_note}", ""]
    lines.append(f"**Season record:** {s['wins']}W-{s['losses']}L across {tournaments_played} tournaments, "
                 f"{len(rows)} games in our data.")
    if s["ppg_for"] is not None:
        lines.append(f"**Scoring:** averaging **{s['ppg_for']:.1f}** PPG, allowing **{s['ppg_against']:.1f}** "
                     f"(margin {s['margin']:+.1f}).")
    lines.append("")
    lines.append("**Last 5 games:**")
    lines.append("")
    lines.append("| Date | Tournament | Div | Result | Score | Opponent |")
    lines.append("|---|---|---|---|---|---|")
    for r in last_n:
        score = f"{r['our_sc']}-{r['opp_sc']}" if r["our_sc"] else r["status"] or "—"
        lines.append(f"| {r['date']} | {r['tournament'][:30]} | {r['div']} | {r['wl']} | {score} | {r['opp']} |")
    lines.append("")

    if h2h_games:
        lines.append(f"**Head-to-head vs {our_label}:** {h2h_sum['wins']}W-{h2h_sum['losses']}L in {len(h2h_games)} games")
        lines.append("")
        lines.append("| Date | Tournament | Round | Result | Score |")
        lines.append("|---|---|---|---|---|")
        for r in h2h_sum["rows"]:
            score = f"{r['our_sc']}-{r['opp_sc']}" if r["our_sc"] else r["status"] or "—"
            lines.append(f"| {r['date']} | {r['tournament'][:30]} | {r['round']} | {r['wl']} | {score} |")
        lines.append("")
    else:
        lines.append(f"**Head-to-head vs {our_label}:** none found.")
        lines.append("")
    return "\n".join(lines)


# Patterns for our kids' teams. Each combined with the per-opponent div_filter to constrain by age.
OUR_PATS = {
    # Brayden plays BOTH SV Prospects 13U AND TM Falcons Black this weekend.
    "Brayden (SV Prospects 13U)": re.compile(r"(silicon valley|sv) soldiers? prospect", re.I),
    # TM Falcons Black — also registers as "TM Basketball" or "TM Falcons" without tier. Div filter to 13U/14U constrains.
    "Brayden (TM Falcons Black)": re.compile(r"\btm\b.*falcon|\btm\b.*basketball|^tm$", re.I),
    # Paxton plays TM Griffins Black this weekend. Same alias variants.
    "Paxton (TM Griffins Black)": re.compile(r"\btm\b.*griffin|\btm\b.*basketball|^tm$|^tm 11u$", re.I),
    # Weston is on the primary SV Soldiers 10U team — no coach/tier suffix. Match unsuffixed only.
    "Weston (SV Soldiers 10U)": re.compile(r"^(silicon valley|sv) soldiers?( 10[uU])?$", re.I),
}

# Opponent patterns for all distinct opponents this weekend
OPP_PATS = {
    "San Jose Spartans Wilson":       re.compile(r"(san jose )?spartans?.*wilson|wilson.*spartans?", re.I),
    "Oakland Soldiers (Ashton) 13U":  re.compile(r"oakland.*soldier.*ashton", re.I),
    "Oakland Soldiers (Ashton) 11U":  re.compile(r"oakland.*soldier.*ashton", re.I),
    "Team Esface 5th Goers":          re.compile(r"team esface.*5th|esface.*5th goer", re.I),
    "Cali Gold 4th (Dario)":          re.compile(r"cali gold.*dario|cali gold 4th", re.I),
    "Hayward Swoosh":                 re.compile(r"hayward swoosh", re.I),
    "SV Soldiers Elite":              re.compile(r"(silicon valley|sv) soldiers? elite", re.I),
    "Bay Area Tar Heels":             re.compile(r"bay area.*tar ?heels|tar ?heels.*bay area|chico tarheels", re.I),
    "Westbay Ospreys (Tim)":          re.compile(r"westbay ospreys.*tim|ospreys.*tim", re.I),
}

# Division filters — only count opponent games in age-appropriate divisions
DIV_13U_14U = re.compile(r"\b(13|14)[uU]|7th|8th", re.I)
DIV_11U_12U = re.compile(r"\b(11|12)[uU]|5th|6th", re.I)
DIV_10U     = re.compile(r"\b(9|10)[uU]|4th", re.I)

# Each kid's weekend schedule with per-opponent age filter
# Note: schedule rows are (time, opp_display, side, opp_key_for_OPP_PATS, div_filter, div_note)
SCHEDULES = [
    ("Brayden — SV Soldiers Prospects 13U", "Brayden (SV Prospects 13U)", "13u Black", "Menlo College, Court 1", [
        ("Sat 10:10 AM", "San Jose Spartans Wilson", "HOME", "San Jose Spartans Wilson", DIV_13U_14U, "Filtered to 13U/14U divisions."),
        ("Sat 11:00 AM", "Oakland Soldiers (Ashton)", "HOME", "Oakland Soldiers (Ashton) 13U", DIV_13U_14U, "Filtered to 13U/14U divisions (Ashton runs multiple age cohorts)."),
    ]),
    ("Brayden — TM Falcons Black (entered as \"TM Basketball\")", "Brayden (TM Falcons Black)", "13u Green", "Menlo College, Court 2", [
        ("Sat 1:30 PM",  "Silicon Valley Soldiers Elite", "AWAY", "SV Soldiers Elite", DIV_13U_14U, "Filtered to 13U/14U divisions."),
        ("Sat 2:20 PM",  "Bay Area Tar Heels (White)",    "HOME", "Bay Area Tar Heels", DIV_13U_14U, "Filtered to 13U/14U divisions."),
    ]),
    ("Paxton — TM Griffins Black (entered as \"TM Basketball\")", "Paxton (TM Griffins Black)", "11u Black", "Menlo College, Court 2", [
        ("Sat 11:00 AM", "Westbay Ospreys (Tim)", "AWAY", "Westbay Ospreys (Tim)", DIV_11U_12U, "Filtered to 11U/12U divisions."),
        ("Sat 12:40 PM", "Team Esface 5th Goers", "HOME", "Team Esface 5th Goers",  DIV_11U_12U, "Filtered to 11U/12U divisions."),
    ]),
    ("Weston — SV Soldiers 10U", "Weston (SV Soldiers 10U)", "10u Green", "Red Morton Community Center", [
        ("Sat 9:20 AM",  "Cali Gold 4th (Dario)", "HOME", "Cali Gold 4th (Dario)", DIV_10U, "Filtered to 9U/10U/4th divisions."),
        ("Sat 11:00 AM", "Hayward Swoosh",         "HOME", "Hayward Swoosh", DIV_10U, "Filtered to 9U/10U/4th divisions (Hayward Swoosh runs teams at every age)."),
    ]),
]


def main():
    out = ["# Scouting Report — Soldier's South Bay Invitational, May 30-31, 2026",
           "",
           f"Compiled from {len(glob.glob('data/[0-9]*.json'))-1} historical NorCal tournaments (Jun 2025 - May 2026, this tournament excluded).",
           ""]
    for header, our_label, div, venue, sched in SCHEDULES:
        our_pat = OUR_PATS[our_label]
        out.append(f"## {header}")
        out.append(f"*Division: {div}. Venue: {venue}.*")
        out.append("")
        out.append("**Pool A schedule:**")
        out.append("")
        out.append("| Time | Opponent | Side |")
        out.append("|---|---|---|")
        for time, opp, side, _, _, _ in sched:
            out.append(f"| {time} | {opp} | {side} |")
        out.append("")
        for time, opp, side, opp_key, div_filter, div_note in sched:
            scheduled = f"{time} ({side})"
            out.append(render_opp_section(opp_key, OPP_PATS[opp_key], our_label, our_pat, scheduled, div_filter, div_note))
        out.append("---")
        out.append("")
    Path("data/scout_257525.md").write_text("\n".join(out))
    print("Wrote data/scout_257525.md")


if __name__ == "__main__":
    main()
