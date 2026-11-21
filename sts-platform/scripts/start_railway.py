import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
POSTGRES_PREFIXES = (
    'postgres://',
    'postgresql://',
    'postgresql+psycopg://',
)


def main():
    os.chdir(BASE_DIR)

    database_url = os.environ.get('DATABASE_URL', '').strip()
    if database_url.startswith(POSTGRES_PREFIXES):
        print('PostgreSQL DATABASE_URL detected; applying ride-hailing schema.', flush=True)
        subprocess.run(
            [sys.executable, str(BASE_DIR / 'scripts' / 'apply_ride_schema.py')],
            check=True,
        )
    else:
        print(
            'DATABASE_URL is not PostgreSQL; skipping the ride-hailing migration. '
            'Ride APIs require PostgreSQL with PostGIS.',
            flush=True,
        )

    # Initialise exactly once here; the web workers must not repeat bootstrap.
    init_env = os.environ.copy()
    init_env['STS_SKIP_DB_INIT'] = '1'
    subprocess.run(
        [sys.executable, '-c', 'from app import init_db; init_db()'],
        check=True,
        env=init_env,
    )

    port = os.environ.get('PORT')
    if not port:
        raise SystemExit('PORT must be set by the platform before starting the web server.')

    os.environ['STS_SKIP_DB_INIT'] = '1'
    os.execvp('gunicorn', [
        'gunicorn',
        'navigation_wsgi:app',
        '--bind',
        f'0.0.0.0:{port}',
        '--workers',
        '1',
        '--timeout',
        '120',
    ])


if __name__ == '__main__':
    main()
