import hashlib
import hmac
import json
import math
import re
import secrets
import uuid
from datetime import date
from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db

ride_bp = Blueprint('ride_hailing', __name__)

RIDE_SETTING_LIMITS = {
    'matching_radius_m': (100, 20000, 5000),
    'offer_timeout_seconds': (10, 120, 30),
    'max_driver_offers': (1, 25, 10)
}


@ride_bp.before_request
def require_postgis_database():
    if request.path.startswith('/api/rides') and db.engine.dialect.name != 'postgresql':
        return jsonify({
            'error': 'Ride-hailing requires PostgreSQL 15+ with PostGIS. '
                     'The school transport module can continue using SQLite.'
        }), 503


def _role_required(*roles):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = session.get('ride_user_id')
            role = session.get('ride_role')
            if not user_id or role not in roles:
                return jsonify({'error': 'Sign in with an authorised ride-hailing account'}), 403
            try:
                uuid.UUID(str(user_id))
            except (ValueError, TypeError):
                session.pop('ride_user_id', None)
                session.pop('ride_role', None)
                return jsonify({'error': 'Invalid session'}), 403
            with db.engine.connect() as connection:
                account = connection.execute(text(
                    'SELECT role, status FROM ride_hailing.users WHERE id = :id'
                ), {'id': user_id}).first()
            if not account or account.status != 'active' or account.role != role:
                session.pop('ride_user_id', None)
                session.pop('ride_role', None)
                session.pop('ride_name', None)
                return jsonify({'error': 'Account is not active'}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorate


def _json_body():
    return request.get_json(silent=True) or {}


def _coordinates(data, prefix):
    latitude_key = f'{prefix}_latitude' if prefix else 'latitude'
    longitude_key = f'{prefix}_longitude' if prefix else 'longitude'
    try:
        latitude = float(data[latitude_key])
        longitude = float(data[longitude_key])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f'Provide valid {prefix} latitude and longitude')
    if (not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError(f'{prefix.capitalize()} coordinates are outside the valid range')
    return latitude, longitude


def _json_value(value):
    return json.dumps(value, separators=(',', ':')) if value is not None else None


def _notify(connection, user_id, kind, title, body, data=None):
    connection.execute(text('''
        INSERT INTO ride_hailing.notifications (user_id, kind, title, body, data)
        VALUES (:user_id, :kind, :title, :body, CAST(:data AS jsonb))
    '''), {
        'user_id': user_id, 'kind': kind, 'title': title,
        'body': body, 'data': _json_value(data)
    })


def _event(connection, ride_id, event_type, actor_id=None, payload=None):
    connection.execute(text('''
        INSERT INTO ride_hailing.ride_events (ride_id, event_type, actor_id, payload)
        VALUES (:ride_id, :event_type, :actor_id, CAST(:payload AS jsonb))
    '''), {
        'ride_id': ride_id, 'event_type': event_type,
        'actor_id': actor_id, 'payload': _json_value(payload)
    })


def _audit(connection, actor_id, action, entity, entity_id=None, before=None, after=None):
    connection.execute(text('''
        INSERT INTO ride_hailing.audit_log
            (actor_id, action, entity, entity_id, before_json, after_json, ip_address)
        VALUES (
            :actor_id, :action, :entity, :entity_id,
            CAST(:before_json AS jsonb), CAST(:after_json AS jsonb),
            CAST(:ip_address AS inet)
        )
    '''), {
        'actor_id': actor_id, 'action': action, 'entity': entity,
        'entity_id': str(entity_id) if entity_id is not None else None,
        'before_json': _json_value(before), 'after_json': _json_value(after),
        'ip_address': request.remote_addr
    })


def _mark_driver_pending(connection, driver_id, note):
    profile = connection.execute(text('''
        SELECT verification_status, availability FROM ride_hailing.driver_profiles
        WHERE user_id = :driver_id FOR UPDATE
    '''), {'driver_id': driver_id}).mappings().first()
    if not profile:
        raise ValueError('Driver profile not found')
    if profile['verification_status'] != 'pending':
        connection.execute(text('''
            UPDATE ride_hailing.driver_profiles
            SET verification_status = 'pending'::ride_hailing.verification_status,
                verified_at = NULL, rejection_reason = NULL
            WHERE user_id = :driver_id
        '''), {'driver_id': driver_id})
        connection.execute(text('''
            INSERT INTO ride_hailing.driver_status_history
                (driver_id, old_status, new_status, note)
            VALUES (
                :driver_id, CAST(:old_status AS ride_hailing.verification_status),
                'pending'::ride_hailing.verification_status, :note
            )
        '''), {
            'driver_id': driver_id, 'old_status': profile['verification_status'],
            'note': note
        })
    if profile['availability'] == 'online':
        connection.execute(text('''
            UPDATE ride_hailing.driver_profiles
            SET availability = 'offline'::ride_hailing.driver_availability
            WHERE user_id = :driver_id
        '''), {'driver_id': driver_id})
        connection.execute(text('''
            UPDATE ride_hailing.driver_sessions
            SET went_offline = now()
            WHERE driver_id = :driver_id AND went_offline IS NULL
        '''), {'driver_id': driver_id})


def _ride_setting(connection, key):
    minimum, maximum, default = RIDE_SETTING_LIMITS[key]
    value = connection.execute(text('''
        SELECT CASE
            WHEN jsonb_typeof(value) = 'number' AND value::text ~ '^[0-9]+$'
            THEN (value::text)::integer
            ELSE NULL
        END
        FROM ride_hailing.app_settings WHERE key = :key
    '''), {'key': key}).scalar()
    if value is None or not minimum <= value <= maximum:
        return default
    return value


@ride_bp.get('/rides')
def rider_page():
    if session.get('ride_role') != 'rider':
        return render_template('ride_access.html')
    return render_template('rides.html')


@ride_bp.get('/rides/driver')
def ride_driver_page():
    if session.get('ride_role') != 'driver':
        return render_template('ride_access.html')
    return render_template('ride_driver.html')


@ride_bp.get('/rides/admin')
def ride_admin_page():
    if session.get('ride_role') not in ('admin', 'support'):
        return render_template('ride_access.html')
    return render_template(
        'ride_admin.html',
        can_manage=session.get('ride_role') == 'admin'
    )


@ride_bp.get('/rides/setup')
def ride_admin_setup_page():
    if not session.get('super_id'):
        return render_template('ride_access.html')
    return render_template('ride_admin_setup.html')


@ride_bp.get('/api/rides/vehicle-types')
def list_vehicle_types():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id, code, display_name, seats, base_fare, per_km,
                   per_minute, min_fare
            FROM ride_hailing.vehicle_types
            WHERE active = true
            ORDER BY id
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/auth/register')
def register_ride_account():
    data = _json_body()
    role = data.get('role')
    name = str(data.get('full_name', '')).strip()
    phone = str(data.get('phone_e164', '')).strip()
    password = data.get('password', '')
    if role not in ('rider', 'driver'):
        return jsonify({'error': 'Role must be rider or driver'}), 400
    if not name or len(name) > 160 or not re.fullmatch(r'\+[1-9]\d{7,14}', phone):
        return jsonify({'error': 'Provide a name and a valid E.164 phone number'}), 400
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        return jsonify({'error': 'Password must be between 10 and 256 characters'}), 400

    password_hash = generate_password_hash(password)
    try:
        with db.engine.begin() as connection:
            user_id = connection.execute(text('''
                INSERT INTO ride_hailing.users
                    (role, phone_e164, full_name, password_hash)
                VALUES (CAST(:role AS ride_hailing.user_role), :phone, :name, :password_hash)
                RETURNING id
            '''), {
                'role': role, 'phone': phone, 'name': name,
                'password_hash': password_hash
            }).scalar_one()
            if role == 'rider':
                connection.execute(text('''
                    INSERT INTO ride_hailing.rider_profiles (user_id)
                    VALUES (:user_id)
                '''), {'user_id': user_id})
            else:
                connection.execute(text('''
                    INSERT INTO ride_hailing.driver_profiles (user_id)
                    VALUES (:user_id)
                '''), {'user_id': user_id})
                connection.execute(text('''
                    INSERT INTO ride_hailing.driver_status_history
                        (driver_id, new_status, note)
                    VALUES (:user_id, 'not_started', 'Driver account created')
                '''), {'user_id': user_id})
    except IntegrityError:
        return jsonify({'error': 'That phone number is already registered'}), 409

    session.clear()
    session['ride_user_id'] = str(user_id)
    session['ride_role'] = role
    session['ride_name'] = name
    return jsonify({
        'success': True,
        'user_id': str(user_id),
        'role': role,
        'verification_status': 'not_started' if role == 'driver' else None
    }), 201


@ride_bp.post('/api/rides/auth/login')
def login_ride_account():
    data = _json_body()
    phone = str(data.get('phone_e164', '')).strip()
    password = data.get('password', '')
    if not isinstance(password, str) or len(password) > 256:
        return jsonify({'error': 'Invalid credentials or inactive account'}), 401
    with db.engine.connect() as connection:
        account = connection.execute(text('''
            SELECT id, role, full_name, password_hash, status
            FROM ride_hailing.users
            WHERE phone_e164 = :phone
        '''), {'phone': phone}).mappings().first()
    if (not account or account['status'] != 'active'
            or not account['password_hash']
            or not check_password_hash(account['password_hash'], password)):
        return jsonify({'error': 'Invalid credentials or inactive account'}), 401
    with db.engine.begin() as connection:
        connection.execute(text('''
            UPDATE ride_hailing.users SET last_login_at = now() WHERE id = :user_id
        '''), {'user_id': account['id']})
    session.clear()
    session['ride_user_id'] = str(account['id'])
    session['ride_role'] = account['role']
    session['ride_name'] = account['full_name']
    return jsonify({
        'success': True, 'user_id': str(account['id']),
        'role': account['role'], 'name': account['full_name']
    })


@ride_bp.get('/api/rides/auth/session')
def ride_session():
    if not session.get('ride_user_id'):
        return jsonify({'type': None})
    return jsonify({
        'type': session.get('ride_role'),
        'id': session.get('ride_user_id'),
        'name': session.get('ride_name')
    })


@ride_bp.post('/api/rides/auth/logout')
def ride_logout():
    session.clear()
    return jsonify({'success': True})


@ride_bp.post('/api/rides/admin/accounts')
def create_ride_admin():
    if not session.get('super_id'):
        return jsonify({'error': 'Only the existing platform super admin can create ride administrators'}), 403
    data = _json_body()
    role = data.get('role', 'admin')
    name = str(data.get('full_name', '')).strip()
    phone = str(data.get('phone_e164', '')).strip()
    password = data.get('password', '')
    if role not in ('admin', 'support'):
        return jsonify({'error': 'Role must be admin or support'}), 400
    if not name or not re.fullmatch(r'\+[1-9]\d{7,14}', phone):
        return jsonify({'error': 'Provide a name and valid E.164 phone number'}), 400
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        return jsonify({'error': 'Password must be between 10 and 256 characters'}), 400
    try:
        with db.engine.begin() as connection:
            user_id = connection.execute(text('''
                INSERT INTO ride_hailing.users
                    (role, phone_e164, full_name, password_hash)
                VALUES (CAST(:role AS ride_hailing.user_role), :phone, :name, :password_hash)
                RETURNING id
            '''), {
                'role': role, 'phone': phone, 'name': name,
                'password_hash': generate_password_hash(password)
            }).scalar_one()
    except IntegrityError:
        return jsonify({'error': 'That phone number is already registered'}), 409
    return jsonify({'success': True, 'user_id': str(user_id), 'role': role}), 201


@ride_bp.get('/api/rides/profile')
@_role_required('rider', 'driver', 'admin', 'support')
def ride_profile():
    user_id = session['ride_user_id']
    with db.engine.connect() as connection:
        user = connection.execute(text('''
            SELECT id, role, phone_e164, email, full_name, avatar_url,
                   language, status, created_at
            FROM ride_hailing.users WHERE id = :user_id
        '''), {'user_id': user_id}).mappings().first()
        profile = None
        if user['role'] == 'driver':
            profile = connection.execute(text('''
                SELECT verification_status, availability, rating_avg, rating_count,
                       total_trips, current_vehicle_id
                FROM ride_hailing.driver_profiles WHERE user_id = :user_id
            '''), {'user_id': user_id}).mappings().first()
        elif user['role'] == 'rider':
            profile = connection.execute(text('''
                SELECT rating_avg, rating_count, total_trips
                FROM ride_hailing.rider_profiles WHERE user_id = :user_id
            '''), {'user_id': user_id}).mappings().first()
    return jsonify({'user': dict(user), 'profile': dict(profile) if profile else None})


@ride_bp.get('/api/rides/devices')
@_role_required('rider', 'driver', 'admin', 'support')
def list_registered_devices():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id::text AS id, platform, app_version, last_seen_at, created_at
            FROM ride_hailing.devices WHERE user_id = :user_id
            ORDER BY last_seen_at DESC NULLS LAST
        '''), {'user_id': session['ride_user_id']}).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/devices')
@_role_required('rider', 'driver', 'admin', 'support')
def register_device():
    data = _json_body()
    platform = data.get('platform')
    push_token = str(data.get('push_token', '')).strip() or None
    app_version = str(data.get('app_version', '')).strip()[:80] or None
    if platform not in ('ios', 'android', 'web'):
        return jsonify({'error': 'Platform must be ios, android or web'}), 400
    if push_token is not None and len(push_token) > 4096:
        return jsonify({'error': 'Push token is too long'}), 400
    with db.engine.begin() as connection:
        row = connection.execute(text('''
            INSERT INTO ride_hailing.devices
                (user_id, platform, push_token, app_version, last_seen_at)
            VALUES (:user_id, :platform, :push_token, :app_version, now())
            ON CONFLICT (user_id, push_token) DO UPDATE
            SET platform = EXCLUDED.platform,
                app_version = EXCLUDED.app_version,
                last_seen_at = now()
            RETURNING id::text AS id, platform, app_version, last_seen_at
        '''), {
            'user_id': session['ride_user_id'], 'platform': platform,
            'push_token': push_token, 'app_version': app_version
        }).mappings().one()
    return jsonify(dict(row)), 201


@ride_bp.delete('/api/rides/devices/<device_id>')
@_role_required('rider', 'driver', 'admin', 'support')
def remove_registered_device(device_id):
    try:
        device_id = _valid_uuid(device_id, 'device id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    with db.engine.begin() as connection:
        result = connection.execute(text('''
            DELETE FROM ride_hailing.devices
            WHERE id = :device_id AND user_id = :user_id
        '''), {'device_id': device_id, 'user_id': session['ride_user_id']})
    if result.rowcount == 0:
        return jsonify({'error': 'Device not found'}), 404
    return jsonify({'success': True})


@ride_bp.get('/api/rides/places')
@_role_required('rider', 'driver')
def list_saved_places():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id, label, address,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude, created_at
            FROM ride_hailing.saved_places
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        '''), {'user_id': session['ride_user_id']}).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/places')
@_role_required('rider', 'driver')
def save_place():
    data = _json_body()
    label = str(data.get('label', '')).strip()[:80]
    address = str(data.get('address', '')).strip()[:300] or None
    try:
        latitude = float(data['latitude'])
        longitude = float(data['longitude'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'Provide valid latitude and longitude'}), 400
    if (not label or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        return jsonify({'error': 'Provide a label and valid coordinates'}), 400
    with db.engine.begin() as connection:
        _mark_driver_pending(connection, session['ride_user_id'], 'Verification document submitted')
        row = connection.execute(text('''
            INSERT INTO ride_hailing.saved_places (user_id, label, address, location)
            VALUES (
                :user_id, :label, :address,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
            )
            RETURNING id::text AS id, label, address, created_at
        '''), {
            'user_id': session['ride_user_id'], 'label': label, 'address': address,
            'latitude': latitude, 'longitude': longitude
        }).mappings().one()
    return jsonify(dict(row)), 201


@ride_bp.delete('/api/rides/places/<place_id>')
@_role_required('rider', 'driver')
def delete_saved_place(place_id):
    try:
        uuid.UUID(place_id)
    except ValueError:
        return jsonify({'error': 'Invalid place id'}), 400
    with db.engine.begin() as connection:
        result = connection.execute(text('''
            DELETE FROM ride_hailing.saved_places
            WHERE id = :place_id AND user_id = :user_id
        '''), {'place_id': place_id, 'user_id': session['ride_user_id']})
    if not result.rowcount:
        return jsonify({'error': 'Saved place not found'}), 404
    return jsonify({'success': True})


@ride_bp.get('/api/rides/driver/profile')
@_role_required('driver')
def driver_ride_profile():
    with db.engine.connect() as connection:
        row = connection.execute(text('''
            SELECT d.verification_status, d.rejection_reason, d.availability, d.rating_avg,
                   d.rating_count, d.total_trips, d.current_vehicle_id,
                   v.plate_number, v.make, v.model, v.color, v.verification_status AS vehicle_status,
                   vt.display_name AS vehicle_type
            FROM ride_hailing.driver_profiles d
            LEFT JOIN ride_hailing.vehicles v ON v.id = d.current_vehicle_id
            LEFT JOIN ride_hailing.vehicle_types vt ON vt.id = v.vehicle_type_id
            WHERE d.user_id = :user_id
        '''), {'user_id': session['ride_user_id']}).mappings().first()
    return jsonify(dict(row) if row else {})


@ride_bp.post('/api/rides/driver/vehicles')
@_role_required('driver')
def register_driver_vehicle():
    data = _json_body()
    required = ('vehicle_type_id', 'plate_number', 'make', 'model')
    if any(not data.get(field) for field in required):
        return jsonify({'error': 'Vehicle type, plate, make and model are required'}), 400
    try:
        vehicle_type_id = int(data['vehicle_type_id'])
        year = int(data['year']) if data.get('year') else None
        insurance_expires = date.fromisoformat(data['insurance_expires']) if data.get('insurance_expires') else None
        inspection_expires = date.fromisoformat(data['inspection_expires']) if data.get('inspection_expires') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Vehicle type, year and expiry dates must be valid'}), 400
    plate = str(data['plate_number']).strip().upper()
    make = str(data['make']).strip()
    model = str(data['model']).strip()
    if (not plate or len(plate) > 20 or not make or len(make) > 80
            or not model or len(model) > 80
            or (year is not None and not 1950 <= year <= 2100)):
        return jsonify({'error': 'Provide a valid plate, make, model and year'}), 400

    with db.engine.begin() as connection:
        driver = connection.execute(text('''
            SELECT verification_status, availability FROM ride_hailing.driver_profiles
            WHERE user_id = :user_id FOR UPDATE
        '''), {'user_id': session['ride_user_id']}).mappings().first()
        if not driver:
            return jsonify({'error': 'Driver profile not found'}), 404
        if driver['availability'] == 'on_trip':
            return jsonify({'error': 'Finish your active ride before changing vehicles'}), 409
        if not connection.execute(text('''
            SELECT 1 FROM ride_hailing.vehicle_types WHERE id = :type_id AND active
        '''), {'type_id': vehicle_type_id}).first():
            return jsonify({'error': 'Vehicle type is unavailable'}), 404
        if connection.execute(text('''
            SELECT 1 FROM ride_hailing.vehicles WHERE plate_number = :plate
        '''), {'plate': plate}).first():
            return jsonify({'error': 'That plate number is already registered'}), 409
        vehicle_id = connection.execute(text('''
            INSERT INTO ride_hailing.vehicles
                (owner_id, vehicle_type_id, plate_number, make, model, year, color,
                 insurance_expires, inspection_expires)
            VALUES (
                :owner_id, :type_id, :plate, :make, :model, :year, :color,
                :insurance_expires, :inspection_expires
            )
            RETURNING id
        '''), {
            'owner_id': session['ride_user_id'],
            'type_id': vehicle_type_id,
            'plate': plate,
            'make': make,
            'model': model,
            'year': year,
            'color': str(data.get('color', '')).strip()[:40] or None,
            'insurance_expires': insurance_expires,
            'inspection_expires': inspection_expires
        }).scalar_one()
        connection.execute(text('''
            UPDATE ride_hailing.driver_profiles
            SET current_vehicle_id = :vehicle_id
            WHERE user_id = :user_id
        '''), {'vehicle_id': vehicle_id, 'user_id': session['ride_user_id']})
        _mark_driver_pending(connection, session['ride_user_id'], 'Vehicle submitted for review')
    return jsonify({'success': True, 'vehicle_id': str(vehicle_id), 'status': 'pending'}), 201


@ride_bp.post('/api/rides/driver/documents')
@_role_required('driver')
def add_driver_document():
    data = _json_body()
    doc_type = data.get('doc_type')
    storage_key = str(data.get('storage_key', '')).strip()
    file_sha256 = str(data.get('file_sha256', '')).lower()
    allowed = {
        'national_id', 'passport', 'drivers_license', 'vehicle_registration',
        'insurance', 'operator_badge', 'good_conduct_certificate',
        'vehicle_inspection', 'profile_selfie', 'vehicle_photo'
    }
    if (doc_type not in allowed
            or not re.fullmatch(r'[A-Za-z0-9/._=-]{1,500}', storage_key)
            or '..' in storage_key
            or not re.fullmatch(r'[a-f0-9]{64}', file_sha256)):
        return jsonify({'error': 'Provide a supported document type, private storage key and SHA-256 hash'}), 400
    with db.engine.begin() as connection:
        row = connection.execute(text('''
            INSERT INTO ride_hailing.driver_documents
                (driver_id, doc_type, storage_key, file_sha256, status)
            VALUES (
                :driver_id, CAST(:doc_type AS ride_hailing.document_type),
                :storage_key, :file_sha256, 'pending'
            )
            RETURNING id::text AS id, doc_type, status, uploaded_at
        '''), {
            'driver_id': session['ride_user_id'], 'doc_type': doc_type,
            'storage_key': storage_key, 'file_sha256': file_sha256
        }).mappings().one()
    return jsonify(dict(row)), 201


@ride_bp.post('/api/rides/driver/availability')
@_role_required('driver')
def set_driver_availability():
    data = _json_body()
    requested = data.get('availability')
    if requested not in ('online', 'offline'):
        return jsonify({'error': 'Availability must be online or offline'}), 400
    user_id = session['ride_user_id']
    with db.engine.begin() as connection:
        profile = connection.execute(text('''
            SELECT verification_status, availability, current_vehicle_id
            FROM ride_hailing.driver_profiles
            WHERE user_id = :user_id FOR UPDATE
        '''), {'user_id': user_id}).mappings().first()
        if not profile:
            return jsonify({'error': 'Driver profile not found'}), 404
        if requested == 'online':
            vehicle = connection.execute(text('''
                SELECT verification_status, active,
                       insurance_expires < current_date AS insurance_expired,
                       inspection_expires < current_date AS inspection_expired
                FROM ride_hailing.vehicles WHERE id = :vehicle_id
            '''), {'vehicle_id': profile['current_vehicle_id']}).mappings().first()
            if (profile['verification_status'] != 'approved' or not vehicle
                    or vehicle['verification_status'] != 'approved' or not vehicle['active']
                    or vehicle['insurance_expired'] or vehicle['inspection_expired']):
                return jsonify({'error': 'Driver and vehicle must be approved before going online'}), 409
            if profile['availability'] == 'on_trip':
                return jsonify({'error': 'Finish the active ride before changing availability'}), 409
            if profile['availability'] != 'online':
                connection.execute(text('''
                    UPDATE ride_hailing.driver_profiles
                    SET availability = 'online'::ride_hailing.driver_availability
                    WHERE user_id = :user_id
                '''), {'user_id': user_id})
                connection.execute(text('''
                    INSERT INTO ride_hailing.driver_sessions (driver_id, vehicle_id)
                    VALUES (:driver_id, :vehicle_id)
                '''), {'driver_id': user_id, 'vehicle_id': profile['current_vehicle_id']})
        else:
            if profile['availability'] == 'on_trip':
                return jsonify({'error': 'Finish the active ride before going offline'}), 409
            connection.execute(text('''
                UPDATE ride_hailing.driver_profiles
                SET availability = 'offline'::ride_hailing.driver_availability
                WHERE user_id = :user_id
            '''), {'user_id': user_id})
            connection.execute(text('''
                UPDATE ride_hailing.driver_sessions
                SET went_offline = now()
                WHERE driver_id = :driver_id AND went_offline IS NULL
            '''), {'driver_id': user_id})
    return jsonify({'success': True, 'availability': requested})


@ride_bp.post('/api/rides/driver/location')
@_role_required('driver')
def update_driver_location():
    data = _json_body()
    try:
        latitude = float(data['latitude'])
        longitude = float(data['longitude'])
        accuracy = float(data['accuracy_m']) if data.get('accuracy_m') is not None else None
        speed = float(data['speed_mps']) if data.get('speed_mps') is not None else None
        heading = float(data['heading']) if data.get('heading') is not None else None
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'Provide valid coordinates and optional GPS measurements'}), 400
    if (not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        return jsonify({'error': 'Coordinates are outside the valid range'}), 400
    if ((accuracy is not None and (not math.isfinite(accuracy) or accuracy < 0))
            or (speed is not None and (not math.isfinite(speed) or speed < 0))
            or (heading is not None and (not math.isfinite(heading) or not 0 <= heading <= 360))):
        return jsonify({'error': 'GPS accuracy, speed and heading must be valid non-negative values'}), 400
    user_id = session['ride_user_id']
    with db.engine.begin() as connection:
        driver = connection.execute(text('''
            SELECT availability FROM ride_hailing.driver_profiles
            WHERE user_id = :user_id
        '''), {'user_id': user_id}).mappings().first()
        if not driver or driver['availability'] not in ('online', 'on_trip'):
            return jsonify({'error': 'Go online before sharing live location'}), 409
        connection.execute(text('''
            INSERT INTO ride_hailing.driver_locations_live
                (driver_id, location, heading, speed_mps, accuracy_m, updated_at)
            VALUES (
                :driver_id,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                :heading, :speed, :accuracy, now()
            )
            ON CONFLICT (driver_id) DO UPDATE SET
                location = EXCLUDED.location,
                heading = EXCLUDED.heading,
                speed_mps = EXCLUDED.speed_mps,
                accuracy_m = EXCLUDED.accuracy_m,
                updated_at = now()
        '''), {
            'driver_id': user_id, 'latitude': latitude, 'longitude': longitude,
            'heading': heading, 'speed': speed, 'accuracy': accuracy
        })
        active_ride = connection.execute(text('''
            SELECT id FROM ride_hailing.rides
            WHERE driver_id = :driver_id AND status = 'in_progress'
            ORDER BY started_at DESC LIMIT 1
        '''), {'driver_id': user_id}).scalar()
        if active_ride:
            connection.execute(text('''
                INSERT INTO ride_hailing.trip_points
                    (ride_id, user_id, location, heading, speed_mps, accuracy_m, recorded_at)
                VALUES (
                    :ride_id, :user_id,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                    :heading, :speed, :accuracy, now()
                )
            '''), {
                'ride_id': active_ride, 'user_id': user_id,
                'latitude': latitude, 'longitude': longitude,
                'heading': heading, 'speed': speed, 'accuracy': accuracy
            })
    return jsonify({'success': True})


@ride_bp.post('/api/rides/request')
@_role_required('rider')
def request_ride():
    data = _json_body()
    try:
        pickup_lat, pickup_lng = _coordinates(data, 'pickup')
        dropoff_lat, dropoff_lng = _coordinates(data, 'dropoff')
        vehicle_type_id = int(data['vehicle_type_id'])
    except (ValueError, KeyError, TypeError) as exc:
        return jsonify({'error': str(exc) or 'Provide a vehicle type'}), 400
    pickup_address = str(data.get('pickup_address', '')).strip()[:300] or None
    dropoff_address = str(data.get('dropoff_address', '')).strip()[:300] or None
    notes = str(data.get('rider_notes', '')).strip()[:1000] or None
    rider_id = session['ride_user_id']
    verification_code = f'{secrets.randbelow(10000):04d}'

    with db.engine.begin() as connection:
        vehicle_type = connection.execute(text('''
            SELECT id, base_fare, per_km, per_minute, min_fare
            FROM ride_hailing.vehicle_types
            WHERE id = :id AND active = true
        '''), {'id': vehicle_type_id}).mappings().first()
        if not vehicle_type:
            return jsonify({'error': 'Selected ride type is unavailable'}), 404

        areas = connection.execute(text('''
            SELECT
                (SELECT id FROM ride_hailing.service_areas
                 WHERE active AND ST_Covers(
                     boundary::geometry,
                     ST_SetSRID(ST_MakePoint(:pickup_lng, :pickup_lat), 4326)
                 ) ORDER BY id LIMIT 1) AS pickup_area,
                EXISTS (
                    SELECT 1 FROM ride_hailing.service_areas
                    WHERE active AND ST_Covers(
                        boundary::geometry,
                        ST_SetSRID(ST_MakePoint(:dropoff_lng, :dropoff_lat), 4326)
                    )
                ) AS dropoff_served
        '''), {
            'pickup_lng': pickup_lng, 'pickup_lat': pickup_lat,
            'dropoff_lng': dropoff_lng, 'dropoff_lat': dropoff_lat
        }).mappings().one()
        if not areas['pickup_area']:
            return jsonify({'error': 'Pickup is outside the active service area'}), 400
        if not areas['dropoff_served']:
            return jsonify({'error': 'Drop-off is outside the active service area'}), 400

        ride = connection.execute(text('''
            WITH points AS (
                SELECT
                    ST_SetSRID(ST_MakePoint(:pickup_lng, :pickup_lat), 4326)::geography AS pickup,
                    ST_SetSRID(ST_MakePoint(:dropoff_lng, :dropoff_lat), 4326)::geography AS dropoff
            ), routed AS (
                SELECT p.*,
                       c.distance_m AS routed_distance_m,
                       c.duration_s AS routed_duration_s,
                       c.polyline AS route_polyline
                FROM points p
                LEFT JOIN ride_hailing.route_cache c
                  ON c.origin_cell = ST_GeoHash(p.pickup::geometry, 7)
                 AND c.dest_cell = ST_GeoHash(p.dropoff::geometry, 7)
                 AND c.created_at > now() - interval '30 days'
            ), estimate AS (
                SELECT pickup, dropoff,
                       COALESCE(routed_distance_m, ST_Distance(pickup, dropoff)::integer) AS distance_m,
                       COALESCE(routed_duration_s,
                           GREATEST(60, CEIL(ST_Distance(pickup, dropoff) / 8.0))::integer) AS duration_s,
                       route_polyline
                FROM routed
            ), zone AS (
                SELECT COALESCE((
                    SELECT multiplier FROM ride_hailing.pricing_zones
                    WHERE area_id = :area_id
                      AND (valid_from IS NULL OR valid_from <= now())
                      AND (valid_to IS NULL OR valid_to > now())
                      AND ST_Covers(boundary::geometry, (SELECT pickup::geometry FROM estimate))
                    ORDER BY multiplier DESC LIMIT 1
                ), 1.0) AS multiplier
            )
            INSERT INTO ride_hailing.rides
                (rider_id, vehicle_type_id, area_id, status,
                 pickup_location, pickup_address, dropoff_location, dropoff_address,
                 est_distance_m, est_duration_s, est_fare, route_polyline,
                 rider_notes, verification_code)
            SELECT
                :rider_id, :vehicle_type_id, :area_id,
                'matching'::ride_hailing.ride_status,
                estimate.pickup, :pickup_address, estimate.dropoff, :dropoff_address,
                estimate.distance_m, estimate.duration_s,
                GREATEST(
                    :min_fare,
                    :base_fare
                      + estimate.distance_m / 1000.0 * :per_km
                      + estimate.duration_s / 60.0 * :per_minute
                ) * zone.multiplier,
                estimate.route_polyline, :notes, :verification_code
            FROM estimate CROSS JOIN zone
            RETURNING id, status, est_distance_m, est_duration_s, est_fare
        '''), {
            'pickup_lng': pickup_lng, 'pickup_lat': pickup_lat,
            'dropoff_lng': dropoff_lng, 'dropoff_lat': dropoff_lat,
            'area_id': areas['pickup_area'], 'rider_id': rider_id,
            'vehicle_type_id': vehicle_type_id,
            'pickup_address': pickup_address, 'dropoff_address': dropoff_address,
            'notes': notes, 'verification_code': verification_code,
            'min_fare': vehicle_type['min_fare'],
            'base_fare': vehicle_type['base_fare'],
            'per_km': vehicle_type['per_km'],
            'per_minute': vehicle_type['per_minute']
        }).mappings().one()

        _event(connection, ride['id'], 'ride_requested', rider_id, {
            'vehicle_type_id': vehicle_type_id
        })
        matching_radius_m = _ride_setting(connection, 'matching_radius_m')
        offer_timeout_seconds = _ride_setting(connection, 'offer_timeout_seconds')
        max_driver_offers = _ride_setting(connection, 'max_driver_offers')
        candidates = connection.execute(text('''
            SELECT d.user_id, d.current_vehicle_id,
                   ST_Distance(l.location, r.pickup_location)::integer AS distance_to_pickup_m,
                   CEIL(ST_Distance(l.location, r.pickup_location) / 8.0)::integer AS eta_to_pickup_s
            FROM ride_hailing.rides r
            JOIN ride_hailing.driver_profiles d
              ON d.availability = 'online'::ride_hailing.driver_availability
             AND d.verification_status = 'approved'::ride_hailing.verification_status
            JOIN ride_hailing.vehicles v
              ON v.id = d.current_vehicle_id
             AND v.vehicle_type_id = r.vehicle_type_id
             AND v.verification_status = 'approved'::ride_hailing.verification_status
             AND v.active = true
             AND (v.insurance_expires IS NULL OR v.insurance_expires >= current_date)
             AND (v.inspection_expires IS NULL OR v.inspection_expires >= current_date)
            JOIN ride_hailing.driver_locations_live l
              ON l.driver_id = d.user_id
             AND l.updated_at > now() - interval '30 seconds'
            WHERE r.id = :ride_id
              AND ST_DWithin(l.location, r.pickup_location, :matching_radius_m)
              AND NOT EXISTS (
                  SELECT 1 FROM ride_hailing.user_blocks b
                  WHERE (b.blocker_id = r.rider_id AND b.blocked_id = d.user_id)
                     OR (b.blocker_id = d.user_id AND b.blocked_id = r.rider_id)
              )
            ORDER BY l.location <-> r.pickup_location
            LIMIT :max_driver_offers
        '''), {
            'ride_id': ride['id'], 'matching_radius_m': matching_radius_m,
            'max_driver_offers': max_driver_offers
        }).mappings().all()
        if not candidates:
            connection.execute(text('''
                UPDATE ride_hailing.rides
                SET status = 'no_drivers_found'::ride_hailing.ride_status,
                    updated_at = now()
                WHERE id = :ride_id
            '''), {'ride_id': ride['id']})
            _event(connection, ride['id'], 'no_drivers_found')
            _notify(connection, rider_id, 'ride_update', 'No drivers found',
                    'Try requesting again in a moment.', {'ride_id': str(ride['id'])})
            status = 'no_drivers_found'
        else:
            for candidate in candidates:
                connection.execute(text('''
                    INSERT INTO ride_hailing.ride_offers
                        (ride_id, driver_id, distance_to_pickup_m, eta_to_pickup_s, expires_at)
                    VALUES (
                        :ride_id, :driver_id, :distance_m, :eta_s,
                        now() + (:timeout_seconds * interval '1 second')
                    )
                '''), {
                    'ride_id': ride['id'], 'driver_id': candidate['user_id'],
                    'distance_m': candidate['distance_to_pickup_m'],
                    'eta_s': candidate['eta_to_pickup_s'],
                    'timeout_seconds': offer_timeout_seconds
                })
                _notify(connection, candidate['user_id'], 'ride_offer',
                        'New ride request', 'A rider nearby needs a trip.',
                        {'ride_id': str(ride['id'])})
            status = 'matching'

    return jsonify({
        'ride_id': str(ride['id']),
        'status': status,
        'estimated_distance_m': ride['est_distance_m'],
        'estimated_duration_s': ride['est_duration_s'],
        'estimated_fare': float(ride['est_fare']),
        'verification_code': verification_code if status == 'matching' else None
    }), 201


@ride_bp.get('/api/rides/driver/offers')
@_role_required('driver')
def get_driver_offers():
    with db.engine.begin() as connection:
        _expire_ride_offers(connection)
        rows = connection.execute(text('''
            SELECT o.id::text AS offer_id, r.id::text AS ride_id,
                   o.distance_to_pickup_m, o.eta_to_pickup_s, o.expires_at,
                   r.pickup_address, r.dropoff_address,
                   ST_Y(r.pickup_location::geometry) AS pickup_latitude,
                   ST_X(r.pickup_location::geometry) AS pickup_longitude,
                   ST_Y(r.dropoff_location::geometry) AS dropoff_latitude,
                   ST_X(r.dropoff_location::geometry) AS dropoff_longitude,
                   u.full_name AS rider_name
            FROM ride_hailing.ride_offers o
            JOIN ride_hailing.rides r ON r.id = o.ride_id
            JOIN ride_hailing.users u ON u.id = r.rider_id
            WHERE o.driver_id = :driver_id AND o.status = 'sent'
              AND o.expires_at > now() AND r.status = 'matching'
            ORDER BY o.distance_to_pickup_m, o.sent_at
        '''), {'driver_id': session['ride_user_id']}).mappings().all()
    return jsonify([dict(row) for row in rows])


def _expire_ride_offers(connection):
    connection.execute(text('''
            UPDATE ride_hailing.ride_offers
            SET status = 'timed_out', responded_at = now()
            WHERE status = 'sent' AND expires_at <= now()
    '''))
    rides = connection.execute(text('''
            UPDATE ride_hailing.rides r
            SET status = 'no_drivers_found'::ride_hailing.ride_status,
                updated_at = now()
            WHERE r.status = 'matching'
              AND EXISTS (SELECT 1 FROM ride_hailing.ride_offers o WHERE o.ride_id = r.id)
              AND NOT EXISTS (
                  SELECT 1 FROM ride_hailing.ride_offers o
                  WHERE o.ride_id = r.id AND o.status = 'sent' AND o.expires_at > now()
              )
            RETURNING id, rider_id
    ''')).mappings().all()
    for ride in rides:
        _event(connection, ride['id'], 'no_drivers_found')
        _notify(connection, ride['rider_id'], 'ride_update', 'No drivers found',
                'Try requesting again in a moment.', {'ride_id': str(ride['id'])})


@ride_bp.post('/api/rides/offers/<offer_id>/accept')
@_role_required('driver')
def accept_ride_offer(offer_id):
    try:
        uuid.UUID(offer_id)
    except ValueError:
        return jsonify({'error': 'Invalid offer id'}), 400
    driver_id = session['ride_user_id']
    with db.engine.begin() as connection:
        offer = connection.execute(text('''
            SELECT o.id, o.ride_id, r.rider_id, d.current_vehicle_id,
                   d.verification_status AS driver_verification,
                   v.verification_status AS vehicle_verification, v.active AS vehicle_active,
                   v.insurance_expires < current_date AS insurance_expired,
                   v.inspection_expires < current_date AS inspection_expired,
                   v.vehicle_type_id, r.vehicle_type_id AS ride_vehicle_type_id,
                   o.status AS offer_status, r.status AS ride_status
            FROM ride_hailing.ride_offers o
            JOIN ride_hailing.rides r ON r.id = o.ride_id
            JOIN ride_hailing.driver_profiles d ON d.user_id = o.driver_id
            LEFT JOIN ride_hailing.vehicles v ON v.id = d.current_vehicle_id
            WHERE o.id = :offer_id AND o.driver_id = :driver_id
              AND o.expires_at > now()
            FOR UPDATE OF o, r, d
        '''), {'offer_id': offer_id, 'driver_id': driver_id}).mappings().first()
        if not offer:
            return jsonify({'error': 'Offer not found or expired'}), 404
        if offer['offer_status'] != 'sent' or offer['ride_status'] != 'matching':
            return jsonify({'error': 'Offer is no longer available'}), 409
        if (offer['driver_verification'] != 'approved'
                or offer['vehicle_verification'] != 'approved'
                or not offer['vehicle_active']
                or offer['insurance_expired'] or offer['inspection_expired']
                or offer['vehicle_type_id'] != offer['ride_vehicle_type_id']):
            return jsonify({'error': 'Your approved vehicle or verification has changed'}), 409
        profile = connection.execute(text('''
            SELECT availability FROM ride_hailing.driver_profiles WHERE user_id = :driver_id
        '''), {'driver_id': driver_id}).mappings().one()
        if profile['availability'] != 'online':
            return jsonify({'error': 'You must be online to accept an offer'}), 409
        connection.execute(text('''
            UPDATE ride_hailing.ride_offers
            SET status = 'accepted', responded_at = now()
            WHERE id = :offer_id
        '''), {'offer_id': offer_id})
        connection.execute(text('''
            UPDATE ride_hailing.ride_offers
            SET status = 'cancelled', responded_at = now()
            WHERE ride_id = :ride_id AND id <> :offer_id AND status = 'sent'
        '''), {'ride_id': offer['ride_id'], 'offer_id': offer_id})
        connection.execute(text('''
            UPDATE ride_hailing.rides
            SET driver_id = :driver_id, vehicle_id = :vehicle_id,
                status = 'driver_assigned'::ride_hailing.ride_status,
                assigned_at = now(), updated_at = now()
            WHERE id = :ride_id
        '''), {
            'driver_id': driver_id, 'vehicle_id': offer['current_vehicle_id'],
            'ride_id': offer['ride_id']
        })
        connection.execute(text('''
            UPDATE ride_hailing.driver_profiles
            SET availability = 'on_trip'::ride_hailing.driver_availability
            WHERE user_id = :driver_id
        '''), {'driver_id': driver_id})
        _event(connection, offer['ride_id'], 'driver_assigned', driver_id)
        _notify(connection, offer['rider_id'], 'ride_update', 'Driver found',
                'A driver accepted your ride request.',
                {'ride_id': str(offer['ride_id'])})
    return jsonify({'success': True, 'ride_id': str(offer['ride_id'])})


@ride_bp.post('/api/rides/offers/<offer_id>/decline')
@_role_required('driver')
def decline_ride_offer(offer_id):
    try:
        uuid.UUID(offer_id)
    except ValueError:
        return jsonify({'error': 'Invalid offer id'}), 400
    with db.engine.begin() as connection:
        result = connection.execute(text('''
            UPDATE ride_hailing.ride_offers
            SET status = 'declined', responded_at = now()
            WHERE id = :offer_id AND driver_id = :driver_id
              AND status = 'sent' AND expires_at > now()
            RETURNING ride_id
        '''), {'offer_id': offer_id, 'driver_id': session['ride_user_id']}).first()
        if not result:
            return jsonify({'error': 'Offer is unavailable'}), 404
        remaining = connection.execute(text('''
            SELECT count(*) FROM ride_hailing.ride_offers
            WHERE ride_id = :ride_id AND status = 'sent' AND expires_at > now()
        '''), {'ride_id': result.ride_id}).scalar_one()
        if remaining == 0:
            ride = connection.execute(text('''
                UPDATE ride_hailing.rides
                SET status = 'no_drivers_found'::ride_hailing.ride_status,
                    updated_at = now()
                WHERE id = :ride_id AND status = 'matching'
                RETURNING rider_id
            '''), {'ride_id': result.ride_id}).first()
            if ride:
                _event(connection, result.ride_id, 'no_drivers_found')
                _notify(connection, ride.rider_id, 'ride_update', 'No drivers found',
                        'Try requesting again in a moment.',
                        {'ride_id': str(result.ride_id)})
    return jsonify({'success': True})


def _valid_uuid(value, label):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f'Invalid {label}')


