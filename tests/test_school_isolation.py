import os
import unittest
from datetime import date

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import (
    app, db, AuditLog, Driver, DutyAssignment, Parent, ParentStop, Payment,
    PickupAlert, PickupAlertLocation, Route, School, Teacher,
)
import navigation_wsgi  # registers /api/vehicle/locations on the same app


class IsolationBase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()
            alpha = School(name='Alpha School', code='ALP', status='active')
            beta = School(name='Beta School', code='BET', status='active')
            db.session.add_all([alpha, beta])
            db.session.flush()
            self.a, self.b = alpha.id, beta.id

            route_a = Route(school_id=alpha.id, name='Alpha Route', description='A only')
            route_b = Route(school_id=beta.id, name='Beta Route', description='B only')
            db.session.add_all([route_a, route_b])
            db.session.flush()

            teacher_a = Teacher(school_id=alpha.id, name='Alpha Teacher',
                                teaching_code='TA1', passcode='1111',
                                authorised=True, active=True)
            teacher_a2 = Teacher(school_id=alpha.id, name='Alpha Spare',
                                 teaching_code='TA2', passcode='1212',
                                 authorised=True, active=True)
            teacher_b = Teacher(school_id=beta.id, name='Beta Teacher',
                                teaching_code='TB1', passcode='2222',
                                authorised=True, active=True)
            driver_a = Driver(school_id=alpha.id, name='Alpha Driver', phone='0710000001',
                              password_hash='x', assigned_route_id=route_a.id,
                              current_latitude=-1.1, current_longitude=36.1,
                              is_tracking=True)
            driver_b = Driver(school_id=beta.id, name='Beta Driver', phone='0710000002',
                              password_hash='x', assigned_route_id=route_b.id,
                              current_latitude=-2.2, current_longitude=37.2,
                              is_tracking=True)
            parent_a = Parent(school_id=alpha.id, name='Alpha Parent', phone='0720000001',
                              password_hash='x', assigned_route_id=route_a.id)
            parent_b = Parent(school_id=beta.id, name='Beta Parent', phone='0720000002',
                              password_hash='x', assigned_route_id=route_b.id)
            db.session.add_all([teacher_a, teacher_a2, teacher_b,
                                driver_a, driver_b, parent_a, parent_b])
            db.session.flush()

            duty_a = DutyAssignment(school_id=alpha.id, teacher_id=teacher_a.id,
                                    route_id=route_a.id, duty_date=date.today(),
                                    is_morning=True, status='assigned')
            duty_b = DutyAssignment(school_id=beta.id, teacher_id=teacher_b.id,
                                    route_id=route_b.id, duty_date=date.today(),
                                    is_morning=True, status='assigned')
            db.session.add_all([duty_a, duty_b])
            db.session.flush()

            stop_a = ParentStop(parent_id=parent_a.id, stop_type='pickup', label='Alpha gate')
            stop_b = ParentStop(parent_id=parent_b.id, stop_type='pickup', label='Beta gate')
            alert_a = PickupAlert(parent_id=parent_a.id, driver_id=driver_a.id,
                                  route_id=route_a.id, alert_type='pickup')
            alert_a.location = PickupAlertLocation(label='Alpha gate', latitude=-1.1, longitude=36.1)
            db.session.add_all([stop_a, stop_b, alert_a])
            db.session.add_all([
                Payment(school_id=alpha.id, mpesa_code='ALPHA01', amount=500, plan='basic'),
                Payment(school_id=beta.id, mpesa_code='BETA001', amount=500, plan='basic'),
                AuditLog(school_id=alpha.id, user_type='admin', user_name='Alpha Admin',
                         action='alpha-only'),
                AuditLog(school_id=beta.id, user_type='admin', user_name='Beta Admin',
                         action='beta-only'),
            ])
            db.session.commit()

            self.route = {'a': route_a.id, 'b': route_b.id}
            self.id = {
                'a': {'teacher': teacher_a.id, 'teacher2': teacher_a2.id,
                      'driver': driver_a.id, 'parent': parent_a.id,
                      'duty': duty_a.id, 'alert': alert_a.id},
                'b': {'teacher': teacher_b.id, 'driver': driver_b.id,
                      'parent': parent_b.id, 'duty': duty_b.id},
            }

    def set_session(self, **values):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(values)

    def as_admin(self, which='a'):
        school_id = self.a if which == 'a' else self.b
        name = 'Alpha School' if which == 'a' else 'Beta School'
        self.set_session(school_admin_id=which == 'a' and 1 or 2,
                         school_id=school_id, school_name=name)

    def as_teacher(self, which='a'):
        school_id = self.a if which == 'a' else self.b
        self.set_session(teacher_id=self.id[which]['teacher'], school_id=school_id,
                         teacher_name='Alpha Teacher' if which == 'a' else 'Beta Teacher',
                         school_name='Alpha School' if which == 'a' else 'Beta School')

    def as_driver(self, which='a'):
        school_id = self.a if which == 'a' else self.b
        self.set_session(driver_id=self.id[which]['driver'], school_id=school_id,
                         school_name='Alpha School' if which == 'a' else 'Beta School')

    def as_parent(self, which='a'):
        school_id = self.a if which == 'a' else self.b
        self.set_session(parent_id=self.id[which]['parent'], school_id=school_id,
                         parent_name='Alpha Parent' if which == 'a' else 'Beta Parent',
                         school_name='Alpha School' if which == 'a' else 'Beta School')


