# 0001 — Store event streams; derive every odometer and due state

Status: accepted

## Context

The wear rules are a yard sale of special cases: wet rides invalidate a km clock,
trainer rides wear some parts and not others, sealant runs on the calendar and
depends on the last product used, quick links count uses rather than distance,
and a measurement can outrank the odometer. A part can also move between bikes or
be retired and re-installed.

If the app stored running totals (`km_since_wax`, `uses`, `due_on`), every rule
would have to remember to update every affected counter, and a correction — a
wrong wet flag, a ride moved to another bike, a backdated maintenance event —
would require a migration back through history. The spec's worst failure mode is
silent non-accrual, so correctness after edits matters more than read speed.

## Decision

- Persist **streams**: ride rows, maintenance events, and install/uninstall
  windows. Do not persist derived counters.
- Derive per-part odometers and due states from those streams on read.
- Keep the derivation in a **pure wear engine** (`app/wear/`) with plain-data
  inputs and outputs, no ORM, no clock reads, no I/O.
- Keep persistence and the engine separate: `app/ledger.py` translates rows to
  engine inputs and returns statuses for rendering.

## Consequences

- Editing or deleting a ride/event, or moving a ride between bikes, recomputes
  the whole ledger correctly with no repair logic.
- The engine is exhaustively testable as input/output pairs, and the HTTP tests
  exercise the same engine end-to-end so the seam cannot drift.
- Reads scale with the number of rides and parts for a user. That is fine for a
  personal, self-hosted ledger; if it stops being fine, add a materialized cache
  behind the same engine interface, not counters written by hand.
- The seed data lives in rows, and the catalog/parts hold rules, so the engine
  has no hard-coded thresholds.
