#!/usr/bin/env python3
"""
Team identity resolution: raw name strings -> canonical team ids.

Two layers:
  1. normalize(name) — deterministic cleanup: strip rank prefixes (#2),
     unify separators, extract age/grade/gender/coach tokens. Produces a
     canonical key. No judgment calls here.
  2. OVERRIDES — curated (program, level) -> canonical team id for the cases
     normalization can't solve: bare program labels ("TM Basketball" at 14U),
     cross-name aliases ("TM Falcons" = 14U "TM Basketball"), ranked squads.

Seeded from session research (Oct 2026). Extend by adding rows, not by
special-casing in queries.

team_id format: "<program-slug>:<level>" e.g. "tm:falcons-14u".
level uses the age/grade as played (13u, 14u, 8th...), NOT normalized across
the grade-up transition: 2026-spring 13u Falcons and 2026-fall 14u Falcons
are different team_ids linked by successor_of.
"""
import re

# Exact squad/year aliases where age/grade naming splits one squad into two
# identities. These intentionally do not generalize across grades or years.
SQUAD_ALIASES = {
    ("oakland soldiers camo", "8th grade boys (2030)"):
        "oakland soldiers camo:14u",
}

# Provider/event-scoped roster aliases supplied by explicit squad evidence.
# These never make a program-wide label globally equivalent to one squad.
EVENT_PROVIDER_ALIASES = {
    # Thanksgiving HoopFest 2026: TM Falcons Black, 14u Silver Sat Only.
    ("11535", "280786"): "tm:falcons-black-14u",
}


def event_provider_alias(event_id, provider_team_id):
    return EVENT_PROVIDER_ALIASES.get((str(event_id), str(provider_team_id or "")))


RANK_PREFIX = re.compile(r"^#\d+\s*")
PAREN_AGE = re.compile(r"\(\s*(\d{1,2})\s*[uU]\s*(?:/\s*\d{1,2}\s*[uU])?\s*(?:girls?)?\s*\)")
BARE_AGE = re.compile(r"\b(1[0-8]|[5-9])\s*[uU]\b")
GRADE = re.compile(r"\b([5-9]|1[0-2])\s*(?:th|st|nd|rd)?\s*grade\b", re.I)
GIRLS = re.compile(r"\bgirls?\b|\b(anita|lady|ladies)\b", re.I)
WS = re.compile(r"\s+")

