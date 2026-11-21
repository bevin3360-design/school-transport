import json
import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

import pyotp
from werkzeug.security import generate_password_hash

from app import SuperAdmin, app, clear_login_failures, db

SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
RECOVERY_CODE = 'aaaa-bbbb-cccc'


class SuperTwoFactorLoginTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            secured = SuperAdmin(
                username='dev', totp_secret=SECRET, totp_enabled=True,
                totp_recovery=json.dumps([generate_password_hash(RECOVERY_CODE)]),
            )
            secured.set_password('correct-password1')
            plain = SuperAdmin(username='fresh', totp_enabled=False)
            plain.set_password('correct-password1')
            db.session.add_all([secured, plain])
            db.session.commit()
        for username in ('dev', 'fresh'):
            clear_login_failures('super', username)

    def login(self, username='dev', password='correct-password1', code=None):
        payload = {'username': username, 'password': password}
        if code is not None:
            payload['totp_code'] = code
        return self.client.post('/api/super/login', json=payload)

    def test_login_without_code_challenges_for_second_factor(self):
        response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json['totp_required'])
        with self.client.session_transaction() as session:
            self.assertNotIn('super_id', session)

    def test_login_rejects_an_invalid_code(self):
        response = self.login(code='invalid-code')
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json['totp_required'])

    def test_login_accepts_a_current_totp_code(self):
        response = self.login(code=pyotp.TOTP(SECRET).now())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        with self.client.session_transaction() as session:
            self.assertIn('super_id', session)

    def test_recovery_code_works_once(self):
        self.assertEqual(self.login(code=RECOVERY_CODE).status_code, 200)
        second = self.login(code=RECOVERY_CODE)
        self.assertEqual(second.status_code, 401)
        self.assertTrue(second.json['totp_required'])

    def test_admin_without_2fa_logs_in_with_password_only(self):
        response = self.login(username='fresh')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])


class SuperTwoFactorEnrollmentTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            admin = SuperAdmin(username='fresh', totp_enabled=False)
            admin.set_password('correct-password1')
            db.session.add(admin)
            db.session.commit()
        clear_login_failures('super', 'fresh')
        self.assertEqual(
            self.client.post('/api/super/login', json={
                'username': 'fresh', 'password': 'correct-password1',
            }).status_code,
            200,
        )

    def test_2fa_endpoints_require_a_super_session(self):
        anonymous = app.test_client()
        self.assertEqual(anonymous.get('/api/super/2fa/status').status_code, 403)
        self.assertEqual(anonymous.post('/api/super/2fa/setup').status_code, 403)

    def test_enrollment_verifies_the_code_and_issues_recovery_codes(self):
        status = self.client.get('/api/super/2fa/status').json
        self.assertFalse(status['enabled'])

        setup = self.client.post('/api/super/2fa/setup')
        self.assertEqual(setup.status_code, 200)
        secret = setup.json['secret']
        self.assertTrue(setup.json['otpauth_url'].startswith('otpauth://totp/'))

        wrong = self.client.post('/api/super/2fa/enable',
                                 json={'secret': secret, 'code': 'invalid-code'})
        self.assertEqual(wrong.status_code, 400)

        enabled = self.client.post('/api/super/2fa/enable', json={
            'secret': secret, 'code': pyotp.TOTP(secret).now(),
        })
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual(len(enabled.json['recovery_codes']), 10)

        status = self.client.get('/api/super/2fa/status').json
        self.assertTrue(status['enabled'])
        self.assertEqual(status['recovery_codes_remaining'], 10)

        with app.app_context():
            admin = SuperAdmin.query.filter_by(username='fresh').first()
            self.assertTrue(admin.totp_enabled)
            self.assertEqual(admin.totp_secret, secret)

    def test_disabling_requires_a_valid_code(self):
        setup = self.client.post('/api/super/2fa/setup').json
        secret = setup['secret']
        self.client.post('/api/super/2fa/enable', json={
            'secret': secret, 'code': pyotp.TOTP(secret).now(),
        })

        self.assertEqual(
            self.client.post('/api/super/2fa/disable',
                             json={'code': 'invalid-code'}).status_code,
            400,
        )
        unknown_recovery = self.client.post('/api/super/2fa/disable',
                                            json={'code': 'zzzz-yyyy-xxxx'})
        self.assertEqual(unknown_recovery.status_code, 400)

        disabled = self.client.post('/api/super/2fa/disable', json={
            'code': pyotp.TOTP(secret).now(),
        })
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(self.client.get('/api/super/2fa/status').json['enabled'])
        with app.app_context():
            admin = SuperAdmin.query.filter_by(username='fresh').first()
            self.assertFalse(admin.totp_enabled)
            self.assertIsNone(admin.totp_secret)
            self.assertIsNone(admin.totp_recovery)


if __name__ == '__main__':
    unittest.main()
