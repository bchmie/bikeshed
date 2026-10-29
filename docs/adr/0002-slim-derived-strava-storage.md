# 0002 — Slim derived Strava storage behind a connector seam

Status: accepted

## Context

Strava is the canonical ride pipe, but its API agreement imposes a
purpose-limited retention posture: no long-lived raw payload cache. The app needs
enough ride data to run the wear ledger and nothing more. Future data sources
(FIT upload, other services) should be able to sit beside Strava without changing
the ledger.

## Decision

- A ride row stores only **derived** data: date, distance km, trainer flag, wet
  flag (default false, user-togglable), attributed bike, source connector, and
  external id. Raw Strava JSON is discarded immediately after ingest.
- The connector is a small protocol (`app/strava.py`). The real implementation
  uses HTTP; tests inject a fake that speaks the same protocol, including OAuth
  token exchange, athlete/bike fetch, activity fetch/list, refresh, and
  deauthorization.
- Ingestion is idempotent on `(user, source, external_id)`: a re-delivered
  webhook or a reconciliation poll refreshes the derived numbers without
  clobbering a user-confirmed bike or a wet flag.
- Deauthorization webhooks delete the connection; rides already derived remain
  part of the user's ledger.

## Consequences

- The app can honestly claim a slim, defensible data footprint.
- The ledger never depends on Strava-specific payload shapes; the ingest layer
  reduces them at the boundary.
- Tests never call the real Strava API and assert on HTTP-visible behavior.
- If another connector lands, it writes the same slim `Ride` rows and gets the
  same attribution rules.
