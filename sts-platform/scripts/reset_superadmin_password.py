import getpass
from importlib import import_module
import os
import sys
from pathlib import Path


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
BASE_DIR = Path(__file__).resolve().parents[1]


def main():
    os.environ['STS_SKIP_DB_INIT'] = '1'
    if not os.environ.get('DATABASE_URL') and os.environ.get('STS_ALLOW_SQLITE_RESET') != '1':
        raise SystemExit(
            'DATABASE_URL is not set; refusing to reset the local SQLite database. '
            'Set STS_ALLOW_SQLITE_RESET=1 only for a disposable local database.'
        )
    sys.path.insert(0, str(BASE_DIR))
    os.chdir(BASE_DIR)
    application = import_module('app')

    username = input('Super-admin username: ').strip()
    if not username:
        raise SystemExit('A username is required.')

    password = getpass.getpass('New password (input hidden): ')
    confirmation = getpass.getpass('Confirm new password: ')
    if password != confirmation:
        raise SystemExit('Passwords do not match.')
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise SystemExit(
            f'Password must be between {MIN_PASSWORD_LENGTH} and '
            f'{MAX_PASSWORD_LENGTH} characters.'
        )

    with application.app.app_context():
        admin = application.SuperAdmin.query.filter_by(username=username).first()
        if not admin:
            raise SystemExit('No super-admin account exists with that username.')

        admin.set_password(password)
        application.db.session.commit()

    print('Super-admin password updated. Sign in with the new password.')


if __name__ == '__main__':
    main()
