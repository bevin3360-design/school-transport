import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
SECRET_DIR = Path('/etc/secrets')
POSTGRES_PREFIXES = (
    'postgres://',
    'postgresql://',
    'postgresql+psycopg://',
)


def usable_url(url):
    return url.startswith(POSTGRES_PREFIXES) and '@' in url


def database_url_files():
    override = os.environ.get('DATABASE_URL_FILE')
    if override:
        yield Path(override)
    yield SECRET_DIR / 'database_url.txt'
    yield BASE_DIR / 'database_url.txt'
    yield BASE_DIR.parent / 'database_url.txt'
    if SECRET_DIR.is_dir():
        yield from sorted(SECRET_DIR.iterdir())


def resolve_database_url():
    # Dashboard env editors have mangled this URL twice, so allow a mounted
    # secret file to take over when the env value is not a complete URL.
    url = os.environ.get('DATABASE_URL', '').strip()
    if usable_url(url):
        return url
    for path in database_url_files():
        try:
            candidate = path.read_text(encoding='utf-8').strip()
        except (OSError, UnicodeDecodeError):
            continue
        if usable_url(candidate):
            print(f'Using the database URL from {path}.', flush=True)
            return candidate
    if SECRET_DIR.is_dir():
        names = sorted(path.name for path in SECRET_DIR.iterdir())
        print(f'No usable database URL found; {SECRET_DIR} holds: {names}', flush=True)
    return url


def main():
    os.chdir(BASE_DIR)

    database_url = resolve_database_url()
    os.environ['DATABASE_URL'] = database_url
    scheme = database_url.split('://', 1)[0] if '://' in database_url else '(none)'
    print(
        f'DATABASE_URL fingerprint: scheme={scheme} length={len(database_url)} '
        f'has_credentials={"@" in database_url}',
        flush=True,
    )
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
