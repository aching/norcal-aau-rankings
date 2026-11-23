"""Explainable evidence-confidence labels for ranked team profiles.

Confidence describes available evidence, not the probability that a rating or
rank is correct. It consumes the same active games/opponents as the scorer.
"""
from datetime import date

from html_utils import esc


LOW_ACTIVE_GAMES = 6
LOW_OPPONENT_COVERAGE = 0.50
HIGH_ACTIVE_GAMES = 12
HIGH_OPPONENT_COVERAGE = 0.80
RECENT_DAYS = 30


def _day(value):
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def rate_confidence(games, opponent_ids, model_team_ids, as_of):
    """Return Low/Medium/High evidence support plus its underlying facts."""
    active_games = len(games)
    modeled = set(model_team_ids)
    covered = sum(1 for oid in opponent_ids
                  if oid is not None and oid in modeled)
    coverage = covered / active_games if active_games else 0.0
    reference = _day(as_of) or date.today()
    dates = [day for day in (_day(g[0]) for g in games if g) if day]
    latest = max(dates, default=None)
    age_days = (reference - latest).days if latest else None

    if active_games < LOW_ACTIVE_GAMES or coverage < LOW_OPPONENT_COVERAGE:
        level = "low"
    elif (active_games >= HIGH_ACTIVE_GAMES
          and coverage >= HIGH_OPPONENT_COVERAGE
          and age_days is not None and age_days <= RECENT_DAYS):
        level = "high"
    else:
        level = "medium"
    return {
        "level": level,
        "active_games": active_games,
        "covered_opponents": covered,
        "coverage": coverage,
        "latest_game": latest.isoformat() if latest else "",
        "latest_age_days": age_days,
    }


def _short_date(value):
    day = _day(value)
    if day is None:
        return "latest date unknown"
    return f"latest {day.month}/{day.day}/{day.year}"


def render_confidence(info):
    """Render a compact visible evidence summary inside the Why section."""
    if not isinstance(info, dict):
        return ""
    level = str(info.get("level", "")).lower()
    if level not in {"low", "medium", "high"}:
        return ""
    try:
        games = int(info.get("active_games", 0))
        covered = int(info.get("covered_opponents", 0))
        coverage = max(0.0, min(1.0, float(info.get("coverage", 0.0))))
    except (TypeError, ValueError):
        return ""
    latest = _short_date(info.get("latest_game", ""))
    summary = (f"{games} active games · {covered}/{games} opponents covered "
               f"({coverage:.0%}) · {latest}")
    return (f'<p class="confidence confidence-{esc(level)}">'
            f'<strong>Confidence: {esc(level.title())}</strong> '
            f'<span>{esc(summary)}</span>'
            '<span class="confidence-note">Evidence grade only; not a '
            'probability of exact placement. High requires ≥12 games, '
            '≥80% coverage, and a game within 30 days.</span></p>')