@ride_bp.get('/api/rides')
@_role_required('rider', 'driver', 'admin', 'support')
def list_rides():
    role = session['ride_role']
    user_id = session['ride_user_id']
    filters = ''
    params = {}
    if role == 'rider':
        filters = 'WHERE r.rider_id = :user_id'
        params['user_id'] = user_id
    elif role == 'driver':
        filters = 'WHERE r.driver_id = :user_id'
        params['user_id'] = user_id
    with db.engine.begin() as connection:
        _expire_ride_offers(connection)
        rows = connection.execute(text(f'''
            SELECT r.id::text AS id, r.status, r.pickup_address, r.dropoff_address,
                   r.est_distance_m, r.est_duration_s, r.est_fare, r.final_fare,
                   r.requested_at, r.assigned_at, r.started_at, r.completed_at,
                   rider.full_name AS rider_name, driver.full_name AS driver_name
            FROM ride_hailing.rides r
            JOIN ride_hailing.users rider ON rider.id = r.rider_id
            LEFT JOIN ride_hailing.users driver ON driver.id = r.driver_id
            {filters}
            ORDER BY r.requested_at DESC
            LIMIT 100
        '''), params).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.get('/api/rides/<ride_id>')
@_role_required('rider', 'driver', 'admin', 'support')
def get_ride(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    role = session['ride_role']
    user_id = session['ride_user_id']
    with db.engine.connect() as connection:
        ride = connection.execute(text('''
            SELECT r.id::text AS id, r.rider_id::text AS rider_id,
                   r.driver_id::text AS driver_id, r.status,
                   r.pickup_address, r.dropoff_address,
                   ST_Y(r.pickup_location::geometry) AS pickup_latitude,
                   ST_X(r.pickup_location::geometry) AS pickup_longitude,
                   ST_Y(r.dropoff_location::geometry) AS dropoff_latitude,
                   ST_X(r.dropoff_location::geometry) AS dropoff_longitude,
                   r.est_distance_m, r.est_duration_s, r.est_fare, r.final_fare,
                   r.rider_notes, r.verification_code, r.requested_at, r.assigned_at,
                   r.arrived_at, r.started_at, r.completed_at, r.cancel_reason,
                   rider.full_name AS rider_name, rider.phone_e164 AS rider_phone,
                   driver.full_name AS driver_name, driver.phone_e164 AS driver_phone,
                   ST_Y(loc.location::geometry) AS driver_latitude,
                   ST_X(loc.location::geometry) AS driver_longitude,
                   loc.updated_at AS driver_location_updated_at
            FROM ride_hailing.rides r
            JOIN ride_hailing.users rider ON rider.id = r.rider_id
            LEFT JOIN ride_hailing.users driver ON driver.id = r.driver_id
            LEFT JOIN ride_hailing.driver_locations_live loc ON loc.driver_id = r.driver_id
            WHERE r.id = :ride_id
        '''), {'ride_id': ride_id}).mappings().first()
        if not ride:
            return jsonify({'error': 'Ride not found'}), 404
        if role not in ('admin', 'support') and user_id not in (ride['rider_id'], ride['driver_id']):
            return jsonify({'error': 'Ride not found'}), 404
        events = connection.execute(text('''
            SELECT event_type, payload, created_at
            FROM ride_hailing.ride_events
            WHERE ride_id = :ride_id ORDER BY created_at
        '''), {'ride_id': ride_id}).mappings().all()
    result = dict(ride)
    if (role != 'rider' or user_id != ride['rider_id']
            or ride['status'] in (
                'completed', 'cancelled_by_rider', 'cancelled_by_driver',
                'no_drivers_found', 'expired'
            )):
        result.pop('verification_code', None)
    result['events'] = [dict(event) for event in events]
    return jsonify(result)


@ride_bp.post('/api/rides/<ride_id>/arrive')
@_role_required('driver')
def mark_driver_arrived(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    driver_id = session['ride_user_id']
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            UPDATE ride_hailing.rides
            SET status = 'driver_arrived'::ride_hailing.ride_status,
                arrived_at = now(), updated_at = now()
            WHERE id = :ride_id AND driver_id = :driver_id
              AND status = 'driver_assigned'::ride_hailing.ride_status
              AND EXISTS (
                  SELECT 1 FROM ride_hailing.driver_locations_live l
                  WHERE l.driver_id = :driver_id
                    AND l.updated_at > now() - interval '60 seconds'
                    AND ST_DWithin(l.location, pickup_location, 250)
              )
            RETURNING rider_id
        '''), {'ride_id': ride_id, 'driver_id': driver_id}).first()
        if not ride:
            return jsonify({'error': 'Ride is not assigned to you, or your fresh GPS location is not near pickup'}), 409
        connection.execute(text('''
            INSERT INTO ride_hailing.geofence_events (ride_id, user_id, event_type, location)
            SELECT :ride_id, :driver_id, 'pickup_arrived', location
            FROM ride_hailing.driver_locations_live WHERE driver_id = :driver_id
        '''), {'ride_id': ride_id, 'driver_id': driver_id})
        _event(connection, ride_id, 'driver_arrived', driver_id)
        _notify(connection, ride.rider_id, 'ride_update', 'Your driver has arrived',
                'Meet your driver at the pickup point.', {'ride_id': ride_id})
    return jsonify({'success': True, 'status': 'driver_arrived'})


@ride_bp.post('/api/rides/<ride_id>/start')
@_role_required('driver')
def start_ride(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    verification_code = str(_json_body().get('verification_code', ''))
    if not re.fullmatch(r'\d{4}', verification_code):
        return jsonify({'error': 'Enter the four-digit rider verification code'}), 400
    driver_id = session['ride_user_id']
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            SELECT rider_id, verification_code
            FROM ride_hailing.rides
            WHERE id = :ride_id AND driver_id = :driver_id
              AND status = 'driver_arrived'::ride_hailing.ride_status
            FOR UPDATE
        '''), {'ride_id': ride_id, 'driver_id': driver_id}).mappings().first()
        if not ride:
            return jsonify({'error': 'Ride is not ready to start'}), 409
        if not hmac.compare_digest(ride['verification_code'], verification_code):
            return jsonify({'error': 'Verification code does not match'}), 400
        connection.execute(text('''
            UPDATE ride_hailing.rides
            SET status = 'in_progress'::ride_hailing.ride_status,
                started_at = now(), updated_at = now()
            WHERE id = :ride_id
        '''), {'ride_id': ride_id})
        _event(connection, ride_id, 'ride_started', driver_id)
        _notify(connection, ride['rider_id'], 'ride_update', 'Ride started',
                'Your trip is now in progress.', {'ride_id': ride_id})
    return jsonify({'success': True, 'status': 'in_progress'})


