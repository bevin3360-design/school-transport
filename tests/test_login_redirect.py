import os
import unittest
from datetime import date, timedelta

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Driver, Parent, School, SchoolAdmin, Teacher, app, db


class LoginRedirectTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def build_school(self, trial_end=None, code='LGR'):
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Redirect School', code=code, status='trial',
                            trial_end=trial_end or date.today() + timedelta(days=10))
            db.session.add(school)
            db.session.flush()
            admin = SchoolAdmin(school_id=school.id, username='lgr-admin',
                                role='coordinator')
            admin.set_password('CorrectPass1')
            driver = Driver(school_id=school.id, name='Lgr Driver',
                            phone='0700123456')
            driver.set_password('CorrectPass1')
            parent = Parent(school_id=school.id, name='Lgr Parent',
                            phone='0700654321', password_hash='x')
            parent.set_password('CorrectPass1')
            teacher = Teacher(school_id=school.id, name='Lgr Teacher',
                              teaching_code='TC1', passcode='pass9',
                              authorised=True, active=True)
            db.session.add_all([admin, driver, parent, teacher])
            db.session.commit()
            return school.id

    def ids(self, school_id):
        with app.app_context():
            return {
                'admin': SchoolAdmin.query.filter_by(school_id=school_id).first().id,
                'driver': Driver.query.filter_by(school_id=school_id).first().id,
                'parent': Parent.query.filter_by(school_id=school_id).first().id,
                'teacher': Teacher.query.filter_by(school_id=school_id).first().id,
            }

    def sign_in_as(self, key, school_id, ident):
        with self.client.session_transaction() as session:
            session['school_id'] = school_id
            session[key] = ident

    def test_anonymous_login_serves_the_film(self):
        self.build_school()
        resp = self.client.get('/login')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'intro-video', resp.data)
        self.assertIn(b'promo-30s.mp4', resp.data)

    def test_signed_in_roles_skip_film_to_dashboard(self):
        school_id = self.build_school()
        ids = self.ids(school_id)
        for role, key, path in (('admin', 'school_admin_id', '/admin'),
                                ('driver', 'driver_id', '/driver'),
                                ('parent', 'parent_id', '/parent'),
                                ('teacher', 'teacher_id', '/teacher')):
            self.sign_in_as(key, school_id, ids[role])
            resp = self.client.get('/login')
            self.assertEqual(resp.status_code, 302, role)
            self.assertEqual(resp.headers['Location'], path, role)
        with self.client.session_transaction() as session:
            session.clear()
            session['super_id'] = 1
        resp = self.client.get('/login')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/super')

    def test_lapsed_sessions_stay_on_login_without_loop(self):
        school_id = self.build_school(trial_end=date.today() - timedelta(days=1))
        ids = self.ids(school_id)
        for role, key in (('driver', 'driver_id'), ('admin', 'school_admin_id')):
            self.sign_in_as(key, school_id, ids[role])
            resp = self.client.get('/login')
            self.assertEqual(resp.status_code, 200, role)
            self.assertIn(b'intro-video', resp.data)
        self.sign_in_as('driver_id', school_id, ids['driver'])
        blocked = self.client.get('/driver')
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked.headers['Location'], '/login')
        self.assertEqual(self.client.get('/login').status_code, 200)


if __name__ == '__main__':
    unittest.main()