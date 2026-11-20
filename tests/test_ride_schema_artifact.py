import re
import unittest
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'migrations' / '001_ride_hailing_schema.sql'
EXPECTED_TABLES = {
    'users', 'otp_codes', 'devices', 'sessions', 'rider_profiles',
    'emergency_contacts', 'saved_places', 'driver_profiles', 'driver_documents',
    'verification_checks', 'driver_status_history', 'driver_sessions',
    'vehicle_types', 'vehicles', 'service_areas', 'pricing_zones',
    'pickup_points', 'places', 'route_cache', 'road_edges', 'rides',
    'ride_offers', 'ride_stops', 'ride_events', 'driver_locations_live',
    'trip_points', 'trip_points_default', 'trip_shares', 'geofence_events',
    'ratings', 'sos_events', 'incident_reports', 'user_blocks',
    'support_tickets', 'ticket_messages', 'audit_log', 'app_settings',
    'notifications'
}


class RideSchemaArtifactTests(unittest.TestCase):
    def test_migration_contains_every_attached_table_and_postgis_setup(self):
        schema = SCHEMA_PATH.read_text(encoding='utf-8')
        table_names = set(re.findall(
            r'^\s*CREATE TABLE\s+([a-z_][a-z0-9_]*)\b',
            schema,
            flags=re.IGNORECASE | re.MULTILINE
        ))

        self.assertEqual(table_names, EXPECTED_TABLES)
        self.assertIn('CREATE EXTENSION IF NOT EXISTS postgis;', schema)
        self.assertIn('CREATE EXTENSION IF NOT EXISTS pgcrypto;', schema)
        self.assertIn('CREATE EXTENSION IF NOT EXISTS citext;', schema)
        self.assertIn('SET search_path TO ride_hailing, public;', schema)
        self.assertIn('CREATE INDEX idx_offers_expiry', schema)
        self.assertIn('CREATE UNIQUE INDEX idx_trip_shares_token_hash', schema)
        self.assertTrue(schema.rstrip().endswith('RESET search_path;'))


if __name__ == '__main__':
    unittest.main()
