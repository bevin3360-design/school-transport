import os
import unittest
from datetime import date, timedelta

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Driver, Parent, School, SchoolAdmin, Teacher, app, db


class SubscriptionExpiryTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def build_school(self, status='trial', trial_end=None, subscription_end=None,
                     code='EXP'):
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Expiry School', code=code, status=status,
                            trial_end=trial_end, subscription_end=subscription_end)
            db.session.add(school)
            db.session.flush()
            admin = SchoolAdmin(school_id=school.id, username='exp-admin',
                                role='coordinator')
            admin.set_password('CorrectPass1')
            driver = Driver(school_id=school.id, name='Exp Driver',
                            phone='0700123456')
            driver.set_password('CorrectPass1')
            parent = Parent(school_id=school.id, name='Exp Parent',
                            phone='0700654321', password_hash='x')
            parent.set_password('CorrectPass1')
            teacher = Teacher(school_id=school.id, name='Exp Teacher',
                              teaching_code='TC1', passcode='pass9',
                              authorised=True, active=True)
            db.session.add_all([admin, driver, parent, teacher])
            db.session.commit()
            return school.id

    def login_admin(self, code='EXP'):
        return self.client.post('/api/admin/login', json={
            'username': 'exp-admin', 'password': 'CorrectPass1'})

    def test_expired_trial_admin_reaches_only_payment(self):
        self.build_school(trial_end=date.today() - timedelta(days=1))
        self.assertEqual(self.login_admin().status_code, 200)
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.get('/admin').headers['Location'], '/payment')
        self.assertEqual(self.client.get('/payment').status_code, 200)
        blocked = self.client.post('/api/routes', json={'name': 'Blocked Route'})
        self.assertEqual(blocked.status_code, 402)
        self.assertEqual(blocked.json['code'], 'subscription_expired')
        status = self.client.get('/api/payment/status')
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json['school_status'], 'expired')

    def test_lapsed_school_blocks_driver_parent_and_teacher_logins(self):
        self.build_school(status='active',
                          subscription_end=date.today() - timedelta(days=1))
        driver = self.client.post('/api/driver/login', json={
            'phone': '0700123456', 'password': 'CorrectPass1', 'school_code': 'EXP'})
        self.assertEqual(driver.status_code, 403)
        self.assertIn('subscription has ended', driver.json['message'])
        parent = self.client.post('/api/parent/login', json={
            'phone': '0700654321', 'password': 'CorrectPass1', 'school_code': 'EXP'})
        self.assertEqual(parent.status_code, 403)
        teacher = self.client.post('/api/teacher/login', json={
            'teaching_code': 'TC1', 'passcode': 'pass9', 'school_code': 'EXP'})
        self.assertEqual(teacher.status_code, 403)

    def test_open_trial_keeps_full_access(self):
        self.build_school(trial_end=date.today() + timedelta(days=10))
        self.assertEqual(self.login_admin().status_code, 200)
        created = self.client.post('/api/routes', json={'name': 'Allowed Route'})
        self.assertEqual(created.status_code, 200)
        driver = self.client.post('/api/driver/login', json={
            'phone': '0700123456', 'password': 'CorrectPass1', 'school_code': 'EXP'})
        self.assertEqual(driver.status_code, 200)

    def test_paid_plan_lasts_until_subscription_end(self):
        self.build_school(status='active',
                          subscription_end=date.today() + timedelta(days=5))
        self.assertEqual(self.login_admin().status_code, 200)
        self.assertEqual(self.client.post('/api/routes',
                                          json={'name': 'Paid Route'}).status_code, 200)

    def test_mid_session_lapse_blocks_existing_driver_session(self):
        school_id = self.build_school(trial_end=date.today() + timedelta(days=5))
        with app.app_context():
            driver = Driver.query.filter_by(school_id=school_id).first()
            driver_id = driver.id
        with self.client.session_transaction() as session:
            session['driver_id'] = driver_id
            session['school_id'] = school_id
            session['driver_name'] = 'Exp Driver'
        with app.app_context():
            school = db.session.get(School, school_id)
            school.trial_end = date.today() - timedelta(days=1)
            db.session.commit()
        blocked = self.client.post('/api/driver/start-tracking')
        self.assertEqual(blocked.status_code, 402)
        self.assertEqual(blocked.json['code'], 'subscription_expired')


if __name__ == '__main__':
    unittest.main()
