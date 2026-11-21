import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import School, app, db


class SchoolSettingsTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Settings School', code='SETS', status='active')
            db.session.add(school)
            db.session.commit()
            self.school_id = school.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def test_school_admin_receives_payment_details(self):
        self.set_session(school_admin_id=1, school_id=self.school_id)
        response = self.client.get('/api/school/settings')
        self.assertEqual(response.status_code, 200)
        self.assertIn('mpesa_number', response.json)
        self.assertIn('plans', response.json)

    def test_teacher_sees_public_link_only(self):
        self.set_session(teacher_id=1, school_id=self.school_id)
        response = self.client.get('/api/school/settings')
        self.assertEqual(response.status_code, 200)
        self.assertIn('public_link', response.json)
        self.assertNotIn('mpesa_number', response.json)
        self.assertNotIn('plans', response.json)

    def test_parent_driver_and_anonymous_are_rejected(self):
        self.assertEqual(self.client.get('/api/school/settings').status_code, 403)
        self.set_session(parent_id=1, school_id=self.school_id)
        self.assertEqual(self.client.get('/api/school/settings').status_code, 403)
        self.set_session(driver_id=1, school_id=self.school_id)
        self.assertEqual(self.client.get('/api/school/settings').status_code, 403)

    def test_public_link_must_be_http_and_is_saved(self):
        self.set_session(school_admin_id=1, school_id=self.school_id)
        rejected = self.client.put('/api/school/settings',
                                   json={'public_link': 'javascript:alert(1)'})
        self.assertEqual(rejected.status_code, 400)

        accepted = self.client.put('/api/school/settings',
                                   json={'public_link': 'https://example.test/s/SETS'})
        self.assertEqual(accepted.status_code, 200)
        with app.app_context():
            self.assertEqual(db.session.get(School, self.school_id).public_link,
                             'https://example.test/s/SETS')

    def test_teacher_cannot_change_settings(self):
        self.set_session(teacher_id=1, school_id=self.school_id)
        response = self.client.put('/api/school/settings', json={'morning_active': True})
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
