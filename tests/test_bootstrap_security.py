import os
import unittest
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import SuperAdmin, app, db, init_db


class SuperAdminBootstrapTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        with app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_does_not_create_a_default_super_admin(self):
        with app.app_context():
            init_db()
            self.assertIsNone(SuperAdmin.query.first())

    def test_bootstraps_only_from_explicit_environment_password(self):
        with patch.dict(os.environ, {'SUPERADMIN_INITIAL_PASSWORD': 'test-only-password-123'}):
            with app.app_context():
                init_db()
                admin = SuperAdmin.query.filter_by(username='superadmin').one()
                self.assertTrue(admin.check_password('test-only-password-123'))

    def test_rotates_existing_super_admin_from_environment_without_logging_password(self):
        with app.app_context():
            admin = SuperAdmin(username='superadmin')
            admin.set_password('old-password-for-test')
            db.session.add(admin)
            db.session.commit()

        with patch.dict(os.environ, {'SUPERADMIN_RESET_PASSWORD': 'new-test-password-456'}):
            with app.app_context():
                init_db()
                admin = SuperAdmin.query.filter_by(username='superadmin').one()
                self.assertTrue(admin.check_password('new-test-password-456'))
                self.assertFalse(admin.check_password('old-password-for-test'))


if __name__ == '__main__':
    unittest.main()
