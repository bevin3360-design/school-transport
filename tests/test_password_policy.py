import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Parent, School, SchoolAdmin, app, db


class PasswordPolicyTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Policy School', code='POLS', status='trial')
            db.session.add(school)
            db.session.flush()
            admin = SchoolAdmin(school_id=school.id, username='policy-admin',
                                role='coordinator')
            admin.set_password('existing-pass-123')
            db.session.add(admin)
            db.session.commit()
            self.school_id = school.id
            self.admin_id = admin.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def parent_payload(self, password):
        return {
            'school_code': 'POLS',
            'name': 'Test Parent',
            'phone': '0700111222',
            'password': password,
        }

    def test_parent_registration_rejects_weak_passwords(self):
        for weak in ('short1', 'alllettersonly', '12345678', '0700111222'):
            response = self.client.post('/api/parent/register',
                                        json=self.parent_payload(weak))
            self.assertEqual(response.status_code, 400, weak)
        with app.app_context():
            self.assertEqual(Parent.query.count(), 0)

    def test_parent_registration_accepts_a_strong_password(self):
        response = self.client.post('/api/parent/register',
                                    json=self.parent_payload('Strong-pass1'))
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            parent = Parent.query.one()
            self.assertTrue(parent.check_password('Strong-pass1'))

    def test_school_registration_rejects_weak_passwords(self):
        response = self.client.post('/api/register', json={
            'name': 'New School', 'code': 'NEWS',
            'admin_username': 'new-admin', 'admin_password': 'weak',
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertIsNone(School.query.filter_by(code='NEWS').first())

    def test_super_password_reset_rejects_weak_password(self):
        self.set_session(super_id=1, super_name='operator')
        response = self.client.post(
            f'/api/super/school/{self.school_id}/reset-password',
            json={'password': 'password'})
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            admin = db.session.get(SchoolAdmin, self.admin_id)
            self.assertTrue(admin.check_password('existing-pass-123'))


if __name__ == '__main__':
    unittest.main()
