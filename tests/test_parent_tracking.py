import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Driver, LocationHistory, Parent, Route, School, app, db
import navigation_wsgi  # Register the shared vehicle-locations endpoint.


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
                            last_location_update=utc_now())
            parent = Parent(school_id=self.school.id, name='Parent',
                            phone='0700000002', password_hash='x',
                            assigned_route_id=self.route.id)
            db.session.add_all([driver, parent])
            db.session.commit()
            self.school_id = self.school.id
            self.route_id = self.route.id
            self.parent_id = parent.id
            self.driver_id = driver.id

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
        self.assertEqual(data['location_state'], 'live')
        self.assertEqual(data['latitude'], -1.2)
        self.assertEqual(data['longitude'], 36.8)

    def test_location_is_marked_delayed_and_stale_as_it_ages(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            driver = db.session.query(Driver).filter_by(school_id=self.school_id).one()
            driver.last_location_update = utc_now() - timedelta(seconds=60)
            db.session.commit()
        data = self.get_tracking().json
        self.assertEqual(data['location_state'], 'delayed')
        self.assertTrue(data['tracking'])

        with app.app_context():
            driver = db.session.query(Driver).filter_by(school_id=self.school_id).one()
            driver.last_location_update = utc_now() - timedelta(seconds=180)
            db.session.commit()
        data = self.get_tracking().json
        self.assertEqual(data['location_state'], 'stale')
        self.assertFalse(data['tracking'])
        self.assertNotIn('latitude', data)
        self.assertNotIn('longitude', data)

    def test_expired_location_is_hidden_even_when_driver_still_shares(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            driver = db.session.query(Driver).filter_by(school_id=self.school_id).one()
            driver.last_location_update = utc_now() - timedelta(seconds=301)
            db.session.commit()
        data = self.get_tracking().json
        self.assertEqual(data['location_state'], 'unavailable')
        self.assertFalse(data['tracking'])
        self.assertNotIn('latitude', data)
        self.assertNotIn('longitude', data)

    def test_queued_old_device_fix_is_not_marked_live_when_received(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            driver = db.session.get(Driver, self.driver_id)
            driver.last_location_update = utc_now()
            db.session.add(LocationHistory(
                driver_id=driver.id,
                latitude=driver.current_latitude,
                longitude=driver.current_longitude,
                timestamp=utc_now(),
                device_time=utc_now() - timedelta(seconds=301),
            ))
            db.session.commit()
        data = self.get_tracking().json
        self.assertEqual(data['location_state'], 'unavailable')
        self.assertFalse(data['tracking'])
        self.assertNotIn('latitude', data)

    def test_location_is_unavailable_when_driver_stops_tracking(self):
        self.set_session(parent_id=self.parent_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            driver = db.session.query(Driver).filter_by(school_id=self.school_id).one()
            driver.is_tracking = False
            db.session.commit()
        data = self.get_tracking().json
        self.assertEqual(data['location_state'], 'unavailable')
        self.assertFalse(data['tracking'])
        self.assertNotIn('latitude', data)

    def test_freshness_setting_can_restore_legacy_tracking_state(self):
        self.set_session(parent_id=self.parent_id, school_id=self.school_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            driver = db.session.get(Driver, self.driver_id)
            driver.last_location_update = utc_now() - timedelta(seconds=301)
            db.session.commit()
        freshness_enabled = app.config['GPS_FRESHNESS_ENABLED']
        try:
            app.config['GPS_FRESHNESS_ENABLED'] = False
            data = self.get_tracking().json
            shared_map_vehicle = self.client.get('/api/vehicle/locations').json['vehicles'][0]
        finally:
            app.config['GPS_FRESHNESS_ENABLED'] = freshness_enabled
        self.assertTrue(data['tracking'])
        self.assertEqual(data['location_state'], 'live')
        self.assertFalse(data['freshness_enabled'])
        self.assertNotIn('location_state', shared_map_vehicle)
        self.assertTrue(shared_map_vehicle['is_tracking'])

    def test_stopping_tracking_clears_current_location_and_timestamp(self):
        self.set_session(
            driver_id=self.driver_id,
            school_id=self.school_id,
            driver_name='Driver',
        )
        response = self.client.post('/api/driver/stop-tracking')
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            self.assertFalse(driver.is_tracking)
            self.assertIsNone(driver.current_latitude)
            self.assertIsNone(driver.current_longitude)
            self.assertIsNone(driver.last_location_update)

    def test_shared_map_only_shows_recent_parent_route_locations(self):
        self.set_session(parent_id=self.parent_id, school_id=self.school_id)
        with app.app_context():
            db.session.get(School, self.school_id).morning_active = True
            db.session.commit()

        fresh = self.client.get('/api/vehicle/locations').json['vehicles'][0]
        self.assertEqual(fresh['location_state'], 'live')
        self.assertTrue(fresh['is_tracking'])
        self.assertEqual(fresh['latitude'], -1.2)

        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            driver.last_location_update = utc_now() - timedelta(seconds=60)
            db.session.commit()
        delayed = self.client.get('/api/vehicle/locations').json['vehicles'][0]
        self.assertEqual(delayed['location_state'], 'delayed')
        self.assertTrue(delayed['is_tracking'])
        self.assertEqual(delayed['latitude'], -1.2)

        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            driver.last_location_update = utc_now() - timedelta(seconds=180)
            db.session.commit()
        stale = self.client.get('/api/vehicle/locations').json['vehicles'][0]
        self.assertEqual(stale['location_state'], 'stale')
        self.assertFalse(stale['is_tracking'])
        self.assertNotIn('latitude', stale)
        self.assertNotIn('longitude', stale)

        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            driver.last_location_update = utc_now()
            driver.is_tracking = False
            db.session.commit()
        stopped = self.client.get('/api/vehicle/locations').json['vehicles'][0]
        self.assertEqual(stopped['location_state'], 'unavailable')
        self.assertFalse(stopped['is_tracking'])
        self.assertNotIn('latitude', stopped)

        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            driver.is_tracking = True
            db.session.get(School, self.school_id).morning_active = False
            db.session.commit()
        inactive_shift = self.client.get('/api/vehicle/locations').json['vehicles'][0]
        self.assertEqual(inactive_shift['location_state'], 'unavailable')
        self.assertNotIn('latitude', inactive_shift)

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
