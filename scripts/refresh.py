#!/usr/bin/env python3
"""
Full refresh pipeline: discovery -> scrape -> database, for both sources.

Usage:
  python3 refresh.py status            # run nothing; report freshness per source
  python3 refresh.py progress          # run nothing; report live progress of running jobs
  python3 refresh.py [--no-bt] [--no-ee] [--no-db] [--since YYYY-MM-DD]
                                      # run the pipeline (all stages by default)

Stages:
  1. discovery — re-poll listings. EE: list_events.py over [since, today] into a
     dated snapshot (events_ca_<date>.json). BT: search is folded into the
     scrape step (its index only surfaces current events; no snapshot kept).
  2. scrape — diff snapshot/index against data/*.json and scrape what's new.
  3. database — rebuild data/aau.db from all JSON (mirrors ledger + watermarks).

Freshness model (per source), stored in data/scrape_state.json:
  runs.<source>.<job>.finished_at  — when did the job last run
  content.<source>.last_event_end   — newest tournament end-date actually on disk
  content.<source>.last_game_date   — newest game date actually on disk

`status` prints both, so "last run" vs "last data" are never confused.
"""
import glob, json, os, re, sqlite3, sys, time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from scrape_state import load, update_content

DATA = HERE.parent / "data"


def ee_watermark():
    ends, games, tids = [], [], []
    for f in glob.glob(str(DATA / "[0-9]*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        tids.append(str(d.get("tournament_id")))
        for e in [d.get("metadata", {}).get("title", "")]:
            pass
        for g in d.get("games", []):
            dt = g.get("DateFormatted") or ""
            try:
                m, dd, y = dt.split("/")
                games.append(f"{y}-{int(m):02d}-{int(dd):02d}")
            except ValueError:
                pass
    # tournament end dates come from the events snapshots
    for snap in sorted(glob.glob(str(DATA / "events_ca*.json"))):
        try:
            for e in json.load(open(snap)):
                if str(e.get("Id")) in set(tids) and e.get("EndDate"):
                    ends.append(e["EndDate"])
        except Exception:
            continue
    wm = {}
    if ends:
        i = ends.index(max(ends))
        wm["last_event_end"] = max(ends)
    if tids:
        wm["last_event_id"] = max(tids, key=lambda t: (len(t), t))
    if games:
        wm["last_game_date"] = max(games)
    return update_content("exposureevents", wm) if wm else {}


def bt_watermark():
    ends, games, eids = [], [], []
    for f in glob.glob(str(DATA / "bt_*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        eids.append(int(d.get("event_id", 0)))
        if d.get("end_date"):
            ends.append(d["end_date"])
        for m in d.get("games", []):
            if m.get("date"):
                games.append(m["date"])
    wm = {}
    if ends:
        wm["last_event_end"] = max(ends)
    if eids:
        wm["last_event_id"] = max(eids)
    if games:
        wm["last_game_date"] = max(games)
    return update_content("bracketteam", wm) if wm else {}


def show_status():
    state = load()
    print(f"{'source':<16}{'job':<18}{'last run':<20}{'status':<8}stats")
    for key in sorted(state.get("runs", {})):
        r = state["runs"][key]
        stats = json.dumps(r.get("stats", {}))
        print(f"{r['source']:<16}{r['job']:<18}{r.get('finished_at') or '-':<20}"
              f"{r.get('status') or '-':<8}{stats[:80]}")
    print()
    print(f"{'source':<16}{'last_event_end':<16}{'last_game_date':<16}checked")
    for source, c in state.get("content", {}).items():
        print(f"{source:<16}{c.get('last_event_end') or '-':<16}"
              f"{c.get('last_game_date') or '-':<16}{c.get('updated_at') or '-'}")
    # live DB row counts when available
    db = DATA / "aau.db"
    if db.exists():
        con = sqlite3.connect(db)
        try:
            ee = con.execute("SELECT COUNT(*) FROM ee_games").fetchone()[0]
            bt = con.execute("SELECT COUNT(*) FROM bt_games").fetchone()[0]
            print(f"\ndb: ee_games={ee} bt_games={bt}")
        except Exception as e:
            print(f"\ndb: present but unreadable ({e})")
        con.close()


def parse_log_progress(path):
    """Parse a batch log into a progress dict. Returns None if no log/empty.

    Understands START/DONE lines plus per-item lines:
      [i/N] SCRAPE <id> <slug> (<city>) ending <date>   (EE backfills)
      [i/N] SCRAPE <id> <name> (<date>)                 (BT backfill)
      [i/N] RESCRAPE <id> <slug>                        (rescrape-empty)
      [i/N] SKIP ... / FAIL ...                         (any)
    """
    lines = path.read_text().splitlines() if path.exists() else []
    if not lines:
        return None
    prog = {"log": path.name, "total": None, "done": 0, "skipped": 0, "failed": 0,
            "current": None, "started": None, "finished": None, "items": []}
    for ln in lines:
        m = re.match(r"\[(\d\d:\d\d:\d\d)\] START[^\d]*(\d+)", ln)
        if m:
            prog["started"] = m.group(1)
        m = re.match(r"\[(\d\d:\d\d:\d\d)\] DONE[^\n]*scraped (\d+), skipped (\d+), failed (\d+)", ln)
        if not m:
            m = re.match(r"\[(\d\d:\d\d:\d\d)\] DONE[^\n]*filled (\d+), still empty (\d+), failed (\d+)", ln)
        if m:
            prog["finished"] = m.group(1)
            prog["done"], prog["skipped"], prog["failed"] = map(int, m.groups()[1:])
            continue
        m = re.match(r"\[\d\d:\d\d:\d\d\] \[(\d+)/(\d+)\] (SCRAPE|RESCRAPE|SKIP|FAIL)\s+(\S+)\s*(.*?)\s*$", ln)
        if m:
            idx, total, verb, item_id, rest = m.groups()
            prog["total"] = int(total)
            end_m = re.search(r"ending (\d{4}-\d\d-\d\d)", rest)
            date_m = re.search(r"\((\d{4}-\d\d-\d\d)\)", rest)
            prog["items"].append({"id": item_id, "verb": verb,
                                  "end": (end_m or date_m).group(1) if (end_m or date_m) else None,
                                  "detail": rest[:60]})
            if verb in ("SCRAPE", "RESCRAPE"):
                prog["done"] = int(idx)
                prog["current"] = prog["items"][-1]
            elif verb == "SKIP":
                prog["skipped"] += 1
            elif verb == "FAIL":
                prog["failed"] += 1
    if prog["total"] is None and prog["items"]:
        prog["total"] = len(prog["items"])
    return prog


def show_progress():
    """One-screen view of running (or last) jobs: window + current item + rate."""
    logs = {"EE refresh": DATA / "_refresh_ee_progress.log",
            "EE backfill H2": DATA / "_batch_h2_progress.log",
            "EE rescrape-empty": DATA / "_rescrape_progress.log",
            "BT backfill": DATA / "_batch_bt_progress.log",
            "EE backfill (May)": DATA / "_batch_progress.log"}
    state = load()
    for label, path in logs.items():
        prog = parse_log_progress(path)
        if not prog:
            continue
        total, done = prog["total"] or "?", prog["done"]
        pct = f"{100 * done / total:.0f}%" if isinstance(total, int) and total else "-"
        status = "DONE " + (prog["finished"] or "") if prog["finished"] else "RUNNING"
        print(f"{label} [{status}] {done}/{total} ({pct})"
              f"{' failed=' + str(prog['failed']) if prog['failed'] else ''}")
        if prog["items"]:
            ends = [i["end"] for i in prog["items"] if i["end"]]
            if ends:
                print(f"  window: {min(ends)} -> {max(ends)} (tournament end dates, newest-first queue)")
        if prog["current"] and not prog["finished"]:
            c = prog["current"]
            print(f"  now: {c['id']} {c['detail']}" + (f" ending {c['end']}" if c["end"] else ""))
    # ledger summary: last run per job (authoritative for "when did it run")
    print("\nledger (last run per job):")
    for key in sorted(state.get("runs", {})):
        r = state["runs"][key]
        print(f"  {r['source']}:{r['job']} finished={r.get('finished_at')} status={r.get('status')} "
              f"{json.dumps(r.get('stats', {}))[:100]}")
    print("\ncontent watermarks (newest data on disk):")
    for source, c in state.get("content", {}).items():
        print(f"  {source}: last_event_end={c.get('last_event_end')} "
              f"last_game_date={c.get('last_game_date')} checked={c.get('updated_at')}")


def run_pipeline(do_ee=True, do_bt=True, do_db=True, since=None):
    from list_events import main as discover
    from batch_scrape import main as scrape_ee_batch, is_norcal, is_circuit
    from scrape_tournament import scrape_tournament
    from batch_scrape_bracketteam import discover_events, main as scrape_bt_batch

    today = date.today().isoformat()
    if do_ee:
        since = since or "2026-05-30"
        # discovery window extends past today: the EE listing omits events
        # spanning the window edge, so `end=today` misses tournaments ending
        # this weekend (e.g. 273462, 255460 absent from the 11/14 snapshot).
        # The StartDate<=today scrape gate below decides what's actionable.
        from datetime import timedelta
        discover_end = (date.today() + timedelta(days=3)).isoformat()
        snap = f"events_ca_refresh_{today}.json"
        print(f"== discovery (EE {since} -> {discover_end}) ==")
        discover(since, discover_end, snap)
        # scrape new NorCal tournaments started by today (includes multi-day
        # events in progress -- Saturday games of a Sat-Sun event are final
        # and scrapable on Saturday; EndDate<=today waited until Monday).
        # Circuit events (Jr EYBL / 3SSB / 3Stripes / UAA) bypass the city
        # gate: SoCal-based but NorCal teams travel (user-confirmed Nov
        # 2026). Camps/tryouts never match is_circuit (no bracket games).
        have = {Path(p).stem for p in glob.glob(str(DATA / "[0-9]*.json"))}
        evs = json.load(open(DATA / snap))
        new = [e for e in evs
               if (is_norcal(e.get("City")) or is_circuit(e.get("Name")))
               and (e.get("StartDate") or "") <= today
               and str(e["Id"]) not in have]
        # re-scrape in-progress tournaments already on disk (Sunday scores
        # post after Saturday's scrape; skip unless event ends today+)
        have_in_progress = [e for e in evs
               if (is_norcal(e.get("City")) or is_circuit(e.get("Name")))
               and (e.get("StartDate") or "") <= today
               and (e.get("EndDate") or "") >= today
               and str(e["Id"]) in have]
        new.sort(key=lambda e: e["EndDate"] or "")
        # in-progress re-scrapes, oldest-end first (Sunday scores land after
        # Saturday's scrape); attempted with the same politeness, failures
        # (e.g. 429) logged not fatal
        have_in_progress.sort(key=lambda e: e["EndDate"] or "")
        from scrape_state import record as rec, Progress
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        done = failed = 0
        rescraped = resfailed = 0
        ee_log = DATA / "_refresh_ee_progress.log"
        prog = Progress(len(new), label="EE refresh")
        print(f"== scrape ({len(new)} new EE tournaments) ==")
        with open(ee_log, "a") as lf:
            def log(msg):
                line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
                lf.write(line); lf.flush(); print(line, end="", flush=True)
            log(f"START - {len(new)} new + {len(have_in_progress)} in-progress NorCal tournaments from refresh discovery")
            for i, e in enumerate(new, 1):
                tid = str(e["Id"])
                slug = e.get("Slug") or e["Name"].lower().replace(" ", "-")
                try:
                    log(f"[{i}/{len(new)}] SCRAPE {tid} {slug[:40]:40} "
                        f"({(e.get('City') or '?')[:18]:18}) ending {e.get('EndDate', '?')}")
                    prog.render(f"SCRAPE {tid} {slug[:40]}")
                    scrape_tournament(tid, slug, str(DATA))
                    done += 1
                    prog.tick(msg=f"SCRAPE {tid}")
                except Exception as ex:
                    log(f"[{i}/{len(new)}] FAIL {tid} {ex}")
                    failed += 1
                    prog.tick(failed=1, msg=f"FAIL {tid}")
            prog.finish(f"scraped {done}, skipped 0, failed {failed}")
            log(f"DONE - scraped {done}, skipped 0, failed {failed}")
            if have_in_progress:
                log(f"RESCRAPE - {len(have_in_progress)} in-progress tournaments (scores may have posted since last scrape)")
                for i, e in enumerate(have_in_progress, 1):
                    tid = str(e["Id"])
                    slug = e.get("Slug") or e["Name"].lower().replace(" ", "-")
                    try:
                        log(f"[re {i}/{len(have_in_progress)}] RESCRAPE {tid} {slug[:40]:40} "
                            f"ending {e.get('EndDate', '?')}")
                        scrape_tournament(tid, slug, str(DATA))
                        rescraped += 1
                    except Exception as ex:
                        log(f"[re {i}/{len(have_in_progress)}] RE-FAIL {tid} {ex}")
                        resfailed += 1
                log(f"RE-DONE - rescraped {rescraped}, failed {resfailed}")
        rec("exposureevents", "refresh",
            {"queued": len(new), "scraped": done, "failed": failed,
             "rescraped": rescraped, "rescrape_failed": resfailed},
            status="ok" if not failed and not resfailed else "failed", started_at=started)
        ee_watermark()
    if do_bt:
        print("== scrape (bracketteam) ==")
        scrape_bt_batch(str(DATA))
        bt_watermark()
    if do_db:
        print("== database ==")
        ee_watermark()
        bt_watermark()
        from build_db import main as build
        build(str(DATA / "aau.db"))
    show_status()


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if not args or args == {"status"}:
        show_status()
    elif args == {"progress"}:
        show_progress()
    else:
        since = None
        for a in sys.argv[1:]:
            if a.startswith("--since="):
                since = a.split("=", 1)[1]
        run_pipeline(do_ee="--no-ee" not in args, do_bt="--no-bt" not in args,
                     do_db="--no-db" not in args, since=since)
