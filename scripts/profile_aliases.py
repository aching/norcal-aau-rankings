"""Source-name aliases for canonical team profiles (stdlib/SQLite only)."""
from html_utils import esc


def profile_aliases(db):
    """Return team_id -> sorted raw source labels for each multi-name team.

    The canonical team_id already carries cohort/gender boundaries, so
    grouping by it cannot leak labels from another age or girls roster.
    """
    grouped = {}
    for raw, team_id in db.execute(
            "SELECT DISTINCT raw_name, team_id FROM team_names "
            "WHERE raw_name IS NOT NULL AND trim(raw_name) <> ''"):
        by_folded_name = grouped.setdefault(team_id, {})
        raw = raw.strip()
        by_folded_name.setdefault(raw.casefold(), raw)
    return {team_id: sorted(names.values(), key=str.casefold)
            for team_id, names in grouped.items() if len(names) > 1}


def render_aliases(aliases):
    """Render an escaped, collapsed alias list; one name is not an alias."""
    names = {}
    for alias in aliases or []:
        alias = alias.strip()
        if alias:
            names.setdefault(alias.casefold(), alias)
    if len(names) < 2:
        return ""
    ordered = sorted(names.values(), key=str.casefold)
    items = "".join(f"<li>{esc(name)}</li>" for name in ordered)
    return (f'<details class="note aliases"><summary>Known aliases '
            f'({len(ordered)})</summary><ul>{items}</ul></details>')