class ScopedListTests(IsolationBase):
    def test_admin_lists_only_own_school_rows(self):
        self.as_admin('a')
        self.assertEqual([d['name'] for d in self.client.get('/api/admin/drivers').json],
                         ['Alpha Driver'])
        self.assertEqual([p['name'] for p in self.client.get('/api/admin/parents').json],
                         ['Alpha Parent'])
        self.assertEqual([t['name'] for t in self.client.get('/api/teachers').json],
                         ['Alpha Teacher', 'Alpha Spare'])
        self.assertEqual([r['name'] for r in self.client.get('/api/routes').json],
                         ['Alpha Route'])
        self.assertEqual([t['teacher_name'] for t in self.client.get('/api/roster').json],
                         ['Alpha Teacher'])
        self.assertEqual([l['user_name'] for l in self.client.get('/api/logs').json],
                         ['Alpha Admin'])
        payments = self.client.get('/api/payment/status').json['payments']
        self.assertEqual([p['mpesa_code'] for p in payments], ['ALPHA01'])
        settings = self.client.get('/api/school/settings').json
        self.assertEqual(settings['code'], 'ALP')
        self.assertEqual(settings['name'], 'Alpha School')

    def test_teacher_and_parent_reads_are_scoped(self):
        self.as_teacher('a')
        self.assertEqual([r['name'] for r in self.client.get('/api/routes').json],
                         ['Alpha Route'])
        self.assertEqual([d['route_name'] for d in
                          self.client.get('/api/roster/teacher').json], ['Alpha Route'])
        self.assertEqual(self.client.get('/api/school/settings').json['code'], 'ALP')

        self.as_parent('b')
        stops = self.client.get('/api/parent/stops').json
        self.assertEqual(stops['pickup']['label'], 'Beta gate')
        self.assertEqual(self.client.get('/api/parent/track-bus').json['route_name'],
                         'Beta Route')

    def test_teacher_cannot_read_pickup_stop_from_parent_session_data(self):
        self.set_session(
            teacher_id=self.id['a']['teacher'],
            parent_id=self.id['b']['parent'],
            school_id=self.a,
            school_name='Alpha School',
        )
        response = self.client.get('/api/parent/stops')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Beta gate', response.get_data(as_text=True))

    def test_role_separation_on_admin_endpoints(self):
        for role in (self.as_teacher, self.as_driver, self.as_parent):
            role('a')
            self.assertEqual(self.client.get('/api/admin/drivers').status_code, 403)
            self.assertEqual(self.client.get('/api/admin/parents').status_code, 403)
            self.assertEqual(self.client.get('/api/payment/status').status_code, 403)
            self.assertEqual(self.client.get('/api/logs').status_code, 403)
        self.set_session()
        self.assertEqual(self.client.get('/api/admin/drivers').status_code, 403)
        self.assertEqual(self.client.get('/api/routes').status_code, 403)


