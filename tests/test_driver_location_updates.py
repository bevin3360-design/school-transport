import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Driver, LocationHistory, School, app, db


class DriverLocationUpdateTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='GPS Test School', code='GPS',
                            status='active')
            db.session.add(school)
            db.session.flush()
            driver = Driver(
                school_id=school.id,
                name='Test Driver',
                phone='0700000000',
                password_hash='not-a-real-password',
                active=True,
                is_tracking=False,
            )
            db.session.add(driver)
            db.session.commit()
            self.school_id = school.id
            self.driver_id = driver.id

    def set_driver_session(self, driver_id=None):
        with self.client.session_transaction() as session:
            session.clear()
            session.update({
                'driver_id': driver_id or self.driver_id,
                'school_id': self.school_id,
                'driver_name': 'Test Driver',
            })

    def set_tracking(self, driver_id=None, enabled=True):
        with app.app_context():
            driver = db.session.get(Driver, driver_id or self.driver_id)
            driver.is_tracking = enabled
            db.session.commit()

    def update(self, latitude, longitude):
        return self.client.post(
            '/api/driver/update-location',
            json={'latitude': latitude, 'longitude': longitude},
        )

    def test_location_update_requires_tracking(self):
        self.set_driver_session()
        response = self.update(1.0, 2.0)
        self.assertEqual(response.status_code, 409)
        with app.app_context():
            self.assertEqual(LocationHistory.query.count(), 0)

    def test_coordinate_ranges_and_zero_values(self):
        self.set_tracking(enabled=True)
        self.set_driver_session()

        response = self.update(0, 0)
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            self.assertEqual(driver.current_latitude, 0)
            self.assertEqual(driver.current_longitude, 0)
            self.assertEqual(LocationHistory.query.count(), 1)

        for latitude, longitude in (
            (90.001, 0),
            (-90.001, 0),
            (0, 180.001),
            (0, -180.001),
            ('NaN', 0),
            (0, 'Infinity'),
            (True, 1),
        ):
            with self.subTest(latitude=latitude, longitude=longitude):
                response = self.update(latitude, longitude)
                self.assertEqual(response.status_code, 400)

        with app.app_context():
            self.assertEqual(LocationHistory.query.count(), 1)

    def test_coordinate_range_endpoints_are_inclusive(self):
        self.set_tracking(enabled=True)
        self.set_driver_session()
        response = self.update(-90, 180)
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            driver = db.session.get(Driver, self.driver_id)
            self.assertEqual(driver.current_latitude, -90)
            self.assertEqual(driver.current_longitude, 180)

    def test_location_history_records_device_metadata(self):
        self.set_tracking(enabled=True)
        self.set_driver_session()
        response = self.client.post(
            '/api/driver/update-location',
            json={
                'latitude': 0,
                'longitude': 0,
                'device_time': '2026-01-02T03:04:05Z',
                'accuracy': 0,
                'vehicle': 'Test Bus',
            },
        )
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            history = LocationHistory.query.one()
            self.assertEqual(history.device_time.isoformat(), '2026-01-02T03:04:05')
            self.assertEqual(history.accuracy, 0)
            self.assertEqual(history.vehicle, 'Test Bus')

    def test_invalid_location_metadata_is_rejected(self):
        self.set_tracking(enabled=True)
        self.set_driver_session()
        for payload in (
            {'accuracy': -1},
            {'accuracy': 'NaN'},
            {'device_time': 'not-a-timestamp'},
            {'vehicle': 'x' * 121},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    '/api/driver/update-location',
                    json={'latitude': 1, 'longitude': 2, **payload},
                )
                self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(LocationHistory.query.count(), 0)

    def test_rate_limit_is_per_driver(self):
        self.set_tracking(enabled=True)
        self.set_driver_session()
        self.assertEqual(self.update(1.0, 2.0).status_code, 200)

        limited = self.update(1.1, 2.1)
        self.assertEqual(limited.status_code, 429)
        self.assertIn('Retry-After', limited.headers)

        with app.app_context():
            other_driver = Driver(
                school_id=self.school_id,
                name='Second Test Driver',
                phone='0700000001',
                password_hash='not-a-real-password',
                active=True,
                is_tracking=True,
            )
            db.session.add(other_driver)
            db.session.commit()
            other_driver_id = other_driver.id
        self.set_driver_session(other_driver_id)
        self.assertEqual(self.update(-1.0, -2.0).status_code, 200)

    def test_location_guards_can_be_disabled(self):
        self.set_driver_session()
        guards_enabled = app.config['GPS_LOCATION_UPDATE_GUARDS_ENABLED']
        try:
            app.config['GPS_LOCATION_UPDATE_GUARDS_ENABLED'] = False
            first = self.update(1.0, 2.0)
            second = self.update(1.1, 2.1)
        finally:
            app.config['GPS_LOCATION_UPDATE_GUARDS_ENABLED'] = guards_enabled
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)


if __name__ == '__main__':
    unittest.main()