# (program keyword, age-token) -> canonical team id.
# age-token is matched against the raw lowercased name + division string.
OVERRIDES = [
    # TM program: Falcons track (user-confirmed Nov 2026: the 13U-spring
    # "TM Falcons" and the 14U-fall "TM Falcons 14U" are the same cohort
    # aged up -- merge everything into tm:falcons-14u; the bare blob id
    # retires. "TM Basketball" 14U/8th stays as the alternate name.)
    # SPLIT Nov 2026 (user-confirmed): Falcons Black and Falcons Red are
    # DISTINCT squads -- they co-occur in the same event twice (May
    # Anderson shootout, Nov GSG showcase) and never play each other.
    # Black is the fall A-squad (Nov GSG: 1-1, beat Adapt 42-24, lost
    # 31-34 to Vision Black); Red is the B-squad (Nov GSG: 0-2, -10/-16).
    # age_kw pins the squad (black/red/14u): most-specific keyword wins,
    # so "TM Falcons Black 14U" hits Black, "TM Falcons 14U" hits the
    # 14u rule (Black, A-squad default), and bare "TM Falcons" hits the
    # era base. Spring-13U bare "TM Falcons" stays on tm:falcons-14u
    # (successors link the 13U history).
    (("tm falcons black", "14u"), "tm:falcons-black-14u"),
    (("tm falcons black", "8th"), "tm:falcons-black-14u"),
    (("tm falcons black", "13u"), "tm:falcons-black-13u"),
    (("tm falcons black", "7th"), "tm:falcons-black-13u"),
    (("tm falcons red", "14u"), "tm:falcons-red-14u"),
    (("tm falcons red", "8th"), "tm:falcons-red-14u"),
    (("tm falcons red", "13u"), "tm:falcons-red-13u"),
    (("tm falcons red", "7th"), "tm:falcons-red-13u"),
    (("tm falcons 14u", "14u"), "tm:falcons-black-14u"),
    (("tm falcons 14u", "8th"), "tm:falcons-black-14u"),
    # Coach-first-name spellings (user-confirmed Nov 2026, BT event 8432
    # South Bay Showdown): "TM Dashawn" = Falcons Black, "TM Tony" =
    # Falcons Red. Pinned at 14u/8th only (the confirmed level) -- a bare
    # coach name at any other age stays unresolved rather than guessed.
    (("tm dashawn", "14u"), "tm:falcons-black-14u"),
    (("tm dashawn", "8th"), "tm:falcons-black-14u"),
    (("tm tony", "14u"), "tm:falcons-red-14u"),
    (("tm tony", "8th"), "tm:falcons-red-14u"),
    # bare "TM Falcons" with NO age in name or division: era base only
    # (prevents "TM Falcons" matching the 14u rules above when the age
    # comes from neither name nor division).
    (("tm falcons", "14u"), "tm:falcons-14u"),
    (("tm falcons", "8th"), "tm:falcons-14u"),
    (("tm falcons", "13u"), "tm:falcons-14u"),
    (("tm falcons", "7th"), "tm:falcons-14u"),
    (("tm falcons", None), "tm:falcons-14u"),
    # NOTE: "TM Basketball" is the club name -- "TM Basketball" alone is
    # unattributable (could be Black/Red/Griffins); only resolve it when a
    # level token disambiguates, handled below at match time.
    (("tm basketball", "14u"), "tm:falcons-black-14u"),
    (("tm basketball", "8th"), "tm:falcons-black-14u"),
    # TM Griffins rename (user-confirmed Nov 2026): bare "TM Basketball"
    # entries (year-round, latest 10/24 Soldiers Halloween) and explicit
    # "TM Griffins 12U" entries (GSG x BAM Nov events, from 10/31) are
    # the same squad -- the registration label just gained "Griffins".
    # Same program, adjacent windows, never co-occur. Merge into the
    # history-carrying tm:griffins-12u.
    (("tm griffins 12u", "12u"), "tm:griffins-12u"),
    (("tm griffins 12u", "6th"), "tm:griffins-12u"),
    (("tm griffins 12u", None), "tm:griffins-12u"),
    (("tm basketball", "12u"), "tm:griffins-12u"),
    (("tm basketball", "6th"), "tm:griffins-12u"),
    # TM Vipers rename (user-confirmed Nov 2026): bare "TM Basketball"
    # 11U entries (year-round, latest 10/24 Soldiers Halloween) and
    # explicit "TM Vipers 11U" entries (GSG x BAM Oct 31 + Nov 7) are
    # the same squad -- the registration label gained "Vipers".
    # Same program, adjacent windows, never co-occur. Merge into the
    # history-carrying tm basketball:11u id. The age travels with the
    # name ("TM Vipers 11U" in a 6th division = playing up, still the squad),
    # consistent with the Griffins/BMG merges. Other TM 11U squads (Club,
    # Dragons, Warriors, bare TM) which remain separate ids.
    (("tm vipers 11u", "11u"), "tm basketball:11u"),
    (("tm vipers 11u", "5th"), "tm basketball:11u"),
    (("tm vipers 11u", None), "tm basketball:11u"),
    # Cali Gold ranked 8th squads
    (("cali gold", "mike"), "cali-gold:mike-8th"),
    (("cali gold", "brian"), "cali-gold:brian-8th"),
    (("cali gold", "kaden"), "cali-gold:kaden-8th"),
    # Tarheels color squads (boys 8th)
    (("tarheel", "white"), "tarheels:white-8th"),
    (("tarheel", "blue"), "tarheels:blue-8th"),
    (("tarheel", "carolina"), "tarheels:carolina-8th"),
    # BMG Soldiers: "BMG Soldiers 14U National" is the same squad as
    # "BMG 14U National" (user-confirmed Nov 2026); the Soldiers name
    # appears when they play up (15U). Level stays 14U.
    # "Silicon Soldiers - Prospects" 11/2026: misregistration of BMG 14U
    # Prospects at the Hoop Explosion (user-confirmed Nov 2026) -- the raw
    # name exists only 4x, all in 255460 14u D1. Alias it, don't merge the
    # whole Silicon program (separate org, still active at other ages).
    (("bmg soldiers", "national"), "bmg national:14u"),
    # SV Soldiers -> BMG rename, 12U Prospects only (user-confirmed Nov
    # 2026): "SV Soldiers 12U Prospects" and "BMG 12u Prospects" are the
    # same squad; SV was renamed to BMG mid-season. prog_kw carries the
    # age so 13U/14U SV squads never match. Singular "Prospect" (Mar
    # 2026, separate identity) doesn't contain "prospects" as a
    # substring... it does ("prospect" in "prospects" is False direction;
    # check: "prospects" in "sv soldiers 12u prospect" -> False). Safe.
    (("sv soldiers 12u", "prospects"), "bmg prospects:12u"),
    (("silicon soldiers - prospects", "14u"), "bmg prospects:14u"),
    # "Silicon Valley Soldiers" 12u (Hoop Explosion Nov 14 2026, 2-0):
    # same squad as BMG 12u Prospects (user-confirmed Nov 2026) -- same
    # program relationship as the 14U alias above, same active window
    # (Prospects latest 11/7). Pinned to the full program name so the
    # 2025 "SV Soldiers"/"SV SOLDIERS" Gold/Platinum rows (a different
    # era/squad, sv soldiers:12u) never match.
    (("silicon valley soldiers", "12u"), "bmg prospects:12u"),
    # WeCompete 14U flagship (user-confirmed Nov 2026): "WeCompete 14u
    # Grizzlies Gold", "We Compete Grizzlies gold" (Nov 7-8 Rumble),
    # "WeCompete Nation Grizzles Elite" (one-S typo) and the bare
    # "WeCompete Nation Grizzlies 14u" are the same squad -- merge into
    # wecompete grizzlies gold:14u. Verified: Gold and Elite never co-occur
    # in the same event (corpus scan 11/16). Black stays separate (B-team:
    # co-occurs with Elite, Bronze/Silver/D2 tiers) -- the two guard
    # entries below MUST stay first so "14u Black" never falls through to
    # the flagship ("nation grizzlies 14u" is a substring of the Black
    # name). "Bears" is a different mascot in the same org -- never match.
    (("nation grizzlies 14u black", "14u"), "wecompete nation grizzlies black:14u"),
    (("nation grizzlies 14u black", "8th"), "wecompete nation grizzlies black:14u"),
    (("grizzlies gold", "14u"), "wecompete grizzlies gold:14u"),
    (("grizzlies gold", "8th"), "wecompete grizzlies gold:14u"),
    (("grizzles elite", "14u"), "wecompete grizzlies gold:14u"),
    (("grizzles elite", "8th"), "wecompete grizzlies gold:14u"),
    (("nation grizzlies 14u", "14u"), "wecompete grizzlies gold:14u"),
    (("nation grizzlies 14u", "8th"), "wecompete grizzlies gold:14u"),
    # "WeCompete Nation Grizzlies" at 14U/8th: the bare label is the SAME
    # flagship (only the B-team carries "Black"; Silver-flight entries are
    # the flagship playing down, like the Sep Fall Classic 15U Yellow
    # title -- same team, weaker bracket, no separate squad ever
    # co-occurs). 13U-and-under bare labels stay separate (younger
    # pipeline), so the age_kw carries 14u/8th only.
    (("nation grizzlies", "14u"), "wecompete grizzlies gold:14u"),
    (("nation grizzlies", "8th"), "wecompete grizzlies gold:14u"),
    # BMG National grade-up (user-confirmed Nov 2026): the Aug-2026
    # "BMG 13u National" entries in 14u DIVISIONS (Back-to-School:
    # BGA loss, 2 wins, Prospects final loss) are the same cohort as
    # today's BMG 14u National (#3). Genuine 13U-division games
    # ("BMG National" in 13U/7th Grade Gold) stay on bmg national:13u
    # -- these rules only fire when the division blob says 14u/8th.
    (("bmg 13u national", "14u"), "bmg national:14u"),
    (("bmg 13u national", "8th"), "bmg national:14u"),
    (("bmg 13u national", None), "bmg national:14u"),
    # FastBreak full-grade labels (user-confirmed Nov 2026): FastBreak
    # renders "Team Name 8th/14U" while EE renders "Team Name 14U" --
    # the "8th/14u" suffix survives normalize() into the program key
    # ("lakeshow fuca 8th/", "norcal elite allocco 8th/"), splitting one
    # team into two ids. These rules catch the FastBreak spellings.
    # Verified: no co-occurrence (corpus scan 11/16) -- same teams,
    # different source labels.
    (("lakeshow 14u fuca 8th/14u", None), "lakeshow fuca:14u"),
    # Parenthesized-coach spelling (user-confirmed Nov 2026): Thanksgiving
    # HoopFest uses this label for the same 14U squad above. Keep the merge
    # scoped to this exact FastBreak label, not other Lakeshow cohorts.
    (("lakeshow 14u (fuca) 8th/14u", "14u"), "lakeshow fuca:14u"),
    (("lakeshow 14u (fuca) 8th/14u", "8th"), "lakeshow fuca:14u"),
    # Lakeshow Duckett 14U (user-confirmed Nov 2026): same squad as the
    # bare Lakeshow Duckett 14U label. Explicit 13U play-ups stay separate.
    (("lakeshow 14u duckett 8th/14u", "14u"), "lakeshow duckett:14u"),
    (("lakeshow 14u duckett 8th/14u", "8th"), "lakeshow duckett:14u"),
    # LGSR 8th (user-confirmed Nov 2026): FastBreak's grade-qualified label
    # belongs to the same 14U squad as bare LGSR, not other LGSR cohorts.
    (("lgsr 8th", "14u"), "lgsr:14u"),
    (("lgsr 8th", "8th"), "lgsr:14u"),
    # NBBA 8th UA (K. Winter) (user-confirmed Nov 2026): exact Thanksgiving
    # HoopFest label for bare 14U NBBA. Do not infer other NBBA coach merges.
    (("nbba 8th ua (k. winter) 8th/14u", "14u"), "nbba:14u"),
    (("nbba 8th ua (k. winter) 8th/14u", "8th"), "nbba:14u"),
    # Barnstomers (user-confirmed Nov 2026): literal source misspelling of
    # Barnstormers. Restrict the correction to this 14U label/cohort.
    (("barnstomers 14u", "14u"), "barnstormers:14u"),
    (("barnstomers 14u", "8th"), "barnstormers:14u"),
    # NorCal Elite Allocco (user-confirmed Nov 2026): "NorCal Elite 14u
    # (Allocco) 8th/14U" (FB Fall Classic 9/19-20: NBBA/Fuca/Flow Elite
    # + WeCompete Black) is the same squad as "NorCal Elite 14U
    # (Allocco)" (EE JRP32 9/12-13 + Hoop Explosion 11/14-15). Same
    # coach, level, window, gold tier; never co-occur. 13 games combined.
    # Keyword carries the full FB suffix (the bare-None guard can't strip
    # the "8th/" remainder, so pin the rule on the division blob instead).
    (("norcal elite 14u (allocco) 8th/14u", "14u"), "norcal elite allocco:14u"),
    (("norcal elite 14u (allocco) 8th/14u", "8th"), "norcal elite allocco:14u"),
    # BMG 13U flagship (user-confirmed Nov 2026): "BMG 13u" (Oct Bay Area
    # Fall Classic 7th Boys Gold, 4-0) and "BMG 13u Elite" (Sep G365 King
    # of the Town + Nov Rumble, 5-2) are the same squad -- merge into
    # bmg:13u. Verified: never co-occur in the same event. Prospects /
    # Select / Premier / Prime / National / Soldiers Elite stay separate
    # (different tiers/squads; Premier+Prime co-occur with Elite events).
    (("bmg 13u elite", "13u"), "bmg:13u"),
    (("bmg 13u elite", "7th"), "bmg:13u"),
    (("bmg 13u elite", None), "bmg:13u"),
    # BMG Prospects (user-confirmed Nov 2026): \"BMG Prospects 14u 8th/14U\"
    # (FB Fall Classic 9/19-20, 4-0 silver) is the same squad as
    # "BMG 14U/14u Prospects" (EE Aug-Nov). Same FastBreak-suffix split,
    # same program/level; never co-occur. 19 games combined.
    (("bmg prospects 14u 8th/14u", "14u"), "bmg prospects:14u"),
    (("bmg prospects 14u 8th/14u", "8th"), "bmg prospects:14u"),
    # Team UNEQLD Marques (user-confirmed Nov 2026 for 14U; same pattern
    # at 13U): FastBreak "Team UNEQLD (Marques) 8th/14U" (Thanksgiving
    # HoopFest, 14u Gold) is the same squad as EE "Team Unequal -
    # Marques" (14u Division 1) -- same coach, UNEQLD/Unequal spelling
    # plus the FastBreak full-grade suffix split the identity. Merge
    # into the history-carrying EE ids; the coach name keeps other
    # UNEQLD squads (Reggie/Trey/bare) untouched.
    (("team uneqld (marques) 8th/14u", "14u"), "team unequal marques:14u"),
    (("team uneqld (marques) 8th/14u", "8th"), "team unequal marques:14u"),
    (("team uneqld (marques) 7th/13u", "13u"), "team unequal marques:13u"),
    (("team uneqld (marques) 7th/13u", "7th"), "team unequal marques:13u"),
]

