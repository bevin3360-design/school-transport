import getpass
import os

os.environ['STS_SKIP_DB_INIT'] = '1'

from app import SuperAdmin, app, db


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def main():
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

    with app.app_context():
        admin = SuperAdmin.query.filter_by(username=username).first()
        if not admin:
            raise SystemExit('No super-admin account exists with that username.')

        admin.set_password(password)
        db.session.commit()

    print('Super-admin password updated.')


if __name__ == '__main__':
    main()