@ride_bp.post('/api/rides/<ride_id>/complete')
@_role_required('driver')
def complete_ride(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    driver_id = session['ride_user_id']
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            SELECT r.rider_id, r.vehicle_id, r.started_at,
                   r.pickup_location, r.dropoff_location,
                   r.est_fare, r.est_distance_m, r.est_duration_s,
                   vt.base_fare, vt.per_km, vt.per_minute, vt.min_fare,
                   ST_Distance(l.location, r.dropoff_location) AS distance_to_dropoff_m,
                   l.updated_at > now() - interval '60 seconds' AS location_fresh
            FROM ride_hailing.rides r
            JOIN ride_hailing.vehicle_types vt ON vt.id = r.vehicle_type_id
            LEFT JOIN ride_hailing.driver_locations_live l ON l.driver_id = r.driver_id
            WHERE r.id = :ride_id AND r.driver_id = :driver_id
              AND r.status = 'in_progress'::ride_hailing.ride_status
            FOR UPDATE OF r
        '''), {'ride_id': ride_id, 'driver_id': driver_id}).mappings().first()
        if not ride:
            return jsonify({'error': 'Ride is not in progress or is not assigned to you'}), 409
        if (not ride['location_fresh'] or ride['distance_to_dropoff_m'] is None
                or ride['distance_to_dropoff_m'] > 500):
            return jsonify({'error': 'Share a fresh GPS location near the destination before completing'}), 409
        totals = connection.execute(text('''
            SELECT
                GREATEST(
                    COALESCE((
                        SELECT ST_Length(
                            ST_MakeLine(location::geometry ORDER BY recorded_at)::geography
                        )::integer
                        FROM ride_hailing.trip_points
                        WHERE ride_id = :ride_id AND recorded_at >= :started_at
                    ), 0),
                    ST_Distance(:pickup, :dropoff)::integer
                ) AS distance_m,
                GREATEST(0, CEIL(EXTRACT(EPOCH FROM (now() - :started_at))))::integer
                    AS duration_s
        '''), {
            'ride_id': ride_id, 'started_at': ride['started_at'],
            'pickup': ride['pickup_location'], 'dropoff': ride['dropoff_location']
        }).mappings().one()
        base_estimate = max(
            float(ride['min_fare']),
            float(ride['base_fare'])
            + (ride['est_distance_m'] or 0) / 1000 * float(ride['per_km'])
            + (ride['est_duration_s'] or 0) / 60 * float(ride['per_minute'])
        )
        multiplier = float(ride['est_fare']) / base_estimate if base_estimate else 1
        fare = max(
            float(ride['min_fare']),
            float(ride['base_fare'])
            + totals['distance_m'] / 1000 * float(ride['per_km'])
            + totals['duration_s'] / 60 * float(ride['per_minute'])
        ) * multiplier
        updated = connection.execute(text('''
            UPDATE ride_hailing.rides
            SET status = 'completed'::ride_hailing.ride_status,
                actual_distance_m = :distance_m,
                actual_duration_s = :duration_s,
                final_fare = :final_fare,
                completed_at = now(), updated_at = now()
            WHERE id = :ride_id
            RETURNING rider_id
        '''), {
            'ride_id': ride_id, 'distance_m': totals['distance_m'],
            'duration_s': totals['duration_s'], 'final_fare': fare
        }).mappings().one()
        connection.execute(text('''
            UPDATE ride_hailing.driver_profiles
            SET availability = CASE
                    WHEN verification_status = 'approved'
                     AND EXISTS (
                         SELECT 1 FROM ride_hailing.vehicles v
                         WHERE v.id = current_vehicle_id
                           AND v.verification_status = 'approved'
                           AND v.active
                           AND (v.insurance_expires IS NULL OR v.insurance_expires >= current_date)
                           AND (v.inspection_expires IS NULL OR v.inspection_expires >= current_date)
                     )
                    THEN 'online'::ride_hailing.driver_availability
                    ELSE 'offline'::ride_hailing.driver_availability
                END,
                total_trips = total_trips + 1
            WHERE user_id = :driver_id
            RETURNING availability
        '''), {'driver_id': driver_id}).scalar_one()
        if availability == 'offline':
            connection.execute(text('''
                UPDATE ride_hailing.driver_sessions
                SET went_offline = now()
                WHERE driver_id = :driver_id AND went_offline IS NULL
            '''), {'driver_id': driver_id})
        connection.execute(text('''
            UPDATE ride_hailing.rider_profiles
            SET total_trips = total_trips + 1
            WHERE user_id = :rider_id
        '''), {'rider_id': updated['rider_id']})
        _event(connection, ride_id, 'ride_completed', driver_id, {
            'distance_m': totals['distance_m'], 'duration_s': totals['duration_s'],
            'final_fare': fare
        })
        _notify(connection, updated['rider_id'], 'ride_update', 'Ride completed',
                'Your trip is complete. You can now rate your driver.',
                {'ride_id': ride_id})
    return jsonify({
        'success': True, 'status': 'completed',
        'actual_distance_m': totals['distance_m'],
        'actual_duration_s': totals['duration_s'],
        'final_fare': fare
    })


@ride_bp.post('/api/rides/<ride_id>/cancel')
@_role_required('rider', 'driver')
def cancel_ride(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    user_id = session['ride_user_id']
    role = session['ride_role']
    reason = str(_json_body().get('reason', '')).strip()[:300] or None
    status = 'cancelled_by_rider' if role == 'rider' else 'cancelled_by_driver'
    ownership = 'rider_id' if role == 'rider' else 'driver_id'
    with db.engine.begin() as connection:
        ride = connection.execute(text(f'''
            UPDATE ride_hailing.rides
            SET status = CAST(:status AS ride_hailing.ride_status),
                cancelled_at = now(), cancel_reason = :reason, updated_at = now()
            WHERE id = :ride_id AND {ownership} = :user_id
              AND status IN (
                  'requested'::ride_hailing.ride_status,
                  'matching'::ride_hailing.ride_status,
                  'driver_assigned'::ride_hailing.ride_status,
                  'driver_arrived'::ride_hailing.ride_status
              )
            RETURNING rider_id, driver_id
        '''), {
            'status': status, 'reason': reason,
            'ride_id': ride_id, 'user_id': user_id
        }).mappings().first()
        if not ride:
            return jsonify({'error': 'Ride not found or can no longer be cancelled'}), 409
        connection.execute(text('''
            UPDATE ride_hailing.ride_offers
            SET status = 'cancelled', responded_at = now()
            WHERE ride_id = :ride_id AND status = 'sent'
        '''), {'ride_id': ride_id})
        if ride['driver_id']:
            connection.execute(text('''
                UPDATE ride_hailing.driver_profiles
                SET availability = CASE
                        WHEN verification_status = 'approved'
                         AND EXISTS (
                             SELECT 1 FROM ride_hailing.vehicles v
                             WHERE v.id = current_vehicle_id
                               AND v.verification_status = 'approved'
                               AND v.active
                               AND (v.insurance_expires IS NULL OR v.insurance_expires >= current_date)
                               AND (v.inspection_expires IS NULL OR v.inspection_expires >= current_date)
                         )
                        THEN 'online'::ride_hailing.driver_availability
                        ELSE 'offline'::ride_hailing.driver_availability
                    END
                WHERE user_id = :driver_id
                RETURNING availability
            '''), {'driver_id': ride['driver_id']}).scalar_one()
            if availability == 'offline':
                connection.execute(text('''
                    UPDATE ride_hailing.driver_sessions
                    SET went_offline = now()
                    WHERE driver_id = :driver_id AND went_offline IS NULL
                '''), {'driver_id': ride['driver_id']})
            _notify(connection, ride['driver_id'], 'ride_update', 'Ride cancelled',
                    'The ride was cancelled.', {'ride_id': ride_id})
        if role == 'driver':
            _notify(connection, ride['rider_id'], 'ride_update', 'Ride cancelled',
                    'The driver cancelled the ride.', {'ride_id': ride_id})
        _event(connection, ride_id, status, user_id, {'reason': reason})
    return jsonify({'success': True, 'status': status})


@ride_bp.get('/api/rides/emergency-contacts')
@_role_required('rider', 'driver')
def list_emergency_contacts():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id::text AS id, name, phone_e164, relationship, created_at
            FROM ride_hailing.emergency_contacts
            WHERE user_id = :user_id ORDER BY created_at
        '''), {'user_id': session['ride_user_id']}).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/emergency-contacts')
