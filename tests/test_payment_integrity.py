import os
import unittest
from datetime import date, timedelta

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Payment, School, app, db


class PaymentIntegrityTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Test School', code='TEST', status='trial')
            db.session.add(school)
            db.session.commit()
            self.school_id = school.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def submit(self, **overrides):
        payload = {
            'mpesa_code': 'SFE4ABC123',
            'amount': 500,
            'plan': 'basic',
            'phone': '0700000000',
        }
        payload.update(overrides)
        return self.client.post('/api/payment/submit', json=payload)

    def add_payment(self, status='pending', code='SFE4XYZ789'):
        with app.app_context():
            payment = Payment(
                school_id=self.school_id,
                mpesa_code=code,
                amount=500,
                plan='basic',
                phone='0700000000',
                status=status,
            )
            db.session.add(payment)
            db.session.commit()
            return payment.id

    def test_submit_accepts_a_valid_payment(self):
        self.set_session(school_admin_id=1, school_id=self.school_id)
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            payment = Payment.query.filter_by(mpesa_code='SFE4ABC123').one()
            self.assertEqual(payment.status, 'pending')
            self.assertEqual(payment.school_id, self.school_id)

    def test_submit_rejects_bad_amounts_and_plans(self):
        self.set_session(school_admin_id=1, school_id=self.school_id)
        self.assertEqual(self.submit(amount='abc').status_code, 400)
        self.assertEqual(self.submit(amount=-5).status_code, 400)
        self.assertEqual(self.submit(plan='platinum').status_code, 400)
        self.assertEqual(self.submit(plan='standard', amount=500).status_code, 400)
        with app.app_context():
            self.assertEqual(Payment.query.count(), 0)

    def test_submit_rejects_a_duplicate_mpesa_code(self):
        self.set_session(school_admin_id=1, school_id=self.school_id)
        self.assertEqual(self.submit().status_code, 200)
        duplicate = self.submit(mpesa_code='sfe4abc123')
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('already been submitted', duplicate.json['error'])
        with app.app_context():
            self.assertEqual(Payment.query.count(), 1)

    def test_second_verification_does_not_extend_subscription_again(self):
        payment_id = self.add_payment()
        self.set_session(super_id=1, super_name='operator')

        first = self.client.post(f'/api/super/payment/{payment_id}/verify')
        self.assertEqual(first.status_code, 200)
        with app.app_context():
            end_after_first = db.session.get(School, self.school_id).subscription_end
        self.assertEqual(end_after_first, date.today() + timedelta(days=30))

        second = self.client.post(f'/api/super/payment/{payment_id}/verify')
        self.assertEqual(second.status_code, 409)
        with app.app_context():
            school = db.session.get(School, self.school_id)
            self.assertEqual(school.subscription_end, end_after_first)
            self.assertEqual(school.status, 'active')

    def test_rejected_payment_cannot_be_verified(self):
        payment_id = self.add_payment(status='rejected')
        self.set_session(super_id=1, super_name='operator')
        response = self.client.post(f'/api/super/payment/{payment_id}/verify')
        self.assertEqual(response.status_code, 409)
        with app.app_context():
            self.assertIsNone(db.session.get(School, self.school_id).subscription_end)

    def test_payment_cannot_be_rejected_twice(self):
        payment_id = self.add_payment(status='verified')
        self.set_session(super_id=1, super_name='operator')
        response = self.client.post(f'/api/super/payment/{payment_id}/reject')
        self.assertEqual(response.status_code, 409)
        with app.app_context():
            self.assertEqual(db.session.get(Payment, payment_id).status, 'verified')


if __name__ == '__main__':
    unittest.main()
