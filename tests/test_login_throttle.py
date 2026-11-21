import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import (
    Parent, School, SchoolAdmin, app, clear_login_failures, db,
)


class LoginThrottleTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Throttle School', code='THR', status='active')
            db.session.add(school)
            db.session.flush()
            admin = SchoolAdmin(school_id=school.id, username='throttle-admin',
                                role='coordinator')
            admin.set_password('correct-password1')
            parent = Parent(school_id=school.id, name='Throttle Parent',
                            phone='0700999888', password_hash='x')
            parent.set_password('correct-password1')
            db.session.add_all([admin, parent])
            db.session.commit()
        clear_login_failures('admin', 'throttle-admin')
        clear_login_failures('parent', 'THR:0700999888')

    def admin_login(self, password='wrong-password'):
        return self.client.post('/api/admin/login', json={
            'username': 'throttle-admin', 'password': password
        })

    def parent_login(self, password='wrong-password'):
        return self.client.post('/api/parent/login', json={
            'school_code': 'THR', 'phone': '0700999888', 'password': password
        })

    def test_admin_login_is_locked_after_repeated_failures(self):
        for _ in range(8):
            self.assertEqual(self.admin_login().status_code, 401)
        blocked = self.admin_login('correct-password1')
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Too many failed attempts', blocked.json['message'])

    def test_successful_login_resets_the_failure_counter(self):
        for _ in range(3):
            self.assertEqual(self.admin_login().status_code, 401)
        self.assertEqual(self.admin_login('correct-password1').status_code, 200)
        for _ in range(7):
            self.assertEqual(self.admin_login().status_code, 401)
        self.assertEqual(self.admin_login('correct-password1').status_code, 200)

    def test_parent_login_is_locked_after_repeated_failures(self):
        for _ in range(8):
            self.assertEqual(self.parent_login().status_code, 401)
        blocked = self.parent_login('correct-password1')
        self.assertEqual(blocked.status_code, 429)


if __name__ == '__main__':
    unittest.main()
