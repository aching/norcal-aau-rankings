#!/usr/bin/env python3
"""Upcoming FastBreak games indexed by resolved AAU team identity."""
import datetime as dt
import re

from html_utils import esc, external_link

DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.I)


def event_day(value):
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except (TypeError, ValueError):
            pass
    return None


def fastbreak_date(value, event_start=None):
    """Parse full-year dates, or legacy month/day dates using the event year."""
    full_date = event_day(value)
    if full_date:
        return full_date
    start = event_day((event_start or "")[:10])
    if not start:
        return None
    match = re.fullmatch(r"\s*([A-Za-z]+)\s+(\d{1,2}),?\s*", value or "")
    if not match:
        return None
    month_name, day_text = match.groups()
    for fmt in ("%b", "%B"):
        try:
            month = dt.datetime.strptime(month_name, fmt).month
        except ValueError:
            continue
        day = int(day_text)
        candidates = []
        for year in (start.year - 1, start.year, start.year + 1):
            try:
                candidates.append(dt.date(year, month, day))
            except ValueError:
                pass
        if candidates:
            return min(candidates, key=lambda candidate: abs((candidate - start).days))
    return None


def time_key(value):
    match = TIME_RE.search(value or "")
    if not match:
        return 24 * 60
    hour = int(match.group(1)) % 12
    minute = int(match.group(2))
    return hour * 60 + minute + (12 * 60 if match.group(3).lower() == "pm" else 0)


def opponent_pending(name):
    value = (name or "").strip().lower()
    return (not value or any(token in value for token in
            ("tbd", "tba", "to be determined")) or
            value.startswith(("winner of", "loser of")))


def upcoming_by_team(cur, today=None, horizon=31):
    today = today or dt.date.today()
    query = """
    SELECT g.event_id,g.game_id,g.date,g.weekday,g.time,g.division_name,g.pool,
           g.home_team,g.away_team,g.venue,g.court,g.status,g.home_score,g.away_score,
           e.title,e.url,e.city,e.start_date,
           COALESCE(hl.team_id,hn.team_id),COALESCE(al.team_id,an.team_id),
           hl.confidence,al.confidence,hl.provider_team_id,al.provider_team_id
    FROM fb_games g
    JOIN fb_events e ON e.event_id=g.event_id
    LEFT JOIN fb_team_links hl ON hl.event_id=g.event_id AND hl.game_id=g.game_id AND hl.side='home'
    LEFT JOIN fb_team_links al ON al.event_id=g.event_id AND al.game_id=g.game_id AND al.side='away'
    LEFT JOIN team_names hn ON hn.raw_name=g.home_team AND hn.division_hint=g.division_name
                             AND hn.confidence != 'bare'
    LEFT JOIN team_names an ON an.raw_name=g.away_team AND an.division_hint=g.division_name
                             AND an.confidence != 'bare'
    WHERE lower(g.status) NOT IN ('final','completed','complete')
    """
    index = {}
    for row in cur.execute(query):
        (event_id, game_id, date_text, weekday, time, division, pool,
         home, away, venue, court, status, hs, a_s,
         title, url, city, event_start, home_id, away_id, home_conf, away_conf,
         home_provider_id, away_provider_id) = row
        date = fastbreak_date(date_text, event_start)
        if date is None or date < today or date > today + dt.timedelta(days=horizon):
            continue
        # Provider status, not placeholder score fields, decides whether a
        # fixture is scheduled or completed. Scheduled scores are never shown.
        for side, own, opponent, team_id, opponent_id, confidence, provider_id in (
                ("home", home, away, home_id, away_id, home_conf, home_provider_id),
                ("away", away, home, away_id, home_id, away_conf, away_provider_id)):
            if not team_id:
                continue
            game = {"event_id": event_id, "game_id": game_id, "event": title,
                    "url": url, "date": date.isoformat(), "weekday": weekday,
                    "time": time, "division": division, "pool": pool,
                    "side": side, "opponent": opponent or "TBD",
                    "opponent_team_id": opponent_id,
                    "opponent_pending": opponent_pending(opponent),
                    "own_team": own, "provider_team_id": provider_id,
                    "venue": venue, "court": court, "city": city,
                    "status": status, "identity_confidence": confidence or ""}
            index.setdefault(team_id, []).append(game)
    for games in index.values():
        games.sort(key=lambda g: (g["date"], time_key(g["time"]), g["game_id"]))
    return index


def profile_href(page_of, team_id):
    """Resolve the page map used by team_page (string) or all_pages_map (tuple)."""
    value = page_of.get(team_id)
    if isinstance(value, str):
        profile = value
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        profile = f"teams/{value[0]}/{value[1]}"
    else:
        return ""
    parts = profile.split("/")
    if len(parts) != 3 or parts[0] != "teams":
        return ""
    scope, level, filename = parts
    if level not in {"11u", "12u", "13u", "14u", "15u"}:
        return ""
    if not filename.endswith(".html") or "/" in filename or "\\" in filename or ".." in filename:
        return ""
    return "../../" + profile


def render_upcoming_games(games, page_of):
    """Render upcoming FastBreak fixtures inside an AAU team profile."""
    if not games:
        return ""
    rows = []
    source_aliases = set()
    for game in games:
        opponent = esc(game["opponent"])
        profile = profile_href(page_of, game["opponent_team_id"])
        if profile:
            opponent = (f'<a href="{esc(profile)}" '
                        f'title="AAU profile: {esc(game["opponent_team_id"])}">{opponent}</a>')
        status = '<div style="color:var(--mut);font-size:12px">opponent pending</div>' \
            if game["opponent_pending"] else ""
        event = external_link(game["url"], game["event"])
        place_parts = [p for p in (game["venue"], game["city"]) if p]
        place = esc(" / ".join(dict.fromkeys(place_parts)))
        court = game["court"]
        if court:
            place += esc(f" · Court {court}" if court.isdigit() else f" · {court}")
        pieces = [game["division"], game["pool"]]
        details = esc(" · ".join(p for p in pieces if p))
        rows.append(
            f'<tr><td>{esc(game["weekday"])} {esc(game["date"])}</td>'
            f'<td>{esc(game["time"])}</td><td>{opponent}{status}</td>'
            f'<td>{event}<div style="color:var(--mut);font-size:12px">{place}</div></td>'
            f'<td>{details}</td></tr>')
        if game["identity_confidence"] == "curated" and game["provider_team_id"]:
            source_aliases.add(game["own_team"])
    alias_note = ""
    if source_aliases:
        alias_note = ("<div>Event-scoped roster aliases: "
                      + esc(", ".join(sorted(source_aliases)))
                      + ". Other program labels are not globally merged.</div>")
    return ('<section id="scheduled-games" class="note"><h2>Upcoming schedule '
            f'({len(games)})</h2><p style="font-size:12px">Published FastBreak times; '
            'opponent-pending slots are marked rather than treated as confirmed matchups. '
            'Check the event source for updates.</p>'
            '<table class="detail"><thead><tr><th>Date</th><th>Time</th><th>Opponent</th>'
            '<th>Event / venue</th><th>Division / pool</th></tr></thead><tbody>'
            + "".join(rows)
            + '</tbody></table><div style="color:var(--mut);font-size:12px">'
            + alias_note + '</div></section>')