class CrossSchoolMutationTests(IsolationBase):
    def test_cross_school_id_operations_are_rejected(self):
        self.as_admin('a')
        checks = [
            ('driver edit', self.client.put(f"/api/admin/driver/{self.id['b']['driver']}/edit",
                                            json={'name': 'Hijacked'})),
            ('driver delete', self.client.delete(f"/api/admin/driver/{self.id['b']['driver']}/delete")),
            ('parent edit', self.client.put(f"/api/admin/parent/{self.id['b']['parent']}/edit",
                                            json={'name': 'Hijacked'})),
            ('parent verify', self.client.post(
                f"/api/admin/parent/{self.id['b']['parent']}/verify-phone",
                json={'verified': True})),
            ('parent delete', self.client.delete(f"/api/admin/parent/{self.id['b']['parent']}/delete")),
            ('teacher edit', self.client.put(f"/api/teachers/{self.id['b']['teacher']}",
                                             json={'name': 'Hijacked'})),
            ('teacher delete', self.client.delete(f"/api/teachers/{self.id['b']['teacher']}")),
            ('route edit', self.client.put(f"/api/routes/{self.route['b']}",
                                           json={'name': 'Hijacked'})),
            ('route delete', self.client.delete(f"/api/routes/{self.route['b']}")),
            ('roster absent', self.client.post(
                f"/api/roster/{self.id['b']['duty']}/absent", json={})),
        ]
        for label, response in checks:
            with self.subTest(label=label):
                self.assertEqual(response.status_code, 404, f'{label} crossed the school boundary')
        with app.app_context():
            self.assertEqual(db.session.get(Driver, self.id['b']['driver']).name, 'Beta Driver')
            self.assertEqual(db.session.get(Parent, self.id['b']['parent']).name, 'Beta Parent')
            self.assertEqual(db.session.get(Teacher, self.id['b']['teacher']).name, 'Beta Teacher')
            self.assertEqual(db.session.get(Route, self.route['b']).name, 'Beta Route')

    def test_roster_replace_with_foreign_teacher_is_rejected(self):
        self.as_admin('a')
        response = self.client.post(f"/api/roster/{self.id['a']['duty']}/replace",
                                    json={'teacher_id': self.id['b']['teacher']})
        self.assertIn(response.status_code, (400, 404),
                      'school A duty accepted school B teacher (cross-tenant reference)')
        with app.app_context():
            duty = db.session.get(DutyAssignment, self.id['a']['duty'])
            self.assertEqual(duty.teacher_id, self.id['a']['teacher'])