# team_id -> successor team_id (grade-up / rename continuity)
SUCCESSORS = {
    "tm:falcons-13u": "tm:falcons-14u",
    "tm:falcons": "tm:falcons-14u",
    "tm:griffins-11u": "tm:griffins-12u",
    "tm:griffins": "tm:griffins-12u",
    # BMG National grade-up (user-confirmed Nov 2026): the Aug-2026
    # "BMG 13u National" that played up in the 14u division at
    # Back-to-School (2-2: BGA loss, 2 wins, Prospects final loss) is
    # the same cohort as today's BMG 14u National (#3). Merge so the
    # August 14u-division games feed the current id -- and BGA's 36-34
    # win confers credit against a #3-level opponent.
    "bmg national:13u": "bmg national:14u",
}


def division_age(division):
    """Return the age/grade suffix encoded in a division label, if any."""
    m = PAREN_AGE.search(division or "")
    if m:
        return m.group(1) + "u"
    m = BARE_AGE.search(division or "")
    if m:
        return m.group(1) + "u"
    # Circuit shorthand such as "EYCL 17'S" means 17U.
    m = re.search(r"\b(1[0-8])\s*['’]s\b", division or "", re.I)
    if m:
        return m.group(1) + "u"
    m = GRADE.search(division or "")
    if m:
        return m.group(1) + "th"
    m = re.search(r"\b([5-9]|1[0-2])\s*(?:th|st|nd|rd)\b", division or "", re.I)
    if m:
        return m.group(1) + "th"
    return ""


