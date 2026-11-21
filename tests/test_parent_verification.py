import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import AuditLog, Parent, School, app, db


class ParentPhoneVerificationTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Verify School', code='VER', status='active')
            other = School(name='Other School', code='OTH', status='active')
            db.session.add_all([school, other])
            db.session.flush()
            mine = Parent(school_id=school.id, name='Mine Parent',
                          phone='0711000001', password_hash='x')
            theirs = Parent(school_id=other.id, name='Other Parent',
                            phone='0711000002', password_hash='x')
            db.session.add_all([mine, theirs])
            db.session.commit()
            self.school_id = school.id
            self.mine_id = mine.id
            self.theirs_id = theirs.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def as_admin(self):
        self.set_session(school_admin_id=1, school_id=self.school_id,
                         school_name='Verify School')

    def verify(self, pid, verified):
        return self.client.post(f'/api/admin/parent/{pid}/verify-phone',
                                json={'verified': verified})

    def test_requires_a_school_admin_session(self):
        self.assertEqual(self.verify(self.mine_id, True).status_code, 403)
        self.set_session(teacher_id=1, school_id=self.school_id)
        self.assertEqual(self.verify(self.mine_id, True).status_code, 403)
        self.set_session(parent_id=self.mine_id, school_id=self.school_id)
        self.assertEqual(self.verify(self.mine_id, True).status_code, 403)

    def listed_parent(self):
        parents = self.client.get('/api/admin/parents').json
        return next(p for p in parents if p['id'] == self.mine_id)

    def test_admin_can_verify_and_unverify_a_parent(self):
        self.as_admin()
        self.assertFalse(self.listed_parent()['phone_verified'])

        self.assertEqual(self.verify(self.mine_id, True).status_code, 200)
        self.assertTrue(self.listed_parent()['phone_verified'])
        with app.app_context():
            self.assertTrue(db.session.get(Parent, self.mine_id).phone_verified)
            logged = AuditLog.query.filter(
                AuditLog.action.like('Verified parent phone%')).count()
            self.assertEqual(logged, 1)

        self.assertEqual(self.verify(self.mine_id, False).status_code, 200)
        with app.app_context():
            self.assertFalse(db.session.get(Parent, self.mine_id).phone_verified)
            logged = AuditLog.query.filter(
                AuditLog.action.like('Removed parent phone verification%')).count()
            self.assertEqual(logged, 1)

    def test_repeated_verification_is_idempotent(self):
        self.as_admin()
        self.assertEqual(self.verify(self.mine_id, True).status_code, 200)
        self.assertEqual(self.verify(self.mine_id, True).status_code, 200)
        with app.app_context():
            logged = AuditLog.query.filter(
                AuditLog.action.like('Verified parent phone%')).count()
            self.assertEqual(logged, 1)

    def test_cannot_verify_a_parent_from_another_school(self):
        self.as_admin()
        self.assertEqual(self.verify(self.theirs_id, True).status_code, 404)
        with app.app_context():
            self.assertFalse(bool(db.session.get(Parent, self.theirs_id).phone_verified))

    def test_verified_flag_must_be_a_boolean(self):
        self.as_admin()
        self.assertEqual(self.verify(self.mine_id, 'yes').status_code, 400)
        with app.app_context():
            self.assertFalse(bool(db.session.get(Parent, self.mine_id).phone_verified))


if __name__ == '__main__':
    unittest.main()
