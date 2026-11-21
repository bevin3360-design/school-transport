import os
import unittest
from datetime import date

from sqlalchemy.exc import IntegrityError

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import DutyAssignment, Route, School, Teacher, app, db

WORKDAY = date(2026, 11, 23)


class RosterIntegrityTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Roster School', code='ROST', status='trial',
                            morning_active=True)
            db.session.add(school)
            db.session.flush()
            route = Route(school_id=school.id, name='Route A', is_morning=True, active=True)
            db.session.add(route)
            db.session.add(Teacher(school_id=school.id, name='Teacher',
                                   teaching_code='R01', passcode='p1',
                                   active=True, authorised=True))
            db.session.commit()
            self.school_id = school.id
            self.route_id = route.id
            self.teacher_id = Teacher.query.filter_by(school_id=school.id).one().id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def test_database_rejects_double_booking_a_teacher_on_a_shift(self):
        with app.app_context():
            for _ in range(2):
                db.session.add(DutyAssignment(
                    school_id=self.school_id, teacher_id=self.teacher_id,
                    route_id=self.route_id, duty_date=WORKDAY,
                    is_morning=True, status='assigned'))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_database_rejects_two_teachers_on_one_route_shift(self):
        with app.app_context():
            second = Teacher(school_id=self.school_id, name='Second',
                             teaching_code='R02', passcode='p2',
                             active=True, authorised=True)
            db.session.add(second)
            db.session.flush()
            db.session.add(DutyAssignment(
                school_id=self.school_id, teacher_id=self.teacher_id,
                route_id=self.route_id, duty_date=WORKDAY,
                is_morning=True, status='assigned'))
            db.session.add(DutyAssignment(
                school_id=self.school_id, teacher_id=second.id,
                route_id=self.route_id, duty_date=WORKDAY,
                is_morning=True, status='assigned'))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_generating_the_same_day_twice_does_not_duplicate_duties(self):
        self.set_session(school_admin_id=1, school_id=self.school_id)
        first = self.client.post('/api/roster/generate',
                                 json={'date': WORKDAY.isoformat()})
        second = self.client.post('/api/roster/generate',
                                  json={'date': WORKDAY.isoformat()})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        with app.app_context():
            self.assertEqual(
                DutyAssignment.query.filter_by(school_id=self.school_id,
                                               duty_date=WORKDAY).count(), 1)


if __name__ == '__main__':
    unittest.main()