class CrossSchoolRouteReferenceTests(IsolationBase):
    def test_foreign_route_on_driver_create_is_rejected(self):
        self.as_admin('a')
        response = self.client.post('/api/admin/driver/create', json={
            'name': 'Injected Driver', 'phone': '0730000001',
            'password': 'passw0rd1', 'route_id': self.route['b']})
        self.assertIn(response.status_code, (400, 404),
                      'school A admin attached a driver to school B route')

    def test_foreign_route_on_parent_create_is_rejected(self):
        self.as_admin('a')
        response = self.client.post('/api/admin/parent/create', json={
            'name': 'Injected Parent', 'phone': '0730000002',
            'password': 'passw0rd2', 'route_id': self.route['b']})
        self.assertIn(response.status_code, (400, 404),
                      'school A admin attached a parent to school B route')

    def test_foreign_route_on_driver_edit_is_rejected(self):
        self.as_admin('a')
        response = self.client.put(f"/api/admin/driver/{self.id['a']['driver']}/edit",
                                   json={'assigned_route_id': self.route['b']})
        self.assertIn(response.status_code, (400, 404),
                      'school A admin moved their driver onto school B route')
        with app.app_context():
            driver = db.session.get(Driver, self.id['a']['driver'])
            self.assertEqual(driver.assigned_route_id, self.route['a'])

    def test_foreign_route_on_parent_edit_is_rejected(self):
        self.as_admin('a')
        response = self.client.put(f"/api/admin/parent/{self.id['a']['parent']}/edit",
                                   json={'assigned_route_id': self.route['b']})
        self.assertIn(response.status_code, (400, 404),
                      'school A admin moved their parent onto school B route')
        with app.app_context():
            parent = db.session.get(Parent, self.id['a']['parent'])
            self.assertEqual(parent.assigned_route_id, self.route['a'])

    def test_teacher_add_parent_with_foreign_route_is_rejected(self):
        self.as_teacher('a')
        response = self.client.post('/api/teacher/add-parent', json={
            'name': 'Teacher Added', 'phone': '0730000003',
            'password': 'passw0rd3', 'route_id': self.route['b']})
        self.assertIn(response.status_code, (400, 404),
                      'school A teacher attached a parent to school B route')

    def test_legacy_foreign_driver_route_is_not_disclosed(self):
        with app.app_context():
            driver = db.session.get(Driver, self.id['a']['driver'])
            driver.assigned_route_id = self.route['b']
            db.session.commit()
        self.as_driver('a')
        response = self.client.get('/api/driver/route-info')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b'Beta Route', response.data)

    def test_legacy_foreign_parent_route_is_not_disclosed(self):
        with app.app_context():
            parent = db.session.get(Parent, self.id['a']['parent'])
            parent.assigned_route_id = self.route['b']
            db.session.commit()
        self.as_parent('a')
        response = self.client.get('/api/parent/track-bus')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b'Beta Route', response.data)


class DriverParentBoundaryTests(IsolationBase):
    def test_driver_sees_and_acts_on_own_school_only(self):
        self.as_driver('b')
        info = self.client.get('/api/driver/route-info').json
        self.assertEqual(info['route']['name'], 'Beta Route')
        self.assertEqual(info['parent_count'], 1)
        self.assertEqual(info['parents'][0]['name'], 'Beta Parent')

        alert_ids = [a['id'] for a in self.client.get('/api/driver/alerts').json]
        self.assertEqual(alert_ids, [])
        self.assertEqual(self.client.post(
            f"/api/driver/alert/{self.id['a']['alert']}/acknowledge", json={}).status_code, 404)
        self.assertEqual(self.client.post('/api/driver/notify-parent', json={
            'parent_phone': '0720000001', 'message_type': 'call'}).status_code, 404)

    def test_parent_stop_writes_do_not_cross_parents(self):
        self.as_parent('b')
        response = self.client.put('/api/parent/stops/pickup',
                                   json={'label': 'Beta gate updated'})
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            alpha_stop = ParentStop.query.filter_by(
                parent_id=self.id['a']['parent'], stop_type='pickup').first()
            beta_stops = ParentStop.query.filter_by(
                parent_id=self.id['b']['parent'], stop_type='pickup').all()
            self.assertEqual(alpha_stop.label, 'Alpha gate')
            self.assertEqual(len(beta_stops), 1)
            self.assertEqual(beta_stops[0].label, 'Beta gate updated')

    def test_parent_registration_and_login_stay_inside_the_named_school(self):
        registered = self.client.post('/api/parent/register', json={
            'school_code': 'BET', 'name': 'Registered Parent',
            'phone': '0740000001', 'password': 'passw0rd4',
            'child_name': 'Child', 'child_class': 'Grade 2'})
        self.assertEqual(registered.status_code, 200)
        with app.app_context():
            parent = Parent.query.filter_by(phone='0740000001').one()
            self.assertEqual(parent.school_id, self.b)

        wrong_school = self.client.post('/api/parent/login', json={
            'school_code': 'ALP', 'phone': '0740000001', 'password': 'passw0rd4'})
        self.assertEqual(wrong_school.status_code, 401)
        right_school = self.client.post('/api/parent/login', json={
            'school_code': 'BET', 'phone': '0740000001', 'password': 'passw0rd4'})
        self.assertEqual(right_school.status_code, 200)
        self.assertEqual(self.client.get('/api/session').json['school_id'], self.b)


