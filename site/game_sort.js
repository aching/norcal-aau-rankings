/* Render UTC tip-offs in the viewer's timezone; date is the primary sort key. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.AauGameTimes = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function currentZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch (_) {
      return "UTC";
    }
  }

  // Numeric parts avoid locale/locale-calendar-dependent sort comparisons.
  function formatInstant(milliseconds, timeZone) {
    const zone = timeZone || currentZone();
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "numeric", minute: "2-digit", timeZoneName: "short",
    });
    const parts = {};
    formatter.formatToParts(new Date(milliseconds)).forEach((part) => {
      parts[part.type] = part.value;
    });
    return {
      dateKey: `${parts.year}-${parts.month}-${parts.day}`,
      dateLabel: `${parts.month}-${parts.day}`,
      timeLabel: [
        `${parts.hour}:${parts.minute}`, parts.dayPeriod,
        parts.timeZoneName || zone,
      ].filter(Boolean).join(" "),
      utc_ms: milliseconds,
      timeZone: zone,
    };
  }

  function _ms(value) {
    if (value === null || value === undefined || value === "") return null;
    const result = Number(value);
    return Number.isFinite(result) ? result : null;
  }

  function readRows(table, timeZone) {
    return Array.from(table.tBodies[0].rows).map((row, index) => {
      const instant = _ms(row.dataset.utcMs);
      const epoch = instant;
      const local = epoch === null ? null : formatInstant(epoch, timeZone);
      if (local) {
        row.children[0].textContent = local.dateLabel;
        if (row.children[1].querySelector("time")) {
          row.children[1].querySelector("time").textContent = local.timeLabel;
        } else {
          row.children[1].textContent = local.timeLabel;
        }
      }
      return {
        node: row,
        day: local ? local.dateKey : row.dataset.sourceDate || "0000-00-00",
        instant: epoch,
        original: index,
        known: Number(row.dataset.knownTime || 0),
      };
    });
  }

  function compareRows(a, b, direction) {
    // Always group by the displayed local date first, never time-of-day first.
    if (a.day !== b.day) return a.day < b.day ? 1 : -1;
    if (a.instant === null && b.instant === null) return a.original - b.original;
    if (a.instant === null) return 1;  // Missing time cannot become midnight.
    if (b.instant === null) return -1;
    if (a.instant === b.instant) return a.original - b.original;
    return direction * (a.instant - b.instant);
  }

  function sortRecords(records, direction) {
    return records.slice().sort((a, b) => compareRows(a, b, direction));
  }

  function sortTable(records, tbody, direction) {
    sortRecords(records, direction).forEach((record) => tbody.appendChild(record.node));
  }

  function init() {
    const table = document.getElementById("full-record");
    if (!table) return;
    const button = table.querySelector("[data-tipoff-sort]");
    if (!button) return;
    let latestFirst = true;
    let records = [];
    const tbody = table.tBodies[0];
    const status = document.getElementById("history-timezone");

    function render() {
      let zone;
        try {
          zone = currentZone();
          records = readRows(table, zone);
        } catch (_) {
          // Generated cells are already explicitly labelled as UTC.
          if (status) {
            status.textContent = "Your browser could not apply its timezone; "
              + "dates and times are shown in UTC. Date first, then time. "
              + "\u2014 means no valid timestamp.";
          }
          return;
        }
        sortTable(records, tbody, latestFirst ? -1 : 1);
      const indicator = button.querySelector("[data-sort-arrow]");
      if (indicator) indicator.textContent = latestFirst ? "↓" : "↑";
      button.setAttribute("aria-label", latestFirst
        ? "Latest game first within each date; switch to earliest within each date"
        : "Earliest game first within each date; switch to latest within each date");
      if (status) {
        const assumed = records.some((record) => ["1", "true"]
          .includes(record.node.dataset.assumedPacific));
        status.textContent = `Showing ${zone}. Date first, then ${latestFirst ? "latest" : "earliest"} tip-off.`
          + (assumed ? " Source timezone missing: Pacific is assumed. " : " ")
          + "— means no usable timestamp.";
      }
    }

    button.addEventListener("click", () => {
      latestFirst = !latestFirst;
      render();
    });
    window.addEventListener("focus", render);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) render();
    });
    render();
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
      init();
    }
  }
  return { formatInstant, compareRows, sortRecords, readRows, currentZone };
}));
