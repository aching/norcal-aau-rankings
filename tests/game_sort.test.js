/* Optional Node test for the browser-only conversion and sorting helpers. */
"use strict";
const assert = require("node:assert/strict");
const {formatInstant, sortRecords} = require("../scripts/game_sort.js");

const early = Date.UTC(2026, 10, 21, 16, 0);
const late = Date.UTC(2026, 10, 21, 17, 40);
const utc = formatInstant(early, "UTC");
assert.equal(utc.dateKey, "2026-11-21");
assert.equal(utc.timeLabel, "4:00 PM UTC");

const eastern = formatInstant(early, "America/New_York");
assert.equal(eastern.dateKey, "2026-11-21");
assert.equal(eastern.dateLabel, "11-21");
assert.ok(eastern.timeLabel.startsWith("11:00 AM"), eastern.timeLabel);
assert.equal(eastern.timeZone, "America/New_York");

// UTC 16:00 on Nov 21 is the next local calendar date in Tokyo.
assert.equal(formatInstant(early, "Asia/Tokyo").dateKey, "2026-11-22");
assert.equal(formatInstant(late, "America/Los_Angeles").timeLabel, "9:40 AM PST");

const rows = [
  {day: "2026-11-21", instant: late, original: 0},
  {day: "2026-11-22", instant: late, original: 1},
  {day: "2026-11-21", instant: early, original: 2},
  {day: "2026-11-21", instant: null, original: 3},
];
assert.deepEqual(sortRecords(rows, -1).map((row) => row.original), [1, 0, 2, 3]);
assert.deepEqual(sortRecords(rows, 1).map((row) => row.original), [1, 2, 0, 3]);
// Ties are stable, and missing clocks never become midnight or jump a date.
const tied = [rows[0], {...rows[0], original: 3}];
assert.deepEqual(sortRecords(tied, -1).map((row) => row.original), [0, 3]);
assert.deepEqual(sortRecords(tied, 1).map((row) => row.original), [0, 3]);
assert.deepEqual(rows.map((row) => row.original), [0, 1, 2, 3]);
