# Glossary

The project's domain vocabulary. Use these words in code, tests, tickets, and UI.

- **Bike** — a physical bicycle. Has an optional Strava gear id, a starting
  odometer, and may be the *Default Bike* or the *Trainer Bike*.
- **Part** — a concrete instance, not a type: "Chain #3", "the rear tire on the
  gravel bike". Carries its own rules and its own history.
- **Part Type** — a catalog entry of defaults for a kind of part (chain, tire,
  sealant...). Structure only; every value is editable per part.
- **Wear Unit** — what a part's clock counts: `km`, `days`, `wet_rides`, or
  `uses`.
- **Wear Flags** — `wears-on-trainer` (does the part accrue on trainer rides?)
  and `wears-when-wet` (does a wet ride invalidate its service clock?).
- **Installation / Uninstall Event** — the lifecycle window that puts a part on
  a bike. Re-installing a part starts a new window and keeps its lifetime total.
- **Maintenance Event** — something that moves the ledger: re-wax, sealant
  top-up, reading, manual uses adjustment, wash, service. Events are the only
  way counters reset.
- **Reading** — a measurement recorded on an event (e.g. chain stretch %). When
  present, a measurement threshold outranks the odometer.
- **Quick Action** — a one-tap plain-default event on the dashboard or part page,
  expandable for notes, readings, product, and amount.
- **Ride** — slim derived ride data: date, distance, trainer flag, wet flag,
  bike, source connector, external id. Raw connector payloads are never stored.
- **Connector** — a source of rides. Strava today; the seam allows others.
- **Attribution** — deciding which bike a ride belongs to. Trainer → trainer
  bike; known Strava gear → that bike; otherwise default bike **flagged for
  review**.
- **Recent Rides Strip** — the compact ride ledger on the dashboard where wet and
  bike attribution are fixed inline.
- **Wear Engine** — the pure module mapping (parts, install windows, rides,
  events, today) to per-part odometers and due states. No I/O.
- **Needs Attention** — the fleet-wide list of due and due-soon parts, numbered
  to match the pins on the bike drawing.
- **Quick Link** — a part whose wear unit is `uses`, normally attached to a
  specific chain. Re-waxes on that chain increment its use count.
- **Product Catalog** — the user-editable list of sealant products and their
  calendar intervals (Orange Seal Regular: 45 days; Endurance: 90 days).
- **Default Bike** — where rides with no attributable gear land.
- **Trainer Bike** — where trainer rides land without per-ride effort.