def age_cohort(age):
    """Return a comparable age-group number (8th == 14U, 11th == 17U)."""
    m = re.fullmatch(r"([5-9]|1[0-8])u", (age or "").lower())
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"([5-9]|1[0-2])(?:th|st|nd|rd)", (age or "").lower())
    if m:
        return int(m.group(1)) + 6
    return None


def normalize(name):
    """Return dict(program, age, grade, girls, rank, key)."""
    raw = name.strip()
    rank = None
    m = RANK_PREFIX.match(raw)
    if m:
        rank = m.group(0).strip()
        raw = raw[m.end():]
    girls = bool(GIRLS.search(raw))
    age, grade = None, None
    m = PAREN_AGE.search(raw)
    if m:
        age = m.group(1) + "u"
    else:
        m = BARE_AGE.search(raw)
        if m:
            age = m.group(1) + "u"
    m = GRADE.search(raw)
    if m:
        grade = m.group(1) + "th"
    core = PAREN_AGE.sub("", raw)
    core = BARE_AGE.sub("", core)
    core = GRADE.sub("", core)
    core = GIRLS.sub("", core)
    # Treat slash as a separator too. FastBreak grade/age suffixes
    # (e.g. "8th/14U") must not leave a dangling "/" in canonical ids.
    core = re.sub(r"[-–—:;,.()/]+", " ", core)
    core = WS.sub(" ", core).strip().lower()
    key = core
    if age:
        key += f" {age}"
    elif grade:
        key += f" {grade}"
    if girls:
        key += " girls"
    return {"program": core, "age": age, "grade": grade, "girls": girls,
            "rank": rank, "key": key}


