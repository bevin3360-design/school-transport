import os
import unittest
from datetime import date

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import (
    Payment, Route, School, SchoolAdmin, Teacher, app, db,
)


class SchoolArchiveTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Archive Test School', code='ARCH', status='active',
                            subscription_end=date.today())
            db.session.add(school)
            db.session.flush()
            db.session.add(Teacher(school_id=school.id, name='Teacher',
                                   teaching_code='T01', passcode='p1',
                                   active=True, authorised=True))
            db.session.add(Route(school_id=school.id, name='Route A'))
            admin = SchoolAdmin(school_id=school.id, username='archive-admin',
                                role='coordinator')
            admin.set_password('fake-password-123')
            db.session.add(admin)
            db.session.add(Payment(school_id=school.id, mpesa_code='ARCH0001',
                                   amount=500, plan='basic', status='verified'))
            db.session.commit()
            self.school_id = school.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def test_archive_keeps_records_and_blocks_logins(self):
        self.set_session(super_id=1, super_name='operator')
        response = self.client.delete(f'/api/super/school/{self.school_id}/delete')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['archived'])
        with app.app_context():
            school = db.session.get(School, self.school_id)
            self.assertIsNotNone(school)
            self.assertEqual(school.status, 'suspended')
            self.assertEqual(Teacher.query.filter_by(school_id=self.school_id).count(), 1)
            self.assertEqual(Route.query.filter_by(school_id=self.school_id).count(), 1)
            self.assertEqual(SchoolAdmin.query.filter_by(school_id=self.school_id).count(), 1)
            self.assertEqual(Payment.query.filter_by(school_id=self.school_id).count(), 1)

        login = self.client.post('/api/admin/login', json={
            'username': 'archive-admin', 'password': 'fake-password-123'
        })
        self.assertEqual(login.status_code, 403)

    def test_activated_archive_restores_access(self):
        self.set_session(super_id=1, super_name='operator')
        self.client.delete(f'/api/super/school/{self.school_id}/delete')
        restore = self.client.post(f'/api/super/school/{self.school_id}/activate',
                                   json={'days': 10})
        self.assertEqual(restore.status_code, 200)

        login = self.client.post('/api/admin/login', json={
            'username': 'archive-admin', 'password': 'fake-password-123'
        })
        self.assertEqual(login.status_code, 200)
        with app.app_context():
            school = db.session.get(School, self.school_id)
            self.assertEqual(school.status, 'active')
            self.assertIsNotNone(school.subscription_end)

    def test_archive_requires_super_admin(self):
        response = self.client.delete(f'/api/super/school/{self.school_id}/delete')
        self.assertEqual(response.status_code, 403)
        with app.app_context():
            self.assertEqual(db.session.get(School, self.school_id).status, 'active')


if __name__ == '__main__':
    unittest.main()
