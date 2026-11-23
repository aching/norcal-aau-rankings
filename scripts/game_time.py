"""Normalize and order source game times without inventing missing values.

Providers supply a local game date plus either a 12- or 24-hour clock. EE also
has an explicit Windows-style TimeZone. Times without a timezone are treated
as a NorCal/Pacific assumption, recorded so the website can disclose it.
"""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
ZONE_ALIASES = {
    "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "pt": "America/Los_Angeles", "pacific standard time": "America/Los_Angeles",
    "pacific daylight time": "America/Los_Angeles", "pacific time": "America/Los_Angeles",
    "pacific standard time (mexico)": "America/Tijuana",
    "est": "America/New_York", "edt": "America/New_York",
    "eastern standard time": "America/New_York", "eastern daylight time": "America/New_York",
    "cst": "America/Chicago", "cdt": "America/Chicago",
    "central standard time": "America/Chicago", "central daylight time": "America/Chicago",
    "mst": "America/Denver", "mdt": "America/Denver",
    "mountain standard time": "America/Denver", "mountain daylight time": "America/Denver",
    "hst": "Pacific/Honolulu", "hawaii standard time": "Pacific/Honolulu",
    "akst": "America/Anchorage", "akdt": "America/Anchorage",
    "utc": "UTC", "gmt": "UTC", "z": "UTC", "coordinated universal time": "UTC",
}
CLOCK = re.compile(
    r"^\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
    r"(?:\s*(?P<meridian>[AaPp](?:\.)?[Mm](?:\.)?))?"
    r"(?:\s+(?P<zone>.+?))?\s*$"
)
OFFSET = re.compile(r"(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?$", re.I)


def _zone(value):
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    key = " ".join(raw.lower().replace("_", " ").split())
    if key in ZONE_ALIASES:
        return ZoneInfo(ZONE_ALIASES[key])
    offset = OFFSET.fullmatch(raw)
    if offset:
        sign, hour, minute = offset.groups()
        hours, minutes = int(hour), int(minute or 0)
        if minutes > 59 or hours > 14 or (hours == 14 and minutes):
            return None
        delta = (hours * 3600 + minutes * 60) * (-1 if sign == "-" else 1)
        return timezone(timedelta(seconds=delta))
    if "/" in raw:
        try:
            return ZoneInfo(raw)
        except ZoneInfoNotFoundError:
            return None
    return None


def source_time(date_text, clock, source_zone=None, provider=""):
    """Return source fields and UTC instant data for a game, or ``None``.

    An explicitly supplied but unrecognized timezone is never quietly replaced.
    If timezone metadata is absent, NorCal/Pacific is a documented fallback.
    """
    provider = str(provider or "").lower()
    if provider not in ("", "ee", "bt", "fb"):
        return None
    match = CLOCK.fullmatch(str(clock or ""))
    if not match or not date_text:
        return None
    hour = int(match["hour"])
    minute = int(match["minute"])
    second = int(match["second"] or 0)
    meridian = match.group("meridian")
    if hour > 23 or second > 59 or (meridian and not 1 <= hour <= 12):
        return None
    supplied_zone = source_zone if source_zone is not None else match.group("zone")
    if supplied_zone:
        tz = _zone(supplied_zone)
        if tz is None:
            return None
        assumed = False

    else:
        # These providers' unqualified clocks are within this NorCal pipeline.
        tz = datetime.now(ZoneInfo("America/Los_Angeles")).tzinfo
        assumed = True
        zone_name = "America/Los_Angeles"
    if meridian:
        hour %= 12
        if meridian.lower().startswith("p"):
            hour += 12
    try:
        day = date.fromisoformat(str(date_text)[:10])
        instant = datetime.combine(day, time(hour, minute, second), tzinfo=tz)
        utc = instant.astimezone(UTC)
        milliseconds = int(utc.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError) as exc:
        return None
    return {
        "source_time": " ".join(str(clock).split()),
        "source_timezone": str(supplied_zone or zone_name),
        "assumed_pacific": assumed,
        "utc": utc.isoformat().replace("+00:00", "Z"),
        "utc_ms": milliseconds,
    }


def _source(game):
    extra = game[11] if not isinstance(game, dict) and len(game) > 11 else {}
    extra = extra if isinstance(extra, dict) else {}
    if isinstance(game, dict):
        return (game.get("d", ""), game.get("tipoff"), extra, game.get("event", ""))
    return game[0], extra.get("tipoff"), extra, game[4]


def payload(game):
    """Return new portable JSON or an unknown-time payload for old records."""
    day, tipoff, extra, _ = _source(game)
    if not isinstance(tipoff, dict) or "utc_ms" not in tipoff:
        tipoff = source_time(day, tipoff.get("label") if isinstance(tipoff, dict) else tipoff,
                             extra.get("time_zone") or (tipoff.get("source_timezone")
                                                        if isinstance(tipoff, dict) else None),
                             extra.get("source", ""))
    return tipoff if isinstance(tipoff, dict) else {
        "source_time": None, "source_timezone": None,
        "assumed_pacific": False, "utc": None, "utc_ms": None,
    }


def timestamp_ms(game):
    """A finite UTC millisecond timestamp or None for untimed games."""
    value = payload(game).get("utc_ms")
    if value is None or isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value


def sort_key(game):
    instant = timestamp_ms(game)
    tick = payload(game).get("utc")
    date_text = tick[:10] if tick else str(_source(game)[0])[:10] or "0000-00-00"
    try:
        day = date.fromisoformat(date_text).toordinal()
    except ValueError:
        day = 1
    # Date is primary, time secondary; without a tertiary key ties stay stable.
    # Missing clocks stay last within their date, never an invented midnight.
    return day, instant if instant is not None else -1


def order_games(games):
    """Return rows with valid instants newest day/time first, stable on ties."""
    return sorted(games, key=sort_key, reverse=True)
