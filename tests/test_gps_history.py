import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, inspect, text

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import (
    Driver, LocationHistory, School, app, cleanup_location_history, db,
    migrate_location_history_schema,
)


class LocationHistoryMigrationTests(unittest.TestCase):
    def test_migration_is_repeatable_on_a_copy_and_preserves_existing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = os.path.join(directory, 'source.sqlite')
            copy_path = os.path.join(directory, 'migration-copy.sqlite')
            source_engine = create_engine(f'sqlite:///{source_path}')
            with source_engine.begin() as connection:
                connection.execute(text(
                    'CREATE TABLE location_history ('
                    'id INTEGER PRIMARY KEY, driver_id INTEGER NOT NULL, '
                    'latitude FLOAT NOT NULL, longitude FLOAT NOT NULL, '
                    'timestamp DATETIME NOT NULL, speed FLOAT)'
                ))
                connection.execute(text(
                    "INSERT INTO location_history "
                    "(id, driver_id, latitude, longitude, timestamp, speed) "
                    "VALUES (1, 7, -1.2, 36.8, '2026-01-01 10:00:00', 24.0)"
                ))
            source_engine.dispose()
            shutil.copyfile(source_path, copy_path)

            copy_engine = create_engine(f'sqlite:///{copy_path}')
            try:
                migrate_location_history_schema(copy_engine)
                migrate_location_history_schema(copy_engine)

                columns = {
                    column['name']: column
                    for column in inspect(copy_engine).get_columns('location_history')
                }
                for name in ('device_time', 'accuracy', 'vehicle'):
                    self.assertIn(name, columns)
                    self.assertTrue(columns[name]['nullable'])
                indexes = inspect(copy_engine).get_indexes('location_history')
                self.assertIn(
                    'ix_location_history_driver_timestamp',
                    [index['name'] for index in indexes],
                )
                with copy_engine.connect() as connection:
                    row = connection.execute(text(
                        'SELECT driver_id, latitude, longitude, speed, '
                        'device_time, accuracy, vehicle FROM location_history '
                        'WHERE id = 1'
                    )).mappings().one()
                self.assertEqual(row['driver_id'], 7)
                self.assertEqual(row['latitude'], -1.2)
                self.assertIsNone(row['device_time'])
                self.assertIsNone(row['accuracy'])
                self.assertIsNone(row['vehicle'])

                source_engine = create_engine(f'sqlite:///{source_path}')
                self.assertNotIn(
                    'device_time',
                    [column['name'] for column in inspect(source_engine).get_columns(
                        'location_history'
                    )],
                )
                source_engine.dispose()
            finally:
                copy_engine.dispose()


class LocationHistoryApiAndRetentionTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            school = School(name='History Test School', code='HIST', status='active')
            other_school = School(name='Other History School', code='OHIS', status='active')
            db.session.add_all([school, other_school])
            db.session.flush()
            driver = Driver(
                school_id=school.id, name='Test Driver', phone='0700000010',
                password_hash='fake-password',
            )
            other_driver = Driver(
                school_id=other_school.id, name='Other Driver', phone='0700000011',
                password_hash='fake-password',
            )
            db.session.add_all([driver, other_driver])
            db.session.flush()
            history = LocationHistory(
                driver_id=driver.id, latitude=0.0, longitude=0.0,
                timestamp=datetime(2026, 1, 1, 12, 0),
                device_time=datetime(2026, 1, 1, 11, 59),
                accuracy=4.5, vehicle='Bus-7',
            )
            db.session.add(history)
            db.session.commit()
            self.school_id = school.id
            self.driver_id = driver.id
            self.other_driver_id = other_driver.id

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def test_history_is_limited_to_admins_and_school(self):
        endpoint = f'/api/admin/drivers/{self.driver_id}/location-history'
        self.set_session(teacher_id=1, school_id=self.school_id)
        self.assertEqual(self.client.get(endpoint).status_code, 403)
        self.set_session(parent_id=1, school_id=self.school_id)
        self.assertEqual(self.client.get(endpoint).status_code, 403)

        self.set_session(school_admin_id=1, school_id=self.school_id)
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json[0]['device_time'], '2026-01-01T11:59:00')
        self.assertEqual(response.json[0]['accuracy'], 4.5)
        self.assertEqual(response.json[0]['vehicle'], 'Bus-7')
        self.assertEqual(
            self.client.get(
                f'/api/admin/drivers/{self.other_driver_id}/location-history'
            ).status_code,
            404,
        )

    def test_retention_cleanup_can_be_repeated_without_extra_deletions(self):
        previous_enabled = app.config['GPS_HISTORY_CLEANUP_ENABLED']
        app.config['GPS_HISTORY_CLEANUP_ENABLED'] = True
        now = datetime(2026, 6, 1, 12, 0)
        try:
            with app.app_context():
                driver = db.session.get(Driver, self.driver_id)
                db.session.add_all([
                    LocationHistory(
                        driver_id=driver.id, latitude=1, longitude=1,
                        timestamp=now - timedelta(days=100),
                    ),
                    LocationHistory(
                        driver_id=driver.id, latitude=2, longitude=2,
                        timestamp=now - timedelta(days=10),
                    ),
                ])
                db.session.commit()
                self.assertEqual(
                    cleanup_location_history(retention_days=90, now=now), 2
                )
                self.assertEqual(
                    cleanup_location_history(retention_days=90, now=now), 0
                )
                remaining = LocationHistory.query.all()
                self.assertEqual(len(remaining), 1)
                self.assertEqual(remaining[0].latitude, 2)
        finally:
            app.config['GPS_HISTORY_CLEANUP_ENABLED'] = previous_enabled

    def test_cleanup_is_disabled_by_default(self):
        previous_enabled = app.config['GPS_HISTORY_CLEANUP_ENABLED']
        app.config['GPS_HISTORY_CLEANUP_ENABLED'] = False
        try:
            with app.app_context():
                with self.assertRaises(RuntimeError):
                    cleanup_location_history()
        finally:
            app.config['GPS_HISTORY_CLEANUP_ENABLED'] = previous_enabled


if __name__ == '__main__':
    unittest.main()
