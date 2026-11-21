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

    if password.lower() == username.lower():
        raise SystemExit('Password must not match the username.')

    with application.app.app_context():
        admin = application.SuperAdmin.query.filter_by(username=username).first()
        created = False
        if not admin:
            confirm = input(
                f'No super-admin "{username}" exists. Create it with this password? '
                '[yes/NO]: '
            ).strip().lower()
            if confirm != 'yes':
                raise SystemExit('No account was changed.')
            admin = application.SuperAdmin(username=username)
            application.db.session.add(admin)
            created = True

        admin.set_password(password)
        application.db.session.commit()

    if created:
        print('Super-admin account created. Sign in with the new password.')
    else:
        print('Super-admin password updated. Sign in with the new password.')


if __name__ == '__main__':
    main()
