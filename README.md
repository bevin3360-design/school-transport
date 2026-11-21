# School Transport System (STS)

## Running Locally
```
python sts-platform/app.py
```
Open: http://localhost:5001. No accounts are seeded; create a super admin with
`python sts-platform/scripts/reset_superadmin_password.py` and register a school
from the public registration page.

## Ride-hailing database
The complete ride-hailing schema from the project specification is maintained in
`migrations/001_ride_hailing_schema.sql` under the PostgreSQL schema `ride_hailing`.
It includes PostGIS geography columns, spatial indexes, all ride, matching, tracking,
safety, support, verification, notification, and admin tables. Keeping it in a separate
PostgreSQL schema avoids collisions with the existing school transport tables.

Ride-hailing deployment requires PostgreSQL 15+ with PostGIS, `pgcrypto`, and `citext`.
Set `DATABASE_URL` to that PostgreSQL instance; the platform start script applies
`migrations/001_ride_hailing_schema.sql` (idempotent) before starting the app. Without a
PostgreSQL connection, the school app still starts on SQLite, but ride-hailing is unavailable.

Ride-hailing is off unless `RIDE_HAILING_ENABLED=1` is set. Keep it off, or restricted to
administrators, until the Phase 7 checks in the master plan pass.

The ride portal is available at `/rides`, `/rides/driver`, and `/rides/admin` once enabled;
the first ride administrator is created at `/rides/setup` by the platform super admin.
Before accepting trips, configure a service area and vehicle types, set fares, and review
drivers and vehicles. Driver documents must use private storage keys and checksums; do not
store identity files in the application database.

### Required environment variables

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Required in production. The app refuses to start without it instead of using the old fallback key. |
| `DATABASE_URL` | PostgreSQL 15+ with PostGIS for ride-hailing; omit to run the school app on SQLite. |
| `SUPERADMIN_USERNAME`, `SUPERADMIN_PASSWORD` | Optional first-boot super-admin bootstrap (password at least 12 characters). No default account is created. |
| `STS_COOKIE_SECURE` | `1` or `0` to force secure cookies; defaults to on for Railway and Render. |
| `RIDE_HAILING_ENABLED` | `1` enables the ride-hailing module; any other value keeps it off. |

### Recovering the platform super-admin password

There is no self-service password reset because the platform has no verified email or SMS
recovery channel. An authorized deployment operator can run
`python sts-platform/scripts/reset_superadmin_password.py` from the repository root, or
`python scripts/reset_superadmin_password.py` from `sts-platform`. The script targets
`DATABASE_URL` and refuses to touch a local SQLite database unless
`STS_ALLOW_SQLITE_RESET=1` is set. It prompts for the username and a new password without
echoing the password, and can create the account if it does not exist. Do not share the new
password in chat.

The API uses a recent route-cache entry when one is available. If no routing provider has
populated the cache, distance and duration estimates fall back to straight-line distance
and are approximate. The supplied ride schema intentionally has no payment processing.
Web sign-in uses signed Flask sessions; OTP delivery, mobile refresh-token flows, push
delivery, private document storage, and a live routing provider must be configured
separately before relying on those services in production.

## Super-admin security
Production deployments must set a strong `SECRET_KEY`; hosted deployments refuse to start
without it. No default super-admin password is created or logged.

To bootstrap a new database, set `SUPERADMIN_INITIAL_PASSWORD` (12–128 characters) and,
optionally, `SUPERADMIN_USERNAME` (defaults to `superadmin`) before startup, then remove
them. To rotate an existing Render account without shell access, set
`SUPERADMIN_RESET_PASSWORD` in the service environment, wait for the deploy, then remove it
and wait for the follow-up deploy. The app never logs the value. See
[Recovering the platform super-admin password](#recovering-the-platform-super-admin-password)
for the interactive alternative.

## Deploying

### Railway
1. Create a Railway project and add a PostgreSQL 15+ database with PostGIS available.
2. Set `DATABASE_URL`, `SECRET_KEY`, and, on first boot, the super-admin bootstrap variables.
3. Connect the repository. Either the repository root or `sts-platform` works as the service
   root; both `railway.toml` files point at the same start script.
4. Leave `RIDE_HAILING_ENABLED` unset until the Phase 7 checks pass.
5. The start script applies the ride schema when `DATABASE_URL` is PostgreSQL, initializes
   the app database once, then starts Gunicorn on `$PORT`.

### Render
1. Create an account at https://render.com and push this repository to GitHub.
2. New → Web Service → connect the repository.
3. Build command: `pip install -r requirements.txt`.
4. Start command: `python sts-platform/scripts/start_railway.py`.
5. Set the environment variables above; do not rely on generated defaults for `SECRET_KEY`.

## Admin Features
- Set school name
- Activate/deactivate morning routes
- Add/edit/delete teachers and routes
- Generate daily duty roster (auto-skips weekends)
- Mark absent → auto-suggests replacements
- View full audit log
- Manage admin accounts (Coordinator / Headteacher / IT)

## Parent Pickup & Drop-off
- Parents can save separate pickup and drop-off landmarks, optionally with their current GPS coordinates.
- Pickup and drop-off alerts include a snapshot of the saved stop so later edits do not change an alert already sent.
- Drivers see the stop in the alert and can open directions in Google Maps.

## Allocation Rules
1. Teacher who worked yesterday is rested today
2. Teacher must rotate through ALL routes before repeating any
3. No teacher dominates a single route
4. Morning routes only run when activated by admin
