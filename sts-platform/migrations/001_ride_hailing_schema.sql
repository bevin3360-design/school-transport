-- The complete ride-hailing schema is isolated to avoid collisions with the legacy app.
CREATE SCHEMA IF NOT EXISTS ride_hailing;
SET search_path TO ride_hailing, public;

-- ====================================================================
-- RIDE-HAILING PLATFORM: FULL DATABASE SCHEMA (no payments)
-- PostgreSQL 15+ with PostGIS. Run top to bottom.
-- Sections: 0 Setup | 1 Accounts | 2 Driver verification | 3 Vehicles
--           4 Service areas & navigation | 5 Rides & matching
--           6 Live tracking | 7 Ratings & safety | 8 Support & admin
--           9 Notifications | 10 Indexes
-- =====================================================================

-- ---------- 0. SETUP ----------
-- PostGIS must live where application sessions resolve it (public), not in
-- ride_hailing, because runtime SQL uses unqualified ST_* and ::geometry.
CREATE EXTENSION IF NOT EXISTS postgis SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA public;
CREATE EXTENSION IF NOT EXISTS citext SCHEMA public;
-- Optional, only if you run your own road graph:
-- CREATE EXTENSION IF NOT EXISTS pgrouting;

CREATE TYPE user_role           AS ENUM ('rider','driver','admin','support');
CREATE TYPE account_status      AS ENUM ('active','suspended','banned','deleted');
CREATE TYPE verification_status AS ENUM ('not_started','pending','in_review','approved','rejected','expired');
CREATE TYPE document_type       AS ENUM ('national_id','passport','drivers_license','vehicle_registration',
                                         'insurance','operator_badge','good_conduct_certificate',
                                         'vehicle_inspection','profile_selfie','vehicle_photo');
CREATE TYPE check_type          AS ENUM ('identity','license','background','vehicle','insurance','selfie_match');
CREATE TYPE driver_availability AS ENUM ('offline','online','on_trip');
CREATE TYPE ride_status         AS ENUM ('requested','matching','driver_assigned','driver_arrived',
                                         'in_progress','completed','cancelled_by_rider',
                                         'cancelled_by_driver','no_drivers_found','expired');
CREATE TYPE offer_status        AS ENUM ('sent','accepted','declined','timed_out','cancelled');
CREATE TYPE ticket_status       AS ENUM ('open','in_progress','resolved','closed');
CREATE TYPE sos_status          AS ENUM ('triggered','acknowledged','resolved','false_alarm');

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