@_role_required('rider', 'driver')
def add_emergency_contact():
    data = _json_body()
    name = str(data.get('name', '')).strip()
    phone = str(data.get('phone_e164', '')).strip()
    relationship = str(data.get('relationship', '')).strip()[:80] or None
    if not name or len(name) > 160 or not re.fullmatch(r'\+[1-9]\d{7,14}', phone):
        return jsonify({'error': 'Provide a name and a valid E.164 phone number'}), 400
    with db.engine.begin() as connection:
        row = connection.execute(text('''
            INSERT INTO ride_hailing.emergency_contacts
                (user_id, name, phone_e164, relationship)
            VALUES (:user_id, :name, :phone, :relationship)
            RETURNING id::text AS id, name, phone_e164, relationship, created_at
        '''), {
            'user_id': session['ride_user_id'], 'name': name,
            'phone': phone, 'relationship': relationship
        }).mappings().one()
    return jsonify(dict(row)), 201


@ride_bp.delete('/api/rides/emergency-contacts/<contact_id>')
@_role_required('rider', 'driver')
def delete_emergency_contact(contact_id):
    try:
        contact_id = _valid_uuid(contact_id, 'contact id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    with db.engine.begin() as connection:
        result = connection.execute(text('''
            DELETE FROM ride_hailing.emergency_contacts
            WHERE id = :contact_id AND user_id = :user_id
        '''), {'contact_id': contact_id, 'user_id': session['ride_user_id']})
    if result.rowcount == 0:
        return jsonify({'error': 'Emergency contact not found'}), 404
    return jsonify({'success': True})


@ride_bp.post('/api/rides/<ride_id>/shares')
@_role_required('rider', 'driver')
def create_trip_share(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    try:
        expires_in = int(_json_body().get('expires_in', 3600))
    except (TypeError, ValueError):
        return jsonify({'error': 'Share duration must be a whole number of seconds'}), 400
    if not 300 <= expires_in <= 86400:
        return jsonify({'error': 'Share duration must be between 5 minutes and 24 hours'}), 400
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    user_id = session['ride_user_id']
    role = session['ride_role']
    ownership = 'rider_id' if role == 'rider' else 'driver_id'
    with db.engine.begin() as connection:
        ride = connection.execute(text(f'''
            SELECT status FROM ride_hailing.rides
            WHERE id = :ride_id AND {ownership} = :user_id
              AND status IN (
                  'driver_assigned'::ride_hailing.ride_status,
                  'driver_arrived'::ride_hailing.ride_status,
                  'in_progress'::ride_hailing.ride_status
              )
        '''), {'ride_id': ride_id, 'user_id': user_id}).mappings().first()
        if not ride:
            return jsonify({'error': 'Only an active assigned ride can be shared'}), 409
        share_id = connection.execute(text('''
            INSERT INTO ride_hailing.trip_shares (ride_id, token_hash, expires_at)
            VALUES (:ride_id, :token_hash, now() + (:expires_in * interval '1 second'))
            RETURNING id::text
        '''), {
            'ride_id': ride_id, 'token_hash': token_hash, 'expires_in': expires_in
        }).scalar_one()
    return jsonify({
        'share_id': share_id, 'token': token,
        'url': request.url_root.rstrip('/') + '/api/rides/shared/' + token
    }), 201


@ride_bp.get('/api/rides/shared/<token>')
def get_shared_trip(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,60}', token):
        return jsonify({'error': 'Share link is invalid or expired'}), 404
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with db.engine.connect() as connection:
        ride = connection.execute(text('''
            SELECT r.id::text AS ride_id, r.status, r.pickup_address, r.dropoff_address,
                   ST_Y(r.pickup_location::geometry) AS pickup_latitude,
                   ST_X(r.pickup_location::geometry) AS pickup_longitude,
                   ST_Y(r.dropoff_location::geometry) AS dropoff_latitude,
                   ST_X(r.dropoff_location::geometry) AS dropoff_longitude,
                   ST_Y(loc.location::geometry) AS driver_latitude,
                   ST_X(loc.location::geometry) AS driver_longitude,
                   loc.updated_at AS driver_location_updated_at
            FROM ride_hailing.trip_shares s
            JOIN ride_hailing.rides r ON r.id = s.ride_id
            LEFT JOIN ride_hailing.driver_locations_live loc ON loc.driver_id = r.driver_id
            WHERE s.token_hash = :token_hash AND s.expires_at > now()
              AND r.status IN (
                  'driver_assigned'::ride_hailing.ride_status,
                  'driver_arrived'::ride_hailing.ride_status,
                  'in_progress'::ride_hailing.ride_status
              )
        '''), {'token_hash': token_hash}).mappings().first()
    if not ride:
        return jsonify({'error': 'Share link is invalid or expired'}), 404
    return jsonify(dict(ride))


@ride_bp.delete('/api/rides/<ride_id>/shares/<share_id>')
@_role_required('rider', 'driver')
def revoke_trip_share(ride_id, share_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
        share_id = _valid_uuid(share_id, 'share id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    role = session['ride_role']
    ownership = 'rider_id' if role == 'rider' else 'driver_id'
    with db.engine.begin() as connection:
        result = connection.execute(text(f'''
            DELETE FROM ride_hailing.trip_shares s
            USING ride_hailing.rides r
            WHERE s.id = :share_id AND s.ride_id = r.id AND r.id = :ride_id
              AND r.{ownership} = :user_id
        '''), {
            'share_id': share_id, 'ride_id': ride_id,
            'user_id': session['ride_user_id']
        })
    if result.rowcount == 0:
        return jsonify({'error': 'Trip share not found'}), 404
    return jsonify({'success': True})


@ride_bp.post('/api/rides/<ride_id>/ratings')
@_role_required('rider', 'driver')
def rate_ride(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    try:
        stars = int(data.get('stars'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Stars must be an integer from 1 to 5'}), 400
    tags = data.get('tags', [])
    comment = str(data.get('comment', '')).strip()[:1000] or None
    if not 1 <= stars <= 5 or not isinstance(tags, list) or len(tags) > 5:
        return jsonify({'error': 'Provide 1 to 5 stars and at most five tags'}), 400
    if any(not isinstance(tag, str) or not tag.strip() or len(tag) > 40 for tag in tags):
        return jsonify({'error': 'Each rating tag must be a non-empty string of at most 40 characters'}), 400
    user_id = session['ride_user_id']
    role = session['ride_role']
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            SELECT rider_id, driver_id, status FROM ride_hailing.rides
            WHERE id = :ride_id AND status = 'completed'::ride_hailing.ride_status
        '''), {'ride_id': ride_id}).mappings().first()
        if (not ride or not ride['driver_id']
                or user_id not in (ride['rider_id'], ride['driver_id'])):
            return jsonify({'error': 'Only ride participants can rate a completed ride'}), 409
        expected_to = ride['driver_id'] if role == 'rider' else ride['rider_id']
        if user_id != (ride['rider_id'] if role == 'rider' else ride['driver_id']):
            return jsonify({'error': 'Ride participant role does not match your account'}), 403
        row = connection.execute(text('''
            INSERT INTO ride_hailing.ratings (ride_id, from_user, to_user, stars, tags, comment)
            VALUES (:ride_id, :from_user, :to_user, :stars, :tags, :comment)
            ON CONFLICT (ride_id, from_user) DO NOTHING
            RETURNING id::text AS id
        '''), {
            'ride_id': ride_id, 'from_user': user_id, 'to_user': expected_to,
            'stars': stars, 'tags': tags, 'comment': comment
        }).mappings().first()
        if not row:
            return jsonify({'error': 'You have already rated this ride'}), 409
        profile_table = 'driver_profiles' if role == 'rider' else 'rider_profiles'
        connection.execute(text(f'''
            UPDATE ride_hailing.{profile_table}
            SET rating_avg = ROUND((rating_avg * rating_count + :stars)::numeric
                                   / (rating_count + 1), 2),
                rating_count = rating_count + 1
            WHERE user_id = :to_user
        '''), {'stars': stars, 'to_user': expected_to})
    return jsonify({'success': True, 'rating_id': row['id']}), 201


@ride_bp.post('/api/rides/<ride_id>/sos')
@_role_required('rider', 'driver')
def trigger_sos(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    user_id = session['ride_user_id']
    data = _json_body()
    coords = None
    if data.get('latitude') is not None or data.get('longitude') is not None:
        try:
            latitude = float(data['latitude'])
            longitude = float(data['longitude'])
        except ValueError:
            return jsonify({'error': 'Provide both valid latitude and longitude'}), 400
        except (KeyError, TypeError):
            return jsonify({'error': 'Provide both valid latitude and longitude'}), 400
        if (not math.isfinite(latitude) or not math.isfinite(longitude)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            return jsonify({'error': 'Coordinates are outside the valid range'}), 400
        coords = latitude, longitude
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            SELECT rider_id, driver_id FROM ride_hailing.rides
            WHERE id = :ride_id AND status IN (
                'driver_assigned'::ride_hailing.ride_status,
                'driver_arrived'::ride_hailing.ride_status,
                'in_progress'::ride_hailing.ride_status
            )
        '''), {'ride_id': ride_id}).mappings().first()
        if not ride or user_id not in (ride['rider_id'], ride['driver_id']):
            return jsonify({'error': 'SOS is only available to participants in an active ride'}), 409
        location_sql = '''
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
        ''' if coords else '''
            (SELECT location FROM ride_hailing.driver_locations_live
             WHERE driver_id = :driver_id)
        '''
        params = {
            'ride_id': ride_id, 'user_id': user_id, 'driver_id': ride['driver_id'],
            'longitude': coords[1] if coords else None,
            'latitude': coords[0] if coords else None
        }
        event_id = connection.execute(text(f'''
            INSERT INTO ride_hailing.sos_events (ride_id, triggered_by, location)
            VALUES (:ride_id, :user_id, {location_sql})
            RETURNING id::text
        '''), params).scalar_one()
        _event(connection, ride_id, 'sos_triggered', user_id, {'sos_id': event_id})
        admins = connection.execute(text('''
            SELECT id FROM ride_hailing.users
            WHERE role IN ('admin'::ride_hailing.user_role, 'support'::ride_hailing.user_role)
              AND status = 'active'::ride_hailing.account_status
        ''')).all()
        for admin in admins:
            _notify(connection, admin.id, 'sos_alert', 'Ride SOS alert',
                    'A rider or driver triggered an SOS alert.',
                    {'ride_id': ride_id, 'sos_id': event_id})
    return jsonify({'success': True, 'sos_id': event_id}), 201


@ride_bp.post('/api/rides/<ride_id>/incidents')
@_role_required('rider', 'driver')
def report_ride_incident(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    category = str(data.get('category', '')).strip()[:80]
    description = str(data.get('description', '')).strip()[:5000] or None
    evidence_keys = data.get('evidence_keys', [])
    if not category or not isinstance(evidence_keys, list) or len(evidence_keys) > 5:
        return jsonify({'error': 'Provide a category and at most five evidence keys'}), 400
    if any(not isinstance(key, str) or not key.strip() or len(key) > 300 for key in evidence_keys):
        return jsonify({'error': 'Evidence keys must be non-empty private storage keys'}), 400
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            SELECT rider_id, driver_id FROM ride_hailing.rides WHERE id = :ride_id
        '''), {'ride_id': ride_id}).mappings().first()
        user_id = session['ride_user_id']
        if not ride or user_id not in (ride['rider_id'], ride['driver_id']):
            return jsonify({'error': 'Only ride participants can report an incident'}), 404
        reported_id = ride['driver_id'] if user_id == ride['rider_id'] else ride['rider_id']
        incident_id = connection.execute(text('''
            INSERT INTO ride_hailing.incident_reports
                (ride_id, reporter_id, reported_id, category, description, evidence_keys)
            VALUES (:ride_id, :reporter_id, :reported_id, :category, :description, :evidence_keys)
            RETURNING id::text
        '''), {
            'ride_id': ride_id, 'reporter_id': user_id, 'reported_id': reported_id,
            'category': category, 'description': description, 'evidence_keys': evidence_keys
        }).scalar_one()
        _event(connection, ride_id, 'incident_reported', user_id, {'incident_id': incident_id})
    return jsonify({'success': True, 'incident_id': incident_id}), 201


@ride_bp.post('/api/rides/<ride_id>/blocks')
@_role_required('rider', 'driver')
def block_ride_participant(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    user_id = session['ride_user_id']
    with db.engine.begin() as connection:
        ride = connection.execute(text('''
            SELECT rider_id, driver_id FROM ride_hailing.rides WHERE id = :ride_id
        '''), {'ride_id': ride_id}).mappings().first()
        if not ride or user_id not in (ride['rider_id'], ride['driver_id']):
            return jsonify({'error': 'Only ride participants can block one another'}), 404
        blocked_id = ride['driver_id'] if user_id == ride['rider_id'] else ride['rider_id']
        if not blocked_id:
            return jsonify({'error': 'There is no other ride participant to block'}), 409
        connection.execute(text('''
            INSERT INTO ride_hailing.user_blocks (blocker_id, blocked_id)
            VALUES (:blocker_id, :blocked_id)
            ON CONFLICT DO NOTHING
        '''), {'blocker_id': user_id, 'blocked_id': blocked_id})
    return jsonify({'success': True})


@ride_bp.get('/api/rides/blocks')
@_role_required('rider', 'driver')
def list_blocked_users():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT b.blocked_id::text AS user_id, u.full_name, b.created_at
            FROM ride_hailing.user_blocks b
            JOIN ride_hailing.users u ON u.id = b.blocked_id
            WHERE b.blocker_id = :user_id ORDER BY b.created_at DESC
        '''), {'user_id': session['ride_user_id']}).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.delete('/api/rides/blocks/<blocked_user_id>')
@_role_required('rider', 'driver')
def unblock_user(blocked_user_id):
    try:
        blocked_user_id = _valid_uuid(blocked_user_id, 'user id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    with db.engine.begin() as connection:
        result = connection.execute(text('''
            DELETE FROM ride_hailing.user_blocks
            WHERE blocker_id = :blocker_id AND blocked_id = :blocked_id
        '''), {'blocker_id': session['ride_user_id'], 'blocked_id': blocked_user_id})
    if result.rowcount == 0:
        return jsonify({'error': 'Blocked user not found'}), 404
    return jsonify({'success': True})


@ride_bp.get('/api/rides/notifications')
@_role_required('rider', 'driver', 'admin', 'support')
def list_ride_notifications():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id::text AS id, kind, title, body, data, read_at, created_at
            FROM ride_hailing.notifications
            WHERE user_id = :user_id
            ORDER BY created_at DESC LIMIT 100
        '''), {'user_id': session['ride_user_id']}).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/notifications/read')
@_role_required('rider', 'driver', 'admin', 'support')
def mark_notifications_read():
    data = _json_body()
    notification_ids = data.get('ids')
    if notification_ids is not None:
        if not isinstance(notification_ids, list) or not notification_ids or len(notification_ids) > 100:
            return jsonify({'error': 'Provide between 1 and 100 notification ids'}), 400
        try:
            notification_ids = [_valid_uuid(value, 'notification id') for value in notification_ids]
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    with db.engine.begin() as connection:
        if notification_ids is None:
            connection.execute(text('''
                UPDATE ride_hailing.notifications SET read_at = now()
                WHERE user_id = :user_id AND read_at IS NULL
            '''), {'user_id': session['ride_user_id']})
        else:
            connection.execute(text('''
                UPDATE ride_hailing.notifications SET read_at = now()
                WHERE user_id = :user_id AND id = ANY(:notification_ids)
            '''), {
                'user_id': session['ride_user_id'],
                'notification_ids': notification_ids
            })
    return jsonify({'success': True})


@ride_bp.get('/api/rides/admin/dashboard')
@_role_required('admin', 'support')
def ride_admin_dashboard():
    with db.engine.connect() as connection:
        counts = connection.execute(text('''
            SELECT
                (SELECT count(*) FROM ride_hailing.rides
                 WHERE status IN ('requested','matching','driver_assigned','driver_arrived','in_progress')) AS active_rides,
                (SELECT count(*) FROM ride_hailing.driver_profiles
                 WHERE verification_status = 'pending') AS pending_drivers,
                (SELECT count(*) FROM ride_hailing.driver_documents
                 WHERE status = 'pending') AS pending_documents,
                (SELECT count(*) FROM ride_hailing.support_tickets
                 WHERE status IN ('open','in_progress')) AS open_tickets,
                (SELECT count(*) FROM ride_hailing.sos_events
                 WHERE status IN ('triggered','acknowledged')) AS open_sos
        ''')).mappings().one()
        recent = connection.execute(text('''
            SELECT r.id::text AS id, r.status, r.requested_at,
                   rider.full_name AS rider_name, driver.full_name AS driver_name,
                   r.pickup_address, r.dropoff_address
            FROM ride_hailing.rides r
            JOIN ride_hailing.users rider ON rider.id = r.rider_id
            LEFT JOIN ride_hailing.users driver ON driver.id = r.driver_id
            ORDER BY r.requested_at DESC LIMIT 20
        ''')).mappings().all()
    return jsonify({'counts': dict(counts), 'recent_rides': [dict(row) for row in recent]})


@ride_bp.get('/api/rides/admin/drivers')
@_role_required('admin', 'support')
def list_drivers_for_review():
    document_storage_column = 'storage_key,' if session['ride_role'] == 'admin' else ''
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT u.id::text AS id, u.full_name, u.phone_e164, u.email, u.created_at,
                   d.verification_status, d.rejection_reason, d.date_of_birth,
                   d.home_address, d.current_vehicle_id::text AS current_vehicle_id,
                   v.plate_number, v.make, v.model, v.year, v.color,
                   v.verification_status AS vehicle_status
            FROM ride_hailing.driver_profiles d
            JOIN ride_hailing.users u ON u.id = d.user_id
            LEFT JOIN ride_hailing.vehicles v ON v.id = d.current_vehicle_id
            ORDER BY CASE d.verification_status
                WHEN 'pending' THEN 0 WHEN 'in_review' THEN 1 ELSE 2 END,
                d.created_at DESC
            LIMIT 200
        ''')).mappings().all()
        docs = connection.execute(text(f'''
            SELECT id::text AS id, driver_id::text AS driver_id, doc_type,
                   {document_storage_column}
                   file_sha256, status, expires_at, uploaded_at,
                   reject_reason
            FROM ride_hailing.driver_documents
            WHERE status IN ('pending','in_review')
            ORDER BY uploaded_at DESC LIMIT 300
        ''')).mappings().all()
    return jsonify({
        'drivers': [dict(row) for row in rows],
        'documents': [dict(row) for row in docs]
    })


@ride_bp.post('/api/rides/admin/drivers/<driver_id>/review')
@_role_required('admin')
def review_driver(driver_id):
    try:
        driver_id = _valid_uuid(driver_id, 'driver id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    decision = data.get('decision')
    reason = str(data.get('reason', '')).strip()[:1000] or None
    if decision not in ('approved', 'rejected'):
        return jsonify({'error': 'Decision must be approved or rejected'}), 400
    if decision == 'rejected' and not reason:
        return jsonify({'error': 'Provide a reason when rejecting a driver'}), 400
    with db.engine.begin() as connection:
        profile = connection.execute(text('''
            SELECT verification_status, availability FROM ride_hailing.driver_profiles
            WHERE user_id = :driver_id FOR UPDATE
        '''), {'driver_id': driver_id}).mappings().first()
        if not profile:
            return jsonify({'error': 'Driver not found'}), 404
        before = profile['verification_status']
        connection.execute(text('''
            UPDATE ride_hailing.driver_profiles
            SET verification_status = CAST(:decision AS ride_hailing.verification_status),
                verified_at = CASE WHEN :decision = 'approved' THEN now() ELSE NULL END,
                rejection_reason = :reason,
                availability = CASE WHEN :decision = 'rejected'
                    AND availability <> 'on_trip'::ride_hailing.driver_availability
                    THEN 'offline'::ride_hailing.driver_availability ELSE availability END
            WHERE user_id = :driver_id
        '''), {'driver_id': driver_id, 'decision': decision, 'reason': reason})
        connection.execute(text('''
            INSERT INTO ride_hailing.driver_status_history
                (driver_id, old_status, new_status, changed_by, note)
            VALUES (
                :driver_id, CAST(:old_status AS ride_hailing.verification_status),
                CAST(:new_status AS ride_hailing.verification_status),
                :changed_by, :note
            )
        '''), {
            'driver_id': driver_id, 'old_status': before, 'new_status': decision,
            'changed_by': session['ride_user_id'], 'note': reason
        })
        if decision == 'rejected' and profile['availability'] != 'on_trip':
            connection.execute(text('''
                UPDATE ride_hailing.driver_sessions
                SET went_offline = now()
                WHERE driver_id = :driver_id AND went_offline IS NULL
            '''), {'driver_id': driver_id})
        _audit(connection, session['ride_user_id'], 'driver_reviewed', 'driver',
               driver_id, {'verification_status': before},
               {'verification_status': decision, 'reason': reason})
        _notify(connection, driver_id, 'verification_update',
                'Driver verification updated',
                'Your driver account has been ' + decision + '.',
                {'verification_status': decision})
    return jsonify({'success': True, 'verification_status': decision})


@ride_bp.post('/api/rides/admin/documents/<document_id>/review')
@_role_required('admin')
def review_driver_document(document_id):
    try:
        document_id = _valid_uuid(document_id, 'document id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    decision = data.get('decision')
    reason = str(data.get('reason', '')).strip()[:1000] or None
    if decision not in ('approved', 'rejected'):
        return jsonify({'error': 'Decision must be approved or rejected'}), 400
    if decision == 'rejected' and not reason:
        return jsonify({'error': 'Provide a reason when rejecting a document'}), 400
    with db.engine.begin() as connection:
        document = connection.execute(text('''
            UPDATE ride_hailing.driver_documents
            SET status = CAST(:decision AS ride_hailing.verification_status),
                reviewed_by = :reviewed_by, reviewed_at = now(), reject_reason = :reason
            WHERE id = :document_id AND status IN ('pending','in_review')
            RETURNING driver_id, doc_type
        '''), {
            'decision': decision, 'reviewed_by': session['ride_user_id'],
            'reason': reason, 'document_id': document_id
        }).mappings().first()
        if not document:
            return jsonify({'error': 'Pending document not found'}), 404
        if decision == 'rejected':
            profile = connection.execute(text('''
                SELECT verification_status, availability FROM ride_hailing.driver_profiles
                WHERE user_id = :driver_id FOR UPDATE
            '''), {'driver_id': document['driver_id']}).mappings().one()
            connection.execute(text('''
                UPDATE ride_hailing.driver_profiles
                SET verification_status = 'rejected'::ride_hailing.verification_status,
                    rejection_reason = :reason,
                availability = CASE
                    WHEN availability = 'on_trip'::ride_hailing.driver_availability
                    THEN availability
                    ELSE 'offline'::ride_hailing.driver_availability
                END
                WHERE user_id = :driver_id
            '''), {'driver_id': document['driver_id'], 'reason': reason})
            connection.execute(text('''
                INSERT INTO ride_hailing.driver_status_history
                    (driver_id, old_status, new_status, changed_by, note)
                VALUES (
                    :driver_id, CAST(:old_status AS ride_hailing.verification_status),
                    'rejected'::ride_hailing.verification_status, :changed_by, :note
                )
            '''), {
                'driver_id': document['driver_id'],
                'old_status': profile['verification_status'],
                'changed_by': session['ride_user_id'], 'note': reason
            })
            if profile['availability'] != 'on_trip':
                connection.execute(text('''
                    UPDATE ride_hailing.driver_sessions
                    SET went_offline = now()
                    WHERE driver_id = :driver_id AND went_offline IS NULL
                '''), {'driver_id': document['driver_id']})
        _audit(connection, session['ride_user_id'], 'document_reviewed', 'driver_document',
               document_id, None, {'status': decision, 'reason': reason})
        _notify(connection, document['driver_id'], 'verification_update',
                'Document review complete',
                'Your ' + str(document['doc_type']) + ' document was ' + decision + '.',
                {'document_id': document_id, 'status': decision})
    return jsonify({'success': True, 'status': decision})


@ride_bp.get('/api/rides/admin/verification-checks')
@_role_required('admin', 'support')
def list_verification_checks():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT c.id::text AS id, c.driver_id::text AS driver_id,
                   u.full_name AS driver_name, c.check_type, c.provider,
                   c.provider_ref, c.status, c.result_json, c.started_at, c.completed_at
            FROM ride_hailing.verification_checks c
            JOIN ride_hailing.users u ON u.id = c.driver_id
            WHERE c.status IN ('pending','in_review')
            ORDER BY c.started_at LIMIT 300
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/admin/drivers/<driver_id>/verification-checks')
@_role_required('admin')
def create_verification_check(driver_id):
    try:
        driver_id = _valid_uuid(driver_id, 'driver id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    check_type = data.get('check_type')
    allowed = {'identity', 'license', 'background', 'vehicle', 'insurance', 'selfie_match'}
    provider_ref = str(data.get('provider_ref', '')).strip()[:200] or None
    if check_type not in allowed:
        return jsonify({'error': 'Unsupported verification check type'}), 400
    with db.engine.begin() as connection:
        if not connection.execute(text('''
            SELECT 1 FROM ride_hailing.driver_profiles WHERE user_id = :driver_id
        '''), {'driver_id': driver_id}).first():
            return jsonify({'error': 'Driver not found'}), 404
        check_id = connection.execute(text('''
            INSERT INTO ride_hailing.verification_checks
                (driver_id, check_type, provider, provider_ref, status)
            VALUES (:driver_id, CAST(:check_type AS ride_hailing.check_type),
                    'manual', :provider_ref, 'in_review')
            RETURNING id::text
        '''), {
            'driver_id': driver_id, 'check_type': check_type,
            'provider_ref': provider_ref
        }).scalar_one()
        _audit(connection, session['ride_user_id'], 'verification_check_created',
               'verification_check', check_id, None,
               {'driver_id': driver_id, 'check_type': check_type})
    return jsonify({'success': True, 'id': check_id}), 201


@ride_bp.post('/api/rides/admin/verification-checks/<check_id>/complete')
@_role_required('admin')
def complete_verification_check(check_id):
    try:
        check_id = _valid_uuid(check_id, 'verification check id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    status = data.get('status')
    if status not in ('approved', 'rejected'):
        return jsonify({'error': 'Status must be approved or rejected'}), 400
    result = data.get('result')
    if result is not None and not isinstance(result, dict):
        return jsonify({'error': 'Result must be a JSON object'}), 400
    with db.engine.begin() as connection:
        check = connection.execute(text('''
            UPDATE ride_hailing.verification_checks
            SET status = CAST(:status AS ride_hailing.verification_status),
                result_json = CAST(:result AS jsonb), completed_at = now()
            WHERE id = :check_id AND status IN ('pending','in_review')
            RETURNING driver_id, check_type
        '''), {
            'check_id': check_id, 'status': status,
            'result': _json_value(result)
        }).mappings().first()
        if not check:
            return jsonify({'error': 'Open verification check not found'}), 404
        _audit(connection, session['ride_user_id'], 'verification_check_completed',
               'verification_check', check_id, None,
               {'status': status, 'check_type': check['check_type']})
        _notify(connection, check['driver_id'], 'verification_update',
                'Verification check complete',
                'Your ' + str(check['check_type']) + ' check was ' + status + '.',
                {'check_id': check_id, 'status': status})
    return jsonify({'success': True, 'status': status})


@ride_bp.get('/api/rides/admin/service-areas')
@_role_required('admin', 'support')
def list_service_areas():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id, name, timezone, active,
                   ST_AsGeoJSON(boundary::geometry)::json AS geometry
            FROM ride_hailing.service_areas ORDER BY name
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/admin/service-areas')
@_role_required('admin')
def create_service_area():
    data = _json_body()
    name = str(data.get('name', '')).strip()[:160]
    timezone = str(data.get('timezone', '')).strip()[:80]
    geometry = data.get('geometry')
    if (not name or not timezone or not isinstance(geometry, dict)
            or geometry.get('type') not in ('Polygon', 'MultiPolygon')):
        return jsonify({'error': 'Provide a name, timezone and Polygon or MultiPolygon GeoJSON geometry'}), 400
    geometry_json = json.dumps(geometry, separators=(',', ':'))
    if len(geometry_json) > 200000:
        return jsonify({'error': 'Service area geometry is too large'}), 413
    with db.engine.begin() as connection:
        if not connection.execute(text('''
            SELECT 1 FROM pg_timezone_names WHERE name = :timezone
        '''), {'timezone': timezone}).first():
            return jsonify({'error': 'Timezone must be a valid IANA timezone'}), 400
        validity = connection.execute(text('''
            WITH input AS (
                SELECT ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)) AS geom
            )
            SELECT ST_IsValid(geom) AS valid,
                   ST_GeometryType(geom) = 'ST_MultiPolygon' AS is_multipolygon,
                   ST_NPoints(geom) AS point_count,
                   ST_XMin(Box3D(geom)) >= -180 AND ST_XMax(Box3D(geom)) <= 180
                       AND ST_YMin(Box3D(geom)) >= -90 AND ST_YMax(Box3D(geom)) <= 90 AS in_range
            FROM input
        '''), {'geometry': geometry_json}).mappings().one()
        if (not validity['valid'] or not validity['is_multipolygon']
                or validity['point_count'] < 4 or not validity['in_range']):
            return jsonify({'error': 'Service area must be a valid polygon with at least four points'}), 400
        area_id = connection.execute(text('''
            INSERT INTO ride_hailing.service_areas (name, boundary, timezone)
            VALUES (
                :name,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))::geography,
                :timezone
            )
            RETURNING id
        '''), {'name': name, 'geometry': geometry_json, 'timezone': timezone}).scalar_one()
        _audit(connection, session['ride_user_id'], 'service_area_created',
               'service_area', area_id, None, {'name': name, 'timezone': timezone})
    return jsonify({'success': True, 'id': area_id}), 201


@ride_bp.get('/api/rides/admin/vehicle-types')
@_role_required('admin', 'support')
def list_admin_vehicle_types():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT id, code, display_name, seats, base_fare, per_km,
                   per_minute, min_fare, active
            FROM ride_hailing.vehicle_types ORDER BY id
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/admin/vehicle-types')
@_role_required('admin')
def create_vehicle_type():
    data = _json_body()
    code = str(data.get('code', '')).strip().lower()[:40]
    name = str(data.get('display_name', '')).strip()[:100]
    try:
        seats = int(data.get('seats'))
        base_fare = float(data.get('base_fare', 0))
        per_km = float(data.get('per_km', 0))
        per_minute = float(data.get('per_minute', 0))
        min_fare = float(data.get('min_fare', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'Seats and fare amounts must be valid numbers'}), 400
    amounts = (base_fare, per_km, per_minute, min_fare)
    if (not re.fullmatch(r'[a-z0-9_-]+', code) or not name or not 1 <= seats <= 99
            or any(not math.isfinite(amount) or amount < 0 for amount in amounts)):
        return jsonify({'error': 'Provide a code, name, 1-99 seats and non-negative fares'}), 400
    with db.engine.begin() as connection:
        row = connection.execute(text('''
            INSERT INTO ride_hailing.vehicle_types
                (code, display_name, seats, base_fare, per_km, per_minute, min_fare)
            VALUES (:code, :name, :seats, :base_fare, :per_km, :per_minute, :min_fare)
            RETURNING id
        '''), {
            'code': code, 'name': name, 'seats': seats, 'base_fare': base_fare,
            'per_km': per_km, 'per_minute': per_minute, 'min_fare': min_fare
        }).mappings().one()
        _audit(connection, session['ride_user_id'], 'vehicle_type_created',
               'vehicle_type', row['id'], None, {'code': code, 'display_name': name})
    return jsonify({'success': True, 'id': row['id']}), 201


@ride_bp.post('/api/rides/admin/vehicles/<vehicle_id>/review')
@_role_required('admin')
def review_vehicle(vehicle_id):
    try:
        vehicle_id = _valid_uuid(vehicle_id, 'vehicle id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    decision = data.get('decision')
    reason = str(data.get('reason', '')).strip()[:1000] or None
    if decision not in ('approved', 'rejected'):
        return jsonify({'error': 'Decision must be approved or rejected'}), 400
    if decision == 'rejected' and not reason:
        return jsonify({'error': 'Provide a reason when rejecting a vehicle'}), 400
    with db.engine.begin() as connection:
        vehicle = connection.execute(text('''
            UPDATE ride_hailing.vehicles
            SET verification_status = CAST(:decision AS ride_hailing.verification_status),
                active = (:decision = 'approved')
            WHERE id = :vehicle_id
            RETURNING owner_id, plate_number
        '''), {'vehicle_id': vehicle_id, 'decision': decision}).mappings().first()
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        if decision == 'rejected':
            profile = connection.execute(text('''
                UPDATE ride_hailing.driver_profiles
                SET availability = CASE
                        WHEN availability = 'on_trip'::ride_hailing.driver_availability
                        THEN availability
                        ELSE 'offline'::ride_hailing.driver_availability
                    END
                WHERE user_id = :driver_id
                RETURNING availability
            '''), {'driver_id': vehicle['owner_id']}).scalar_one()
            if profile != 'on_trip':
                connection.execute(text('''
                    UPDATE ride_hailing.driver_sessions
                    SET went_offline = now()
                    WHERE driver_id = :driver_id AND went_offline IS NULL
                '''), {'driver_id': vehicle['owner_id']})
        _audit(connection, session['ride_user_id'], 'vehicle_reviewed', 'vehicle',
               vehicle_id, None, {'status': decision, 'reason': reason})
        _notify(connection, vehicle['owner_id'], 'verification_update',
                'Vehicle review complete',
                'Your vehicle was ' + decision + '.',
                {'vehicle_id': vehicle_id, 'status': decision})
    return jsonify({'success': True, 'status': decision})


@ride_bp.put('/api/rides/admin/service-areas/<int:area_id>')
@_role_required('admin')
def update_service_area(area_id):
    data = _json_body()
    if not isinstance(data.get('active'), bool):
        return jsonify({'error': 'active must be true or false'}), 400
    with db.engine.begin() as connection:
        result = connection.execute(text('''
            UPDATE ride_hailing.service_areas SET active = :active
            WHERE id = :area_id RETURNING id
        '''), {'area_id': area_id, 'active': data['active']}).first()
        if not result:
            return jsonify({'error': 'Service area not found'}), 404
        _audit(connection, session['ride_user_id'], 'service_area_updated',
               'service_area', area_id, None, {'active': data['active']})
    return jsonify({'success': True, 'active': data['active']})


@ride_bp.get('/api/rides/admin/pricing-zones')
@_role_required('admin', 'support')
def list_pricing_zones():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT z.id, z.area_id, a.name AS area_name, z.name, z.multiplier,
                   z.valid_from, z.valid_to,
                   ST_AsGeoJSON(z.boundary::geometry)::json AS geometry
            FROM ride_hailing.pricing_zones z
            JOIN ride_hailing.service_areas a ON a.id = z.area_id
            ORDER BY a.name, z.name
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/admin/pricing-zones')
@_role_required('admin')
def create_pricing_zone():
    data = _json_body()
    name = str(data.get('name', '')).strip()[:160]
    geometry = data.get('geometry')
    try:
        area_id = int(data.get('area_id'))
        multiplier = float(data.get('multiplier', 1))
    except (TypeError, ValueError):
        return jsonify({'error': 'Area id and multiplier must be numbers'}), 400
    if (not name or not isinstance(geometry, dict)
            or geometry.get('type') not in ('Polygon', 'MultiPolygon')
            or not math.isfinite(multiplier) or not 1 <= multiplier <= 5):
        return jsonify({'error': 'Provide a zone name, polygon and multiplier from 1 to 5'}), 400
    geometry_json = json.dumps(geometry, separators=(',', ':'))
    if len(geometry_json) > 200000:
        return jsonify({'error': 'Pricing zone geometry is too large'}), 413
    with db.engine.begin() as connection:
        if not connection.execute(text('''
            SELECT 1 FROM ride_hailing.service_areas WHERE id = :area_id
        '''), {'area_id': area_id}).first():
            return jsonify({'error': 'Service area not found'}), 404
        validity = connection.execute(text('''
            WITH input AS (
                SELECT ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)) AS geom
            )
            SELECT ST_IsValid(geom) AS valid, ST_NPoints(geom) AS point_count,
                   ST_XMin(Box3D(geom)) >= -180 AND ST_XMax(Box3D(geom)) <= 180
                       AND ST_YMin(Box3D(geom)) >= -90 AND ST_YMax(Box3D(geom)) <= 90 AS in_range,
                   ST_Covers(a.boundary::geometry, geom) AS in_area
            FROM input CROSS JOIN ride_hailing.service_areas a
            WHERE a.id = :area_id
        '''), {'geometry': geometry_json, 'area_id': area_id}).mappings().one()
        if (not validity['valid'] or validity['point_count'] < 4
                or not validity['in_range'] or not validity['in_area']):
            return jsonify({'error': 'Pricing zone must be a valid polygon with at least four points'}), 400
        zone_id = connection.execute(text('''
            INSERT INTO ride_hailing.pricing_zones
                (area_id, name, boundary, multiplier)
            VALUES (
                :area_id, :name,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))::geography,
                :multiplier
            )
            RETURNING id
        '''), {
            'area_id': area_id, 'name': name,
            'geometry': geometry_json, 'multiplier': multiplier
        }).scalar_one()
        _audit(connection, session['ride_user_id'], 'pricing_zone_created',
               'pricing_zone', zone_id, None,
               {'area_id': area_id, 'name': name, 'multiplier': multiplier})
    return jsonify({'success': True, 'id': zone_id}), 201


@ride_bp.get('/api/rides/locations/search')
@_role_required('rider', 'driver')
def search_ride_locations():
    query = str(request.args.get('q', '')).strip()[:100]
    if len(query) < 2:
        return jsonify({'error': 'Search text must be at least two characters'}), 400
    origin = None
    if request.args.get('latitude') is not None or request.args.get('longitude') is not None:
        try:
            origin = _coordinates(request.args, '')
        except ValueError:
            return jsonify({'error': 'Provide both valid latitude and longitude'}), 400
    params = {
        'user_id': session['ride_user_id'],
        'pattern': '%' + query.replace('%', '\\%').replace('_', '\\_') + '%',
        'latitude': origin[0] if origin else None,
        'longitude': origin[1] if origin else None
    }
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            WITH origin AS (
                SELECT CASE WHEN :latitude IS NULL THEN NULL
                    ELSE ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
                END AS location
            ), matches AS (
                SELECT 'pickup_point'::text AS source, id::text AS id, name, notes AS address,
                       location FROM ride_hailing.pickup_points
                WHERE name ILIKE :pattern OR COALESCE(notes, '') ILIKE :pattern
                UNION ALL
                SELECT 'place', id::text, COALESCE(name, address), address, location
                FROM ride_hailing.places
                WHERE COALESCE(name, '') ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern
                UNION ALL
                SELECT 'saved_place', id::text, label, address, location
                FROM ride_hailing.saved_places
                WHERE user_id = :user_id AND (label ILIKE :pattern OR COALESCE(address, '') ILIKE :pattern)
            )
            SELECT m.source, m.id, m.name, m.address,
                   ST_Y(m.location::geometry) AS latitude,
                   ST_X(m.location::geometry) AS longitude,
                   CASE WHEN o.location IS NULL THEN NULL
                        ELSE ST_Distance(m.location, o.location)::integer END AS distance_m
            FROM matches m CROSS JOIN origin o
            ORDER BY distance_m NULLS LAST, m.name
            LIMIT 30
        '''), params).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.get('/api/rides/admin/pickup-points')
@_role_required('admin', 'support')
def list_pickup_points():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT p.id::text AS id, p.name, p.notes, p.area_id,
                   ST_Y(p.location::geometry) AS latitude,
                   ST_X(p.location::geometry) AS longitude
            FROM ride_hailing.pickup_points p ORDER BY p.name
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/admin/pickup-points')
@_role_required('admin')
def create_pickup_point():
    data = _json_body()
    name = str(data.get('name', '')).strip()[:160]
    notes = str(data.get('notes', '')).strip()[:500] or None
    area_id = data.get('area_id')
    try:
        latitude, longitude = _coordinates(data, '')
        area_id = int(area_id) if area_id not in (None, '') else None
    except (ValueError, TypeError):
        return jsonify({'error': 'Provide a name, valid coordinates and optional service area id'}), 400
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    with db.engine.begin() as connection:
        if area_id is not None:
            served = connection.execute(text('''
                SELECT ST_Covers(
                    boundary::geometry,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
                ) AS contains_point
                FROM ride_hailing.service_areas WHERE id = :area_id
            '''), {
                'area_id': area_id, 'longitude': longitude, 'latitude': latitude
            }).first()
            if not served:
                return jsonify({'error': 'Service area not found'}), 404
            if not served.contains_point:
                return jsonify({'error': 'Pickup point must be inside its service area'}), 400
        point_id = connection.execute(text('''
            INSERT INTO ride_hailing.pickup_points (name, location, area_id, notes)
            VALUES (
                :name,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                :area_id, :notes
            )
            RETURNING id::text
        '''), {
            'name': name, 'longitude': longitude, 'latitude': latitude,
            'area_id': area_id, 'notes': notes
        }).scalar_one()
        _audit(connection, session['ride_user_id'], 'pickup_point_created',
               'pickup_point', point_id, None, {'name': name})
    return jsonify({'success': True, 'id': point_id}), 201


@ride_bp.get('/api/rides/admin/settings')
@_role_required('admin', 'support')
def get_ride_settings():
    with db.engine.connect() as connection:
        values = {key: _ride_setting(connection, key) for key in RIDE_SETTING_LIMITS}
    return jsonify(values)


@ride_bp.put('/api/rides/admin/settings/<key>')
@_role_required('admin')
def update_ride_setting(key):
    if key not in RIDE_SETTING_LIMITS:
        return jsonify({'error': 'Setting key is not configurable'}), 404
    try:
        value = int(_json_body().get('value'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Setting value must be an integer'}), 400
    minimum, maximum, _ = RIDE_SETTING_LIMITS[key]
    if isinstance(_json_body().get('value'), bool) or not minimum <= value <= maximum:
        return jsonify({'error': f'Setting value must be between {minimum} and {maximum}'}), 400
    with db.engine.begin() as connection:
        connection.execute(text('''
            INSERT INTO ride_hailing.app_settings (key, value, updated_at)
            VALUES (:key, CAST(:value AS jsonb), now())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
        '''), {
            'key': key,
            'value': str(value)
        })
        _audit(connection, session['ride_user_id'], 'setting_updated',
               'app_setting', key, None, {'value': value})
    return jsonify({'success': True})


@ride_bp.post('/api/rides/<ride_id>/stops')
@_role_required('rider', 'driver')
def add_ride_stop(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
        latitude = float(_json_body()['latitude'])
        longitude = float(_json_body()['longitude'])
    except ValueError as exc:
        return jsonify({'error': 'Provide valid stop coordinates'}), 400
    except (KeyError, TypeError):
        return jsonify({'error': 'Provide valid stop coordinates'}), 400
    if (not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        return jsonify({'error': 'Stop coordinates are outside the valid range'}), 400
    data = _json_body()
    address = str(data.get('address', '')).strip()[:300] or None
    try:
        sequence = int(data.get('sequence'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Stop sequence must be an integer from 1 to 10'}), 400
    if not 1 <= sequence <= 10:
        return jsonify({'error': 'Stop sequence must be an integer from 1 to 10'}), 400
    role = session['ride_role']
    ownership = 'rider_id' if role == 'rider' else 'driver_id'
    with db.engine.begin() as connection:
        ride = connection.execute(text(f'''
            SELECT status FROM ride_hailing.rides
            WHERE id = :ride_id AND {ownership} = :user_id
              AND status IN (
                  'requested'::ride_hailing.ride_status,
                  'matching'::ride_hailing.ride_status,
                  'driver_assigned'::ride_hailing.ride_status
              )
        '''), {'ride_id': ride_id, 'user_id': session['ride_user_id']}).mappings().first()
        if not ride:
            return jsonify({'error': 'Ride is not editable or does not belong to you'}), 409
        row = connection.execute(text('''
            INSERT INTO ride_hailing.ride_stops (ride_id, seq, location, address)
            VALUES (
                :ride_id, :sequence,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                :address
            )
            ON CONFLICT (ride_id, seq) DO NOTHING
            RETURNING id::text AS id, seq AS sequence, address
        '''), {
            'ride_id': ride_id, 'sequence': sequence,
            'longitude': longitude, 'latitude': latitude, 'address': address
        }).mappings().first()
        if not row:
            return jsonify({'error': 'A stop already uses that sequence number'}), 409
    return jsonify(dict(row)), 201


@ride_bp.get('/api/rides/<ride_id>/stops')
@_role_required('rider', 'driver', 'admin', 'support')
def list_ride_stops(ride_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    role = session['ride_role']
    user_id = session['ride_user_id']
    with db.engine.connect() as connection:
        ride = connection.execute(text('''
            SELECT rider_id::text AS rider_id, driver_id::text AS driver_id
            FROM ride_hailing.rides WHERE id = :ride_id
        '''), {'ride_id': ride_id}).mappings().first()
        if not ride:
            return jsonify({'error': 'Ride not found'}), 404
        if role not in ('admin', 'support') and user_id not in (ride['rider_id'], ride['driver_id']):
            return jsonify({'error': 'Ride not found'}), 404
        rows = connection.execute(text('''
            SELECT id::text AS id, seq AS sequence, address,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude, reached_at
            FROM ride_hailing.ride_stops WHERE ride_id = :ride_id
            ORDER BY seq
        '''), {'ride_id': ride_id}).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/<ride_id>/stops/<stop_id>/arrive')
@_role_required('driver')
def mark_stop_reached(ride_id, stop_id):
    try:
        ride_id = _valid_uuid(ride_id, 'ride id')
        stop_id = _valid_uuid(stop_id, 'stop id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    driver_id = session['ride_user_id']
    with db.engine.begin() as connection:
        stop = connection.execute(text('''
            UPDATE ride_hailing.ride_stops s
            SET reached_at = now()
            FROM ride_hailing.rides r
            WHERE s.id = :stop_id AND s.ride_id = r.id AND r.id = :ride_id
              AND r.driver_id = :driver_id
              AND r.status = 'in_progress'::ride_hailing.ride_status
              AND s.reached_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM ride_hailing.driver_locations_live l
                  WHERE l.driver_id = :driver_id
                    AND l.updated_at > now() - interval '60 seconds'
                    AND ST_DWithin(l.location, s.location, 200)
              )
            RETURNING s.seq
        '''), {'stop_id': stop_id, 'ride_id': ride_id, 'driver_id': driver_id}).mappings().first()
        if not stop:
            return jsonify({'error': 'Stop not found or already reached'}), 404
        connection.execute(text('''
            INSERT INTO ride_hailing.geofence_events (ride_id, user_id, event_type, location)
            SELECT :ride_id, :driver_id, 'stop_reached', location
            FROM ride_hailing.ride_stops WHERE id = :stop_id
        '''), {'ride_id': ride_id, 'driver_id': driver_id, 'stop_id': stop_id})
        _event(connection, ride_id, 'stop_reached', driver_id, {'sequence': stop['seq']})
    return jsonify({'success': True})


@ride_bp.get('/api/rides/support/tickets')
@_role_required('rider', 'driver', 'admin', 'support')
def list_support_tickets():
    role = session['ride_role']
    filters = ''
    params = {}
    if role not in ('admin', 'support'):
        filters = 'WHERE t.user_id = :user_id'
        params['user_id'] = session['ride_user_id']
    with db.engine.connect() as connection:
        rows = connection.execute(text(f'''
            SELECT t.id::text AS id, t.user_id::text AS user_id,
                   t.ride_id::text AS ride_id, t.subject, t.status,
                   t.assigned_to::text AS assigned_to, t.created_at, t.closed_at,
                   u.full_name AS user_name,
                   (SELECT count(*) FROM ride_hailing.ticket_messages m
                    WHERE m.ticket_id = t.id) AS message_count
            FROM ride_hailing.support_tickets t
            JOIN ride_hailing.users u ON u.id = t.user_id
            {filters}
            ORDER BY t.created_at DESC LIMIT 200
        '''), params).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/support/tickets')
@_role_required('rider', 'driver', 'admin', 'support')
def create_support_ticket():
    data = _json_body()
    subject = str(data.get('subject', '')).strip()[:200]
    body = str(data.get('message', '')).strip()[:4000]
    if not subject or not body:
        return jsonify({'error': 'Subject and message are required'}), 400
    ride_id = data.get('ride_id')
    if ride_id:
        try:
            ride_id = _valid_uuid(ride_id, 'ride id')
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    user_id = session['ride_user_id']
    with db.engine.begin() as connection:
        if ride_id:
            ride = connection.execute(text('''
                SELECT rider_id, driver_id FROM ride_hailing.rides WHERE id = :ride_id
            '''), {'ride_id': ride_id}).mappings().first()
            if not ride or user_id not in (ride['rider_id'], ride['driver_id']):
                return jsonify({'error': 'The ticket ride must belong to you'}), 404
        ticket_id = connection.execute(text('''
            INSERT INTO ride_hailing.support_tickets (user_id, ride_id, subject)
            VALUES (:user_id, :ride_id, :subject)
            RETURNING id::text
        '''), {'user_id': user_id, 'ride_id': ride_id, 'subject': subject}).scalar_one()
        connection.execute(text('''
            INSERT INTO ride_hailing.ticket_messages (ticket_id, sender_id, body)
            VALUES (:ticket_id, :sender_id, :body)
        '''), {'ticket_id': ticket_id, 'sender_id': user_id, 'body': body})
    return jsonify({'success': True, 'ticket_id': ticket_id}), 201


@ride_bp.get('/api/rides/support/tickets/<ticket_id>')
@_role_required('rider', 'driver', 'admin', 'support')
def get_support_ticket(ticket_id):
    try:
        ticket_id = _valid_uuid(ticket_id, 'ticket id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    role = session['ride_role']
    with db.engine.connect() as connection:
        ticket = connection.execute(text('''
            SELECT id::text AS id, user_id::text AS user_id, ride_id::text AS ride_id,
                   subject, status, assigned_to::text AS assigned_to,
                   created_at, closed_at
            FROM ride_hailing.support_tickets WHERE id = :ticket_id
        '''), {'ticket_id': ticket_id}).mappings().first()
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        if role not in ('admin', 'support') and ticket['user_id'] != session['ride_user_id']:
            return jsonify({'error': 'Ticket not found'}), 404
        messages = connection.execute(text('''
            SELECT m.id, m.body, m.created_at, m.sender_id::text AS sender_id,
                   u.full_name AS sender_name, u.role AS sender_role
            FROM ride_hailing.ticket_messages m
            JOIN ride_hailing.users u ON u.id = m.sender_id
            WHERE m.ticket_id = :ticket_id ORDER BY m.created_at
        '''), {'ticket_id': ticket_id}).mappings().all()
    return jsonify({'ticket': dict(ticket), 'messages': [dict(message) for message in messages]})


@ride_bp.post('/api/rides/support/tickets/<ticket_id>/messages')
@_role_required('rider', 'driver', 'admin', 'support')
def add_ticket_message(ticket_id):
    try:
        ticket_id = _valid_uuid(ticket_id, 'ticket id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    body = str(_json_body().get('message', '')).strip()[:4000]
    if not body:
        return jsonify({'error': 'Message is required'}), 400
    role = session['ride_role']
    user_id = session['ride_user_id']
    with db.engine.begin() as connection:
        ticket = connection.execute(text('''
            SELECT user_id, status FROM ride_hailing.support_tickets
            WHERE id = :ticket_id FOR UPDATE
        '''), {'ticket_id': ticket_id}).mappings().first()
        if not ticket or (role not in ('admin', 'support') and ticket['user_id'] != user_id):
            return jsonify({'error': 'Ticket not found'}), 404
        if ticket['status'] in ('resolved', 'closed'):
            return jsonify({'error': 'Ticket is closed'}), 409
        message_id = connection.execute(text('''
            INSERT INTO ride_hailing.ticket_messages (ticket_id, sender_id, body)
            VALUES (:ticket_id, :sender_id, :body)
            RETURNING id
        '''), {'ticket_id': ticket_id, 'sender_id': user_id, 'body': body}).scalar_one()
        if role in ('admin', 'support') and ticket['status'] == 'open':
            connection.execute(text('''
                UPDATE ride_hailing.support_tickets
                SET status = 'in_progress'::ride_hailing.ticket_status
                WHERE id = :ticket_id
            '''), {'ticket_id': ticket_id})
        else:
            supports = connection.execute(text('''
                SELECT id FROM ride_hailing.users
                WHERE role IN ('admin'::ride_hailing.user_role, 'support'::ride_hailing.user_role)
                  AND status = 'active'::ride_hailing.account_status
            ''')).all()
            for support in supports:
                _notify(connection, support.id, 'support_message', 'New support message',
                        'A support ticket has a new message.',
                        {'ticket_id': ticket_id})
    return jsonify({'success': True, 'message_id': message_id}), 201


@ride_bp.post('/api/rides/admin/tickets/<ticket_id>/status')
@_role_required('admin', 'support')
def update_ticket_status(ticket_id):
    try:
        ticket_id = _valid_uuid(ticket_id, 'ticket id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    status = _json_body().get('status')
    if status not in ('open', 'in_progress', 'resolved', 'closed'):
        return jsonify({'error': 'Unsupported ticket status'}), 400
    with db.engine.begin() as connection:
        ticket = connection.execute(text('''
            UPDATE ride_hailing.support_tickets
            SET status = CAST(:status AS ride_hailing.ticket_status),
                assigned_to = COALESCE(assigned_to, :assigned_to),
                closed_at = CASE WHEN :status IN ('resolved','closed')
                    THEN now() ELSE NULL END
            WHERE id = :ticket_id
            RETURNING user_id
        '''), {
            'ticket_id': ticket_id, 'status': status,
            'assigned_to': session['ride_user_id']
        }).mappings().first()
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        _audit(connection, session['ride_user_id'], 'ticket_status_updated',
               'support_ticket', ticket_id, None, {'status': status})
        _notify(connection, ticket['user_id'], 'support_update', 'Support ticket updated',
                'Your support ticket is now ' + status + '.',
                {'ticket_id': ticket_id, 'status': status})
    return jsonify({'success': True, 'status': status})


@ride_bp.get('/api/rides/admin/sos')
@_role_required('admin', 'support')
def list_sos_events():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT s.id::text AS id, s.ride_id::text AS ride_id,
                   s.triggered_by::text AS triggered_by, u.full_name AS triggered_by_name,
                   s.status, s.notes, s.created_at, s.resolved_at,
                   ST_Y(s.location::geometry) AS latitude,
                   ST_X(s.location::geometry) AS longitude
            FROM ride_hailing.sos_events s
            JOIN ride_hailing.users u ON u.id = s.triggered_by
            ORDER BY s.created_at DESC LIMIT 200
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.get('/api/rides/admin/incidents')
@_role_required('admin', 'support')
def list_incident_reports():
    with db.engine.connect() as connection:
        rows = connection.execute(text('''
            SELECT i.id::text AS id, i.ride_id::text AS ride_id,
                   i.reporter_id::text AS reporter_id, reporter.full_name AS reporter_name,
                   i.reported_id::text AS reported_id, reported.full_name AS reported_name,
                   i.category, i.description, i.evidence_keys, i.created_at
            FROM ride_hailing.incident_reports i
            JOIN ride_hailing.users reporter ON reporter.id = i.reporter_id
            LEFT JOIN ride_hailing.users reported ON reported.id = i.reported_id
            ORDER BY i.created_at DESC LIMIT 300
        ''')).mappings().all()
    return jsonify([dict(row) for row in rows])


@ride_bp.post('/api/rides/admin/sos/<sos_id>/resolve')
@_role_required('admin', 'support')
def resolve_sos_event(sos_id):
    try:
        sos_id = _valid_uuid(sos_id, 'SOS id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    data = _json_body()
    notes = str(data.get('notes', '')).strip()[:1000] or None
    with db.engine.begin() as connection:
        event = connection.execute(text('''
            UPDATE ride_hailing.sos_events
            SET status = 'resolved'::ride_hailing.sos_status,
                handled_by = :handled_by, notes = :notes, resolved_at = now()
            WHERE id = :sos_id AND status IN ('triggered','acknowledged')
            RETURNING ride_id, triggered_by
        '''), {
            'sos_id': sos_id, 'handled_by': session['ride_user_id'], 'notes': notes
        }).mappings().first()
        if not event:
            return jsonify({'error': 'Open SOS alert not found'}), 404
        if event['ride_id']:
            _event(connection, event['ride_id'], 'sos_resolved', session['ride_user_id'],
                   {'sos_id': sos_id})
        _notify(connection, event['triggered_by'], 'sos_update', 'SOS alert resolved',
                'Support has resolved your SOS alert.', {'sos_id': sos_id})
        _audit(connection, session['ride_user_id'], 'sos_resolved',
               'sos_event', sos_id, None, {'notes': notes})
    return jsonify({'success': True})
