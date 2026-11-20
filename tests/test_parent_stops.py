import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import Driver, Parent, ParentStop, PickupAlertLocation, Route, School, app, db


class ParentStopTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='Test School', code='TEST')
            db.session.add(school)
            db.session.flush()
            route = Route(school_id=school.id, name='Route A')
            db.session.add(route)
            db.session.flush()
            parent = Parent(
                school_id=school.id,
                name='Parent',
                phone='0700000000',
                password_hash='test-hash',
                child_name='Child',
                assigned_route_id=route.id
            )
            driver = Driver(
                school_id=school.id,
                name='Driver',
                phone='0700000001',
                password_hash='test-hash',
                assigned_route_id=route.id
            )
            db.session.add_all([parent, driver])
            db.session.commit()
            self.parent_id = parent.id
            self.driver_id = driver.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def test_saves_and_updates_each_stop(self):
        self.set_session(parent_id=self.parent_id)
        first = self.client.put('/api/parent/stops/pickup', json={
            'label': 'North gate',
            'latitude': -1.2,
            'longitude': 36.8
        })
        updated = self.client.put('/api/parent/stops/pickup', json={
            'label': 'Library entrance'
        })

        self.assertEqual(first.status_code, 200)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['stop']['label'], 'Library entrance')
        with app.app_context():
            self.assertEqual(ParentStop.query.filter_by(parent_id=self.parent_id).count(), 1)

    def test_rejects_invalid_coordinates_and_stop_types(self):
        self.set_session(parent_id=self.parent_id)
        bad_coordinates = self.client.put('/api/parent/stops/pickup', json={
            'label': 'North gate',
            'latitude': 95,
            'longitude': 36.8
        })
        bad_type = self.client.put('/api/parent/stops/other', json={'label': 'Gate'})

        self.assertEqual(bad_coordinates.status_code, 400)
        self.assertEqual(bad_type.status_code, 400)

    def test_alert_includes_snapshot_and_driver_directions(self):
        self.set_session(parent_id=self.parent_id)
        self.client.put('/api/parent/stops/pickup', json={
            'label': 'North gate',
            'latitude': -1.2,
            'longitude': 36.8
        })
        response = self.client.post('/api/parent/alert-driver', json={'alert_type': 'pickup'})
        self.assertEqual(response.status_code, 200)

        self.client.put('/api/parent/stops/pickup', json={'label': 'Updated gate'})
        self.set_session(driver_id=self.driver_id)
        alerts = self.client.get('/api/driver/alerts')

        self.assertEqual(alerts.status_code, 200)
        self.assertEqual(alerts.json[0]['location']['label'], 'North gate')
        self.assertEqual(alerts.json[0]['location']['latitude'], -1.2)
        with app.app_context():
            self.assertEqual(PickupAlertLocation.query.count(), 1)

    def test_alert_requires_saved_stop(self):
        self.set_session(parent_id=self.parent_id)
        response = self.client.post('/api/parent/alert-driver', json={'alert_type': 'dropoff'})
        self.assertEqual(response.status_code, 400)

    def test_parent_and_driver_dashboards_render_stop_features(self):
        self.set_session(parent_id=self.parent_id)
        parent_page = self.client.get('/parent')
        self.assertEqual(parent_page.status_code, 200)
        self.assertIn(b'Pickup &amp; Drop-off Points', parent_page.data)

        self.set_session(driver_id=self.driver_id)
        driver_page = self.client.get('/driver')
        self.assertEqual(driver_page.status_code, 200)
        self.assertIn(b'function directionsLink', driver_page.data)


if __name__ == '__main__':
    unittest.main()