def resolve(name, division=""):
    """Return (team_id, confidence) for a raw team name + division string.

    confidence: 'override' (curated), 'normalized' (deterministic key),
    'bare' (program label only, ambiguous across ages — caller must qualify
    with division or treat as unknown).
    """
    alias_key = (name.strip().casefold(), " ".join((division or "").split()).casefold())
    if alias_key in SQUAD_ALIASES:
        return SQUAD_ALIASES[alias_key], "curated"
    low = name.lower()
    div_girls = bool(GIRLS.search(division or ""))
    # Girls divisions never hit the boys overrides (user-confirmed Nov
    # 2026): "TM Basketball" in a girls 14U division is the girls squad,
    # not tm:falcons-14u. Girls programs have no curated overrides --
    # they fall through to the normalized girls ids below.
    if not div_girls:
        for (prog_kw, age_kw), team_id in OVERRIDES:
            if prog_kw not in low:
                continue
            if age_kw is None:
                # bare override: fires when the name itself is exactly the program
                # team label (no separate program word + suffix). "TM Falcons",
                # "TM Falcons Black" carry no other program token, so they ARE
                # the team — unlike "TM Basketball", which is the club name.
                rest = low.replace(prog_kw, "").strip()
                rest_stripped = re.sub(r"\b(1[0-8]|[5-9])\s*u\b|\b([5-9]|1[0-2])\s*(th|st|nd|rd)?\s*grade\b|\(.*?\)", "", rest).strip()
                # Exact-name guard: the rule's keyword must cover the
                # whole team label. "TM Falcons 14U" must NOT match the
                # ("tm falcons", None) rule -- its "14u" remainder belongs
                # to the ("tm falcons 14u", None) Black rule evaluated in
                # order. An age remainder only passes when the rule's own
                # keyword already carries that age (e.g. "tm falcons 14u"
                # rule matching "TM Falcons 14U (Smith)").
                rest_age = re.search(r"\b(1[0-8]|[5-9])\s*u\b|\b([5-9]|1[0-2])\s*(th|st|nd|rd)?\s*grade\b", rest)
                if rest_age and not re.search(r"1[0-8]|[5-9]|grade|th|st|nd|rd", prog_kw):
                    continue
                if rest_stripped == "" or re.fullmatch(
                        r"(black|red|white|blue|gold|elite|select|premier|national|north|south|east|west|a|b|i|ii)+", rest_stripped):
                    return team_id, "override"
                continue
            blob = f"{name} {division}".lower()
            if age_kw in blob:
                return team_id, "override"
    n = normalize(name)
    if not n["age"] and not n["grade"]:
        # Level-split for bare program labels (user-confirmed Nov 2026):
        # a name with no age of its own ("Fury", "TM Basketball") is NOT
        # one team -- it's one squad per level. Qualify with the
        # division's age/grade so 14U Gold Fury and 10U Fury resolve to
        # different ids. Division carries the signal; the name doesn't.
        # Girls divisions ALWAYS split, even when the name has no age
        # (user-confirmed Nov 2026: bare "Team Legree 14U" in a girls
        # division is the girls squad, never the boys id).
        level = division_age(division)
        if level:
            if div_girls or n["girls"]:
                return f"{n['program']}:{level} girls", "normalized"
            return f"{n['program']}:{level}", "normalized"
        if div_girls or n["girls"]:
            return f"prog:{n['program'] or 'unknown'} girls", "bare"
        return f"prog:{n['program'] or 'unknown'}", "bare"
    if div_girls and not n["girls"]:
        return f"{n['program']}:{n['age'] or n['grade']} girls", "normalized"
    return f"{n['program']}:{n['age'] or n['grade']}", "normalized"
