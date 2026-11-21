# School Transport System (STS)

## Default Login Credentials

### Admin
- **URL:** http://localhost:5000
- **Username:** `admin`
- **Password:** `admin123`
- **Role:** IT Expert (full access)

### Sample Teachers (12 pre-loaded)
| Name | Teaching Code | Passcode |
|------|--------------|---------|
| Alice Mwangi | TCH001 | 1001 |
| Bob Odhiambo | TCH002 | 1002 |
| Carol Njeri | TCH003 | 1003 |
| David Kamau | TCH004 | 1004 |
| Eve Wanjiru | TCH005 | 1005 |
| Frank Otieno | TCH006 | 1006 |
| Grace Achieng | TCH007 | 1007 |
| Henry Mutua | TCH008 | 1008 |
| Irene Chebet | TCH009 | 1009 |
| James Kariuki | TCH010 | 1010 |
| Karen Auma | TCH011 | 1011 |
| Liam Ndirangu | TCH012 | 1012 |

## Running Locally
```
python app.py
```
Open: http://localhost:5000

## Ride-hailing database
The complete ride-hailing schema from the project specification is maintained in
`migrations/001_ride_hailing_schema.sql` under the PostgreSQL schema `ride_hailing`.
It includes PostGIS geography columns, spatial indexes, all ride, matching, tracking,
safety, support, verification, notification, and admin tables. Keeping it in a separate
PostgreSQL schema avoids collisions with the existing school transport tables.

Ride-hailing deployment requires PostgreSQL 15+ with PostGIS, `pgcrypto`, and `citext`.
Set `DATABASE_URL` to that PostgreSQL instance before running
`python scripts/apply_ride_schema.py`. The migration runner is idempotent and is included
in the Render start command. Without a PostgreSQL connection, the existing SQLite-backed
school transport system remains available, while ride-hailing API requests return an
explicit service-unavailable response.

The ride portal is available at `/rides`, `/rides/driver`, and `/rides/admin`. The first
administrator account is created at `/rides/setup` by the existing platform super administrator.
Before accepting trips, an administrator must configure at least one active service area
and vehicle type, set fares, and review drivers and vehicles. Driver document records
expect keys and checksums from a private file-storage system; do not use public URLs or
store identity files in the application database.

The API uses a recent route-cache entry when one is available. If no routing provider has
populated the cache, distance and duration estimates fall back to straight-line distance
and are approximate. The supplied ride schema intentionally has no payment processing.
Web sign-in uses signed Flask sessions; OTP delivery, mobile refresh-token flows, push
delivery, private document storage, and a live routing provider must be configured
separately before relying on those services in production.

## Deploying to Render (Free Internet Hosting)
1. Create account at https://render.com
2. Push this folder to a GitHub repo
3. On Render: New → Web Service → connect your repo
4. Build command: `pip install -r requirements.txt`
5. Start command: the configured Render command applies the ride-hailing schema, initializes the legacy app database, and starts Gunicorn.
6. Free tier gives you a public URL like `https://your-app.onrender.com`

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


## Recovering the platform super-admin password

There is no self-service password reset because no verified recovery email or SMS channel is configured. An authorized deployment operator can use the Render service shell and run `python scripts/reset_superadmin_password.py` from the service root. The script prompts for the username and new password with masked input. Do not pass passwords in command arguments or share them in chat.