class VehicleLocationScopeTests(IsolationBase):
    def vehicle_names(self):
        response = self.client.get('/api/vehicle/locations')
        return response.status_code, [v['driver_name'] for v in response.json.get('vehicles', [])]

    def test_admin_sees_only_own_school_vehicles(self):
        self.as_admin('a')
        self.assertEqual(self.vehicle_names(), (200, ['Alpha Driver']))
        self.as_admin('b')
        self.assertEqual(self.vehicle_names(), (200, ['Beta Driver']))

    def test_parent_sees_only_own_route_vehicle(self):
        self.as_parent('a')
        self.assertEqual(self.vehicle_names(), (200, ['Alpha Driver']))
        self.as_parent('b')
        self.assertEqual(self.vehicle_names(), (200, ['Beta Driver']))

    def test_teacher_sees_only_todays_duty_route_vehicle(self):
        self.as_teacher('a')
        self.assertEqual(self.vehicle_names(), (200, ['Alpha Driver']))
        self.as_teacher('b')
        self.assertEqual(self.vehicle_names(), (200, ['Beta Driver']))

    def test_anonymous_vehicle_request_is_rejected(self):
        status, _ = self.vehicle_names()
        self.assertEqual(status, 403)


class LegitimateOperationsTests(IsolationBase):
    def test_admin_manages_own_school_routes_and_people(self):
        self.as_admin('a')
        created_driver = self.client.post('/api/admin/driver/create', json={
            'name': 'New Driver', 'phone': '0731000001',
            'password': 'passw0rd5', 'route_id': self.route['a']})
        self.assertEqual(created_driver.status_code, 200)
        created_parent = self.client.post('/api/admin/parent/create', json={
            'name': 'New Parent', 'phone': '0731000002',
            'password': 'passw0rd6', 'route_id': self.route['a']})
        self.assertEqual(created_parent.status_code, 200)

        drivers = {d['name']: d for d in self.client.get('/api/admin/drivers').json}
        self.assertEqual(drivers['New Driver']['assigned_route_name'], 'Alpha Route')
        parents = {p['name']: p for p in self.client.get('/api/admin/parents').json}
        self.assertEqual(parents['New Parent']['assigned_route_name'], 'Alpha Route')

        unassign = self.client.put(
            f"/api/admin/driver/{created_driver.json['driver_id']}/edit",
            json={'assigned_route_id': None})
        self.assertEqual(unassign.status_code, 200)
        with app.app_context():
            self.assertIsNone(db.session.get(Driver, created_driver.json['driver_id']).assigned_route_id)

    def test_teacher_adds_parent_on_own_route(self):
        self.as_teacher('a')
        response = self.client.post('/api/teacher/add-parent', json={
            'name': 'Teacher Added', 'phone': '0731000003',
            'password': 'passw0rd7', 'route_id': self.route['a']})
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            parent = db.session.get(Parent, response.json['parent_id'])
            self.assertEqual(parent.school_id, self.a)
            self.assertEqual(parent.assigned_route_id, self.route['a'])

    def test_roster_replace_accepts_a_teacher_from_the_same_school(self):
        self.as_admin('a')
        response = self.client.post(f"/api/roster/{self.id['a']['duty']}/replace",
                                    json={'teacher_id': self.id['a']['teacher2']})
        self.assertEqual(response.status_code, 200)
        with app.app_context():
            duty = db.session.get(DutyAssignment, self.id['a']['duty'])
            self.assertEqual(duty.teacher_id, self.id['a']['teacher2'])


if __name__ == '__main__':
    unittest.main()
