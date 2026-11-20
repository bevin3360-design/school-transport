import os
from pathlib import Path

import psycopg
from psycopg import ClientCursor


VERSION = '001_ride_hailing_schema'
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if not DATABASE_URL:
    raise SystemExit('DATABASE_URL must point to a PostgreSQL database to apply the ride schema.')

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
elif DATABASE_URL.startswith('postgresql+psycopg://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql+psycopg://', 'postgresql://', 1)

schema_path = Path(__file__).resolve().parents[1] / 'migrations' / f'{VERSION}.sql'
migration_sql = schema_path.read_text(encoding='utf-8')

with psycopg.connect(DATABASE_URL) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('server_version_num')::integer")
        server_version = cursor.fetchone()[0]
        if server_version < 150000:
            raise SystemExit('The ride-hailing schema requires PostgreSQL 15 or later.')

        cursor.execute("SELECT pg_advisory_lock(hashtext('ride-hailing-schema-migration'))")
        cursor.execute('CREATE SCHEMA IF NOT EXISTS ride_hailing')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ride_hailing.schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        ''')
        cursor.execute(
            'SELECT 1 FROM ride_hailing.schema_migrations WHERE version = %s',
            (VERSION,)
        )
        if cursor.fetchone():
            print(f'Ride-hailing schema {VERSION} is already applied.')
        else:
            with connection.cursor(cursor_factory=ClientCursor) as migration_cursor:
                migration_cursor.execute(migration_sql)
            cursor.execute('SELECT postgis_full_version()')
            postgis_version = cursor.fetchone()[0]
            cursor.execute(
                'INSERT INTO ride_hailing.schema_migrations (version) VALUES (%s)',
                (VERSION,)
            )
            print(f'Applied {VERSION}; {postgis_version}')
