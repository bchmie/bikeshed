# Bikeshed

A self-hosted bike maintenance tracker: an honest per-part wear ledger driven by
automatic ride ingestion. Built for the real rules — chains that need re-waxing by
kilometre *or* immediately after a wet ride, trainer kilometres that wear the
drivetrain but not the tires, calendar-based sealant intervals, and quick links
with a finite number of open/close cycles.

Single service, server-rendered (FastAPI + Jinja2), SQLite, no JS build step.

## Quick start (development)

```sh
uv sync
uv run python -m app
# open http://localhost:8000
```

The first account registered on a fresh deployment becomes the admin. Later
registrations need an invite code generated on the admin page.

Run the tests:

```sh
uv run pytest
uv run ruff check .
```

## Configuration

All configuration is environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `BIKESHED_DATABASE_URL` | `sqlite:///./data/bikeshed.db` | SQLAlchemy database URL. The parent directory is created automatically. |
| `BIKESHED_BASE_URL` | `http://localhost:8000` | Public URL; used for the Strava OAuth redirect. |
| `PORT` | `8000` | Port the single service listens on. |
| `STRAVA_CLIENT_ID` | — | Strava API application id. |
| `STRAVA_CLIENT_SECRET` | — | Strava API application secret. |
| `STRAVA_VERIFY_TOKEN` | — | Verify token configured on the Strava webhook subscription. |
| `BIKESHED_RECONCILE_TOKEN` | — | Shared secret required by `POST /internal/strava/reconcile`. |
| `BIKESHED_SESSION_DAYS` | `30` | Login session lifetime. |

Copy `.env.example` and fill it in for a real deployment.

## Strava setup

1. Create an API application at <https://www.strava.com/settings/api>.
2. Set **Authorization Callback Domain** to your instance's domain.
3. Set `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` and `BIKESHED_BASE_URL`.
4. In the app, open **Settings → Strava → Connect Strava**. The app requests only
   `profile:read_all` and `activity:read`.
5. Create the webhook subscription (once per app, not per user):

   ```sh
   curl -X POST https://www.strava.com/api/v3/push_subscriptions \
     -F client_id=$STRAVA_CLIENT_ID \
     -F client_secret=$STRAVA_CLIENT_SECRET \
     -F callback_url=$BIKESHED_BASE_URL/webhooks/strava \
     -F verify_token=$STRAVA_VERIFY_TOKEN
   ```

   The app answers the subscription challenge and handles `activity` create /
   update / delete events plus athlete deauthorization.
6. Import your Strava bikes on **Settings → Import bikes**. The lifetime km is
   pre-filled and editable — Strava's number only covers what Strava attributed
   to that bike.
7. Set your **default bike** and **trainer bike** on Settings.

Strava access tokens expire after six hours; the connector refreshes them
automatically before calling the API.

### Nightly reconciliation poll

The webhook is the fast path; the poll is the safety net for server downtime.
Run it from cron (or a systemd timer) once a night:

```sh
curl -fsS -X POST \
  -H "X-Reconcile-Token: $BIKESHED_RECONCILE_TOKEN" \
  https://bikeshed.example.com/internal/strava/reconcile
```

It fetches the last 30 days of activities for every connected user and upserts
any rides the webhook missed. Re-delivery is idempotent.

## Deployment

The app is one service listening on `PORT`. TLS, the domain, and the reverse
proxy are outside the app — point them at the container and forward the
`Host`/`X-Forwarded-*` headers.

```sh
docker compose up -d --build
# or
docker build -t bikeshed .
docker run -d --name bikeshed -p 8000:8000 \
  -v "$PWD/data:/data" \
  -e BIKESHED_BASE_URL=https://bikeshed.example.com \
  -e STRAVA_CLIENT_ID=... -e STRAVA_CLIENT_SECRET=... \
  bikeshed
```

The SQLite file lives in the mounted volume (`/data/bikeshed.db`). Back it up by
copying that file while the service is stopped (or with `sqlite3 .backup`). On
SELinux hosts (Fedora/RHEL/Podman) mount the volume with `:Z`, as the compose file
does.

## How it works

The **database stores streams, not running totals**:

- `Bike`, `Part` (a concrete instance), `Part Type` (catalog defaults)
- `Installation` — an install/uninstall window for a part on a bike
- `Ride` — slim derived data only: date, km, trainer, wet, bike, source, external id
- `MaintenanceEvent` — wax, sealant top-up, reading, manual uses adjustment, wash, service
- `Product` — user-editable sealant catalog with calendar intervals

The **wear engine** (`app/wear/`) is a pure module: parts + install windows +
rides + events + today → per-part odometers and due/warn/ok states. It has no I/O
and no ORM imports; `app/ledger.py` translates rows into plain values and back.
Because status is derived, changing a ride's bike or wet flag immediately moves
the wear — there is no accumulated counter to reconcile.

Attribution rules live next to the engine (`attribute_ride`): trainer rides go to
the trainer bike, a known Strava gear wins for outdoor rides, and anything else
falls to the default bike *flagged for review* — a guessed bike, never a silent
hole.

```
app/
  main.py          FastAPI app factory (database, fake-able Strava, clock)
  models.py        SQLAlchemy schema
  wear/            pure wear engine + plain-data types  ← Seam B
  ledger.py        DB → engine inputs → statuses / per-ride wear detail
  ingest.py        Strava payloads → slim rides, attribution, token refresh
  strava.py        HTTP client (the fake in tests implements the same protocol)
  webhooks.py      Strava webhook + reconcile endpoint
  auth.py          accounts, sessions, invites, admin
  bikes.py parts.py rides.py maintenance.py lifecycle.py settings.py strava_web.py
  templates/       Jinja2; server-rendered forms, progressive enhancement
  static/          CSS + the traced bike art
tests/
  conftest.py      HTTP-boundary harness: throwaway SQLite + fake Strava + fixed clock
  test_wear_engine.py  exhaustive input/output pairs for the pure engine  ← Seam B
  test_*.py        HTTP-boundary scenarios (Seam A)
```

Testing seams follow the spec: the HTTP boundary (Seam A) with a fake Strava, and
the pure engine (Seam B). Tests assert on responses and rendered content, not on
database rows.

## Product catalog

Part-type defaults are deliberately placeholders — they are the owner's data.
The catalog seeds chain (300 km), quick link (5 uses), tire (4,000 km), cassette
(8,000 km), brake pads (1,500 km), chainring / bottom bracket (10,000 km), and
sealant (days). Every value is editable per part; product intervals are editable
per user on Settings.

## Known limits (deliberately out of scope)

- No email/push notifications; the dashboard is the channel.
- Wet rides are toggled manually (no weather lookup).
- One bike drawing is shared by every bike; per-bike art is a later iteration.
- The drawing uses the manifest's **overlay** mode (cached `<img>` + translucent
  zones) rather than mask mode, so the 429 KB traced path is not inlined into
  every dashboard render. The zone geometry is identical either way.
- No JSON API, no FIT/GPX upload, no writing back to Strava.
- Deployment automation beyond the single-container compose example.
