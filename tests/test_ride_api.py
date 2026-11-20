import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import app, db


class RideApiTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def test_ride_pages_render_login_and_role_portals(self):
        self.assertEqual(self.client.get('/rides').status_code, 200)

        self.set_session(ride_user_id='user-id', ride_role='rider')
        rider = self.client.get('/rides')
        self.assertEqual(rider.status_code, 200)
        self.assertIn(b'Request a ride', rider.data)

        self.set_session(ride_user_id='driver-id', ride_role='driver')
        driver = self.client.get('/rides/driver')
        self.assertEqual(driver.status_code, 200)
        self.assertIn(b'Driver centre', driver.data)

        self.set_session(ride_user_id='admin-id', ride_role='admin')
        admin = self.client.get('/rides/admin')
        self.assertEqual(admin.status_code, 200)
        self.assertIn(b'Ride operations', admin.data)

        self.set_session(super_id=1)
        setup = self.client.get('/rides/setup')
        self.assertEqual(setup.status_code, 200)
        self.assertIn(b'Create ride administrator', setup.data)

    def test_ride_database_api_explicitly_requires_postgis(self):
        response = self.client.get('/api/rides/vehicle-types')
        self.assertEqual(response.status_code, 503)
        self.assertIn('PostGIS', response.json['error'])


if __name__ == '__main__':
    unittest.main()
