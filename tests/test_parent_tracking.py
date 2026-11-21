import os
import unittest
from datetime import datetime

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Driver, Parent, Route, School, app, db


class ParentTrackingTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.school = School(name='Tracking School', code='TRK',
                                 status='active', morning_active=False,
                                 evening_active=False)
            db.session.add(self.school)
            db.session.flush()
            self.route = Route(school_id=self.school.id, name='Morning Route',
                               is_morning=True, active=True)
            db.session.add(self.route)
            db.session.flush()
            driver = Driver(school_id=self.school.id, name='Driver',
                            phone='0700000001', password_hash='x',
                            active=True, assigned_route_id=self.route.id,
                            is_tracking=True, current_latitude=-1.2,
                            current_longitude=36.8,
                            last_location_update=datetime.utcnow())
            parent = Parent(school_id=self.school.id, name='Parent',
                            phone='0700000002', password_hash='x',
                            assigned_route_id=self.route.id)
            db.session.add_all([driver, parent])
            db.session.commit()
            self.school_id = self.school.id
            self.route_id = self.route.id
            self.parent_id = parent.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def get_tracking(self):
        return self.client.get('/api/parent/track-bus')

    def test_location_is_hidden_when_the_shift_is_not_active(self):
        self.set_session(parent_id=self.parent_id)
        self.assertEqual(self.get_tracking().status_code, 200)
        self.assertFalse(self.get_tracking().json['tracking'])
        self.assertNotIn('latitude', self.get_tracking().json)

    def test_location_is_visible_during_an_active_shift(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            db.session.commit()
        data = self.get_tracking().json
        self.assertTrue(data['shift_active'])
        self.assertTrue(data['tracking'])
        self.assertEqual(data['latitude'], -1.2)
        self.assertEqual(data['longitude'], 36.8)

    def test_evening_shift_does_not_unlock_a_morning_route(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            db.session.get(School, self.school_id).evening_active = True
            db.session.commit()
        self.assertFalse(self.get_tracking().json['tracking'])

    def test_inactive_route_hides_location(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            school = db.session.get(School, self.school_id)
            school.morning_active = True
            db.session.get(Route, self.route_id).active = False
            db.session.commit()
        self.assertFalse(self.get_tracking().json['tracking'])


if __name__ == '__main__':
    unittest.main()
