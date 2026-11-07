"""WSGI entrypoint that adds secure, role-scoped live vehicle visibility."""
from datetime import date

from flask import jsonify, request

from app import app, Driver, DutyAssignment, Route, current_school_id


def _vehicle_scope():
    """Return drivers visible to the signed-in role, within its school scope."""
    if session.get('driver_id'):
        return Driver.query.filter_by(
            id=session['driver_id'], school_id=current_school_id(), active=True
        ).all(), None

    if session.get('school_admin_id'):
        return Driver.query.filter_by(
            school_id=current_school_id(), active=True
        ).all(), None

    if session.get('parent_id'):
        parent = Parent.query.filter_by(
            id=session['parent_id'], school_id=current_school_id(), active=True
        ).first()
        if not parent or not parent.assigned_route_id:
            return [], 'No route is assigned to your child yet.'
        return Driver.query.filter_by(
            school_id=parent.school_id,
            assigned_route_id=parent.assigned_route_id,
            active=True
        ).all(), None

    if session.get('teacher_id'):
        teacher = Teacher.query.filter_by(
            id=session['teacher_id'], school_id=current_school_id(), active=True
        ).first()
        if not teacher:
            return [], 'Teacher account could not be found.'
        route_ids = [row.route_id for row in DutyAssignment.query.filter_by(
            school_id=teacher.school_id, teacher_id=teacher.id,
            duty_date=date.today(), status='assigned'
        ).all()]
        if not route_ids:
            return [], 'No route is assigned to you today.'
        return Driver.query.filter(
            Driver.school_id == teacher.school_id,
            Driver.assigned_route_id.in_(route_ids),
            Driver.active.is_(True)
        ).all(), None

    return None, 'Please sign in to view vehicle locations.'


# Import these after the application module has initialized its models.
from flask import session
from app import Parent, Teacher


@app.route('/api/vehicle/locations')
def vehicle_locations():
    """Return only vehicle locations the current school user may see."""
    drivers, message = _vehicle_scope()
    if drivers is None:
        return jsonify({'error': message}), 403

    vehicles = []
    for driver in drivers:
        route = Route.query.filter_by(
            id=driver.assigned_route_id, school_id=driver.school_id
        ).first() if driver.assigned_route_id else None
        live = bool(
            driver.is_tracking and driver.current_latitude is not None
            and driver.current_longitude is not None
        )
        vehicles.append({
            'id': driver.id,
            'driver_name': driver.name,
            'route_name': route.name if route else 'Route not assigned',
            'route_type': ('Morning' if route.is_morning else 'Evening') if route else '',
            'is_tracking': live,
            'latitude': driver.current_latitude if live else None,
            'longitude': driver.current_longitude if live else None,
            'last_update': driver.last_location_update.isoformat() if driver.last_location_update else None
        })

    return jsonify({'vehicles': vehicles, 'message': message})


@app.after_request
def add_vehicle_map_to_signed_in_pages(response):
    """Load the shared map widget in each signed-in role's existing dashboard."""
    if (response.mimetype == 'text/html'
            and response.status_code == 200
            and not request.path.startswith('/static/')):
        html = response.get_data(as_text=True)
        if '</body>' in html and '/static/js/vehicle-map.js' not in html:
            html = html.replace(
                '</body>',
                '<script src="/static/js/vehicle-map.js" defer></script></body>'
            )
            response.set_data(html)
    return response