-- ---------- 1. ACCOUNTS ----------
CREATE TABLE users (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  role            user_role NOT NULL,
  phone_e164      text UNIQUE NOT NULL,
  phone_verified  boolean NOT NULL DEFAULT false,
  email           citext UNIQUE,
  email_verified  boolean NOT NULL DEFAULT false,
  password_hash   text,                       -- null if phone-OTP only
  full_name       text NOT NULL,
  avatar_url      text,
  language        text NOT NULL DEFAULT 'en',
  status          account_status NOT NULL DEFAULT 'active',
  last_login_at   timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE otp_codes (
  id          bigserial PRIMARY KEY,
  phone_e164  text NOT NULL,
  code_hash   text NOT NULL,
  attempts    int  NOT NULL DEFAULT 0,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE devices (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  platform     text NOT NULL CHECK (platform IN ('ios','android','web')),
  push_token   text,
  app_version  text,
  last_seen_at timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, push_token)
);

CREATE TABLE sessions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id     uuid REFERENCES devices(id) ON DELETE SET NULL,
  refresh_hash  text NOT NULL,
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rider_profiles (
  user_id          uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  rating_avg       numeric(3,2) NOT NULL DEFAULT 5.00,
  rating_count     int NOT NULL DEFAULT 0,
  total_trips      int NOT NULL DEFAULT 0
);

CREATE TABLE emergency_contacts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        text NOT NULL,
  phone_e164  text NOT NULL,
  relationship text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE saved_places (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label     text NOT NULL,                   -- Home, Work, custom
  address   text,
  location  geography(Point,4326) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- 2. DRIVER PROFILE AND VERIFICATION ----------
CREATE TABLE driver_profiles (
  user_id               uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  verification_status   verification_status NOT NULL DEFAULT 'not_started',
  verified_at           timestamptz,
  rejection_reason      text,
  availability          driver_availability NOT NULL DEFAULT 'offline',
  current_vehicle_id    uuid,                -- FK added after vehicles table
  rating_avg            numeric(3,2) NOT NULL DEFAULT 5.00,
  rating_count          int NOT NULL DEFAULT 0,
  total_trips           int NOT NULL DEFAULT 0,
  acceptance_rate       numeric(5,2),
  cancellation_rate     numeric(5,2),
  date_of_birth         date,
  home_address          text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_driver_profiles_updated BEFORE UPDATE ON driver_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Files live in encrypted object storage; the DB keeps only the pointer and a hash.
-- Do NOT store raw ID numbers in plain text: store encrypted or a salted hash.
CREATE TABLE driver_documents (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  driver_id          uuid NOT NULL REFERENCES driver_profiles(user_id) ON DELETE CASCADE,
  doc_type           document_type NOT NULL,
  storage_key        text NOT NULL,          -- path in private bucket
  file_sha256        text NOT NULL,
  document_number_enc bytea,                 -- encrypted at app level (KMS)
  issued_at          date,
  expires_at         date,
  status             verification_status NOT NULL DEFAULT 'pending',
  reviewed_by        uuid REFERENCES users(id),
  reviewed_at        timestamptz,
  reject_reason      text,
  uploaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE verification_checks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  driver_id     uuid NOT NULL REFERENCES driver_profiles(user_id) ON DELETE CASCADE,
  check_type    check_type NOT NULL,
  provider      text,                        -- third-party vendor or 'manual'
  provider_ref  text,
  status        verification_status NOT NULL DEFAULT 'pending',
  result_json   jsonb,
  started_at    timestamptz NOT NULL DEFAULT now(),
  completed_at  timestamptz
);

CREATE TABLE driver_status_history (
  id          bigserial PRIMARY KEY,
  driver_id   uuid NOT NULL REFERENCES driver_profiles(user_id) ON DELETE CASCADE,
  old_status  verification_status,
  new_status  verification_status NOT NULL,
  changed_by  uuid REFERENCES users(id),
  note        text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE driver_sessions (               -- one row per online shift
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  driver_id   uuid NOT NULL REFERENCES driver_profiles(user_id) ON DELETE CASCADE,
  vehicle_id  uuid,
  went_online timestamptz NOT NULL DEFAULT now(),
  went_offline timestamptz
);

-- ---------- 3. VEHICLES ----------
CREATE TABLE vehicle_types (
  id            smallserial PRIMARY KEY,
  code          text UNIQUE NOT NULL,        -- economy, comfort, xl, bike
  display_name  text NOT NULL,
  seats         smallint NOT NULL,
  base_fare     numeric(10,2) NOT NULL DEFAULT 0,
  per_km        numeric(10,2) NOT NULL DEFAULT 0,
  per_minute    numeric(10,2) NOT NULL DEFAULT 0,
  min_fare      numeric(10,2) NOT NULL DEFAULT 0,
  active        boolean NOT NULL DEFAULT true
);

CREATE TABLE vehicles (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id         uuid NOT NULL REFERENCES driver_profiles(user_id) ON DELETE CASCADE,
  vehicle_type_id  smallint NOT NULL REFERENCES vehicle_types(id),
  plate_number     text UNIQUE NOT NULL,
  make             text NOT NULL,
  model            text NOT NULL,
  year             smallint,
  color            text,
  verification_status verification_status NOT NULL DEFAULT 'pending',
  insurance_expires date,
  inspection_expires date,
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE driver_profiles
  ADD CONSTRAINT fk_driver_current_vehicle
  FOREIGN KEY (current_vehicle_id) REFERENCES vehicles(id);

-- ---------- 4. SERVICE AREAS AND NAVIGATION DATA ----------
CREATE TABLE service_areas (                 -- geofence where the app operates
  id        serial PRIMARY KEY,
  name      text NOT NULL,
  boundary  geography(MultiPolygon,4326) NOT NULL,
  timezone  text NOT NULL,
  active    boolean NOT NULL DEFAULT true
);

CREATE TABLE pricing_zones (                 -- optional busy-area multipliers
  id            serial PRIMARY KEY,
  area_id       int NOT NULL REFERENCES service_areas(id),
  name          text NOT NULL,
  boundary      geography(MultiPolygon,4326) NOT NULL,
  multiplier    numeric(4,2) NOT NULL DEFAULT 1.00,
  valid_from    timestamptz,
  valid_to      timestamptz
);

CREATE TABLE pickup_points (                 -- fixed pickup spots: airports, malls
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name      text NOT NULL,
  location  geography(Point,4326) NOT NULL,
  area_id   int REFERENCES service_areas(id),
  notes     text
);

CREATE TABLE places (                        -- cached search and geocode results
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider    text NOT NULL,                 -- google, mapbox, osm
  provider_id text NOT NULL,
  name        text,
  address     text,
  location    geography(Point,4326) NOT NULL,
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_id)
);

CREATE TABLE route_cache (                   -- avoid repeat routing calls
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  origin_cell    text NOT NULL,              -- e.g. geohash / H3 cell
  dest_cell      text NOT NULL,
  distance_m     int  NOT NULL,
  duration_s     int  NOT NULL,
  polyline       text NOT NULL,              -- encoded route geometry
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (origin_cell, dest_cell)
);

-- Optional road graph for pgRouting (usually loaded from OpenStreetMap with osm2pgrouting).
-- Many teams skip this and call a routing engine (OSRM, Valhalla, GraphHopper) instead.
CREATE TABLE road_edges (
  id        bigserial PRIMARY KEY,
  source    bigint,
  target    bigint,
  cost_s    double precision,                -- travel time forward
  reverse_cost_s double precision,           -- travel time backward
  length_m  double precision,
  one_way   boolean,
  road_class text,
  geom      geometry(LineString,4326)
);

-- ---------- 5. RIDES AND MATCHING ----------
CREATE TABLE rides (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id           uuid NOT NULL REFERENCES users(id),
  driver_id          uuid REFERENCES users(id),
  vehicle_id         uuid REFERENCES vehicles(id),
  vehicle_type_id    smallint NOT NULL REFERENCES vehicle_types(id),
  area_id            int REFERENCES service_areas(id),
  status             ride_status NOT NULL DEFAULT 'requested',
  pickup_location    geography(Point,4326) NOT NULL,
  pickup_address     text,
  dropoff_location   geography(Point,4326) NOT NULL,
  dropoff_address    text,
  est_distance_m     int,
  est_duration_s     int,
  est_fare           numeric(10,2),
  actual_distance_m  int,
  actual_duration_s  int,
  final_fare         numeric(10,2),          -- calculated only; no payment handling
  route_polyline     text,                   -- planned route
  rider_notes        text,
  requested_at       timestamptz NOT NULL DEFAULT now(),
  assigned_at        timestamptz,
  arrived_at         timestamptz,
  started_at         timestamptz,
  completed_at       timestamptz,
  cancelled_at       timestamptz,
  cancel_reason      text,
  verification_code  char(4),                -- rider tells driver to confirm pickup
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_rides_updated BEFORE UPDATE ON rides
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE ride_offers (                   -- each request sent to a driver
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ride_id       uuid NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  driver_id     uuid NOT NULL REFERENCES driver_profiles(user_id),
  status        offer_status NOT NULL DEFAULT 'sent',
  distance_to_pickup_m int,
  eta_to_pickup_s      int,
  sent_at       timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  responded_at  timestamptz
);

CREATE TABLE ride_stops (                    -- optional multi-stop trips
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ride_id   uuid NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  seq       smallint NOT NULL,
  location  geography(Point,4326) NOT NULL,
  address   text,
  reached_at timestamptz,
  UNIQUE (ride_id, seq)
);

CREATE TABLE ride_events (                   -- audit trail of every status change
  id          bigserial PRIMARY KEY,
  ride_id     uuid NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  event_type  text NOT NULL,
  actor_id    uuid REFERENCES users(id),
  payload     jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------- 6. LIVE TRACKING ----------
-- Latest known position of each driver (small table, updated every few seconds).
-- In production keep this in Redis GEO and flush here periodically.
CREATE TABLE driver_locations_live (
  driver_id   uuid PRIMARY KEY REFERENCES driver_profiles(user_id) ON DELETE CASCADE,
  location    geography(Point,4326) NOT NULL,
  heading     real,
  speed_mps   real,
  accuracy_m  real,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Full breadcrumb trail, partitioned by month because it grows very fast.
CREATE TABLE trip_points (
  id          bigserial,
  ride_id     uuid NOT NULL,
  user_id     uuid NOT NULL,                 -- driver or rider who sent the point
  location    geography(Point,4326) NOT NULL,
  heading     real,
  speed_mps   real,
  accuracy_m  real,
  recorded_at timestamptz NOT NULL,
  PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);
CREATE TABLE trip_points_default PARTITION OF trip_points DEFAULT;
-- Create one partition per month, e.g.:
-- CREATE TABLE trip_points_2026_12 PARTITION OF trip_points
--   FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE TABLE trip_shares (                   -- "share my trip" links
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ride_id     uuid NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  token_hash  text NOT NULL,
  expires_at  timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geofence_events (               -- entered pickup, left service area, etc.
  id         bigserial PRIMARY KEY,
  ride_id    uuid REFERENCES rides(id) ON DELETE CASCADE,
  user_id    uuid REFERENCES users(id),
  event_type text NOT NULL,
  location   geography(Point,4326),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- 7. RATINGS AND SAFETY ----------
CREATE TABLE ratings (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ride_id     uuid NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
  from_user   uuid NOT NULL REFERENCES users(id),
  to_user     uuid NOT NULL REFERENCES users(id),
  stars       smallint NOT NULL CHECK (stars BETWEEN 1 AND 5),
  tags        text[],
  comment     text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ride_id, from_user)
);

CREATE TABLE sos_events (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ride_id      uuid REFERENCES rides(id),
  triggered_by uuid NOT NULL REFERENCES users(id),
  status       sos_status NOT NULL DEFAULT 'triggered',
  location     geography(Point,4326),
  handled_by   uuid REFERENCES users(id),
  notes        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  resolved_at  timestamptz
);

CREATE TABLE incident_reports (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ride_id     uuid REFERENCES rides(id),
  reporter_id uuid NOT NULL REFERENCES users(id),
  reported_id uuid REFERENCES users(id),
  category    text NOT NULL,
  description text,
  evidence_keys text[],
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_blocks (
  blocker_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  blocked_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (blocker_id, blocked_id)
);

-- ---------- 8. SUPPORT AND ADMIN ----------
CREATE TABLE support_tickets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id),
  ride_id     uuid REFERENCES rides(id),
  subject     text NOT NULL,
  status      ticket_status NOT NULL DEFAULT 'open',
  assigned_to uuid REFERENCES users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  closed_at   timestamptz
);

CREATE TABLE ticket_messages (
  id         bigserial PRIMARY KEY,
  ticket_id  uuid NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
  sender_id  uuid NOT NULL REFERENCES users(id),
  body       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (                     -- who did what in the admin panel
  id          bigserial PRIMARY KEY,
  actor_id    uuid REFERENCES users(id),
  action      text NOT NULL,
  entity      text NOT NULL,
  entity_id   text,
  before_json jsonb,
  after_json  jsonb,
  ip_address  inet,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_settings (
  key         text PRIMARY KEY,
  value       jsonb NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------- 9. NOTIFICATIONS ----------
CREATE TABLE notifications (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        text NOT NULL,
  title       text NOT NULL,
  body        text,
  data        jsonb,
  read_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------- 10. INDEXES ----------
CREATE INDEX idx_driver_live_geo   ON driver_locations_live USING GIST (location);
CREATE INDEX idx_driver_live_time  ON driver_locations_live (updated_at);
CREATE INDEX idx_rides_rider       ON rides (rider_id, requested_at DESC);
CREATE INDEX idx_rides_driver      ON rides (driver_id, requested_at DESC);
CREATE INDEX idx_rides_status      ON rides (status) WHERE status IN
  ('requested','matching','driver_assigned','driver_arrived','in_progress');
CREATE INDEX idx_rides_pickup_geo  ON rides USING GIST (pickup_location);
CREATE INDEX idx_offers_ride       ON ride_offers (ride_id);
CREATE INDEX idx_offers_driver     ON ride_offers (driver_id, status);
CREATE INDEX idx_offers_expiry     ON ride_offers (expires_at) WHERE status = 'sent';
CREATE INDEX idx_trip_points_ride  ON trip_points (ride_id, recorded_at);
CREATE INDEX idx_trip_points_geo   ON trip_points USING GIST (location);
CREATE UNIQUE INDEX idx_trip_shares_token_hash ON trip_shares (token_hash);
CREATE INDEX idx_service_areas_geo ON service_areas USING GIST (boundary);
CREATE INDEX idx_pricing_zone_geo  ON pricing_zones USING GIST (boundary);
CREATE INDEX idx_pickup_points_geo ON pickup_points USING GIST (location);
CREATE INDEX idx_places_geo        ON places USING GIST (location);
CREATE INDEX idx_saved_places_user ON saved_places (user_id);
CREATE INDEX idx_docs_driver       ON driver_documents (driver_id, doc_type);
CREATE INDEX idx_docs_expiry       ON driver_documents (expires_at);
CREATE INDEX idx_checks_driver     ON verification_checks (driver_id);
CREATE INDEX idx_vehicles_owner    ON vehicles (owner_id);
CREATE INDEX idx_ratings_to        ON ratings (to_user);
CREATE INDEX idx_sos_open          ON sos_events (status) WHERE status <> 'resolved';
CREATE INDEX idx_notifications_user ON notifications (user_id, created_at DESC);
CREATE INDEX idx_road_edges_geo    ON road_edges USING GIST (geom);

-- ---------- EXAMPLE QUERY: FIND THE 10 NEAREST ONLINE DRIVERS ----------
-- SELECT d.driver_id,
--        ST_Distance(d.location, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography) AS meters
-- FROM driver_locations_live d
-- JOIN driver_profiles p ON p.user_id = d.driver_id
-- WHERE p.availability = 'online'
--   AND p.verification_status = 'approved'
--   AND d.updated_at > now() - interval '30 seconds'
--   AND ST_DWithin(d.location, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography, 5000)
-- ORDER BY meters
-- LIMIT 10;

RESET search_path;
