from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'sts-secret-key-2024-school-transport')
# Use /tmp for writable storage on Render, local instance folder otherwise
if os.environ.get('RENDER'):
    db_path = '/tmp/school_transport.db'
else:
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'school_transport.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    school_name = db.Column(db.String(200), default='My School')
    morning_route_active = db.Column(db.Boolean, default=False)
    public_link = db.Column(db.String(300), default='')
    link_label = db.Column(db.String(100), default='Weekly School Transport Link')

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='coordinator')  # coordinator, headteacher, it

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    is_morning = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)

class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    teaching_code = db.Column(db.String(20), unique=True, nullable=False)
    passcode = db.Column(db.String(10), nullable=False)
    active = db.Column(db.Boolean, default=True)
    authorised = db.Column(db.Boolean, default=False)

class DutyAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=False)
    duty_date = db.Column(db.Date, nullable=False)
    is_morning = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='assigned')  # assigned, completed, absent
    teacher = db.relationship('Teacher', backref='assignments')
    route = db.relationship('Route', backref='assignments')

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_type = db.Column(db.String(20))   # admin / teacher
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(120))
    action = db.Column(db.String(200))
    ip_address = db.Column(db.String(50))

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def log_action(user_type, user_id, user_name, action):
    entry = AuditLog(
        user_type=user_type,
        user_id=user_id,
        user_name=user_name,
        action=action,
        ip_address=request.remote_addr
    )
    db.session.add(entry)
    db.session.commit()

def is_admin():
    return session.get('admin_id') is not None

def get_settings():
    s = Settings.query.first()
    if not s:
        s = Settings()
        db.session.add(s)
        db.session.commit()
    return s

def is_weekend(d):
    return d.weekday() >= 5  # 5=Sat, 6=Sun

def next_weekday(d):
    d = d + timedelta(days=1)
    while is_weekend(d):
        d = d + timedelta(days=1)
    return d

# ─────────────────────────────────────────
# ALLOCATION ALGORITHM
# ─────────────────────────────────────────

def generate_roster(target_date):
    """
    Rules:
    1. Skip weekends
    2. Teacher who worked yesterday gets today off (1-day rest)
    3. Each teacher rotates through ALL routes before repeating any
    4. No teacher dominates a route
    5. Morning routes only assigned if activated by admin
    """
    if is_weekend(target_date):
        return []

    settings = get_settings()
    teachers = Teacher.query.filter_by(active=True, authorised=True).all()
    routes = Route.query.filter_by(active=True).all()

    if not settings.morning_route_active:
        routes = [r for r in routes if not r.is_morning]

    if not teachers or not routes:
        return []

    yesterday = target_date - timedelta(days=1)
    while is_weekend(yesterday):
        yesterday = yesterday - timedelta(days=1)

    # Teachers who worked yesterday → rest today
    worked_yesterday = set(
        a.teacher_id for a in DutyAssignment.query.filter_by(duty_date=yesterday).all()
    )

    available_today = [t for t in teachers if t.id not in worked_yesterday]

    # If not enough available, pull from rested teachers (fallback)
    if len(available_today) < len(routes):
        rested = [t for t in teachers if t.id in worked_yesterday]
        available_today += rested

    assignments = []
    used_teachers = set()

    for route in routes:
        # Get route history to enforce rotation (no repeat until all done)
        all_assigned_to_route = [
            a.teacher_id for a in DutyAssignment.query
            .filter_by(route_id=route.id)
            .order_by(DutyAssignment.duty_date.desc())
            .all()
        ]

        # Find teacher eligible for this route
        best = None
        for teacher in available_today:
            if teacher.id in used_teachers:
                continue

            # Check rotation: teacher should not repeat route until all routes covered
            teacher_route_history = [
                a.route_id for a in DutyAssignment.query
                .filter_by(teacher_id=teacher.id)
                .order_by(DutyAssignment.duty_date.desc())
                .all()
            ]

            total_routes = len(routes)
            recent_routes = teacher_route_history[:total_routes]

            # If teacher has done this route recently without covering others, skip
            if route.id in recent_routes and len(set(recent_routes)) < total_routes:
                continue

            # Prefer teacher who has done this route least
            if best is None:
                best = teacher
            else:
                best_count = all_assigned_to_route.count(best.id)
                this_count = all_assigned_to_route.count(teacher.id)
                if this_count < best_count:
                    best = teacher

        # If rotation filter left no one, pick least frequent on this route
        if best is None:
            candidates = [t for t in available_today if t.id not in used_teachers]
            if candidates:
                best = min(
                    candidates,
                    key=lambda t: all_assigned_to_route.count(t.id)
                )

        if best:
            used_teachers.add(best.id)
            assignments.append({
                'teacher_id': best.id,
                'teacher_name': best.name,
                'teaching_code': best.teaching_code,
                'route_id': route.id,
                'route_name': route.name,
                'is_morning': route.is_morning,
                'duty_date': target_date.isoformat()
            })

    return assignments

def save_roster(assignments, target_date):
    # Remove existing for that date
    DutyAssignment.query.filter_by(duty_date=target_date).delete()
    for a in assignments:
        entry = DutyAssignment(
            teacher_id=a['teacher_id'],
            route_id=a['route_id'],
            duty_date=target_date,
            is_morning=a['is_morning'],
            status='assigned'
        )
        db.session.add(entry)
    db.session.commit()

def get_replacement_suggestions(absent_teacher_id, route_id, duty_date):
    """Find available teachers not on duty that day, sorted by route fairness."""
    on_duty_today = set(
        a.teacher_id for a in DutyAssignment.query.filter_by(duty_date=duty_date).all()
    )
    on_duty_today.discard(absent_teacher_id)

    all_teachers = Teacher.query.filter_by(active=True, authorised=True).all()
    candidates = [t for t in all_teachers if t.id not in on_duty_today]

    route_history = [
        a.teacher_id for a in DutyAssignment.query.filter_by(route_id=route_id).all()
    ]
    candidates.sort(key=lambda t: route_history.count(t.id))
    return [{'id': t.id, 'name': t.name, 'teaching_code': t.teaching_code} for t in candidates]

# ─────────────────────────────────────────
# ROUTES – PAGES
# ─────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    if not is_admin():
        return redirect(url_for('index'))
    return render_template('admin.html')

@app.route('/teacher')
def teacher_panel():
    if not session.get('teacher_id'):
        return redirect(url_for('index'))
    return render_template('teacher.html')

# ─────────────────────────────────────────
# AUTH APIs
# ─────────────────────────────────────────

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    admin = Admin.query.filter_by(username=data.get('username')).first()
    if admin and admin.check_password(data.get('password')):
        session['admin_id'] = admin.id
        session['admin_name'] = admin.username
        session['admin_role'] = admin.role
        log_action('admin', admin.id, admin.username, 'Admin login')
        return jsonify({'success': True, 'role': admin.role, 'username': admin.username})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/teacher/login', methods=['POST'])
def teacher_login():
    data = request.get_json()
    teacher = Teacher.query.filter_by(
        teaching_code=data.get('teaching_code'),
        passcode=data.get('passcode'),
        authorised=True,
        active=True
    ).first()
    if teacher:
        session['teacher_id'] = teacher.id
        session['teacher_name'] = teacher.name
        log_action('teacher', teacher.id, teacher.name, 'Teacher login')
        return jsonify({'success': True, 'name': teacher.name, 'id': teacher.id})
    return jsonify({'success': False, 'message': 'Invalid code or not authorised'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    user_type = 'teacher' if session.get('teacher_id') else 'admin'
    uid = session.get('teacher_id') or session.get('admin_id')
    uname = session.get('teacher_name') or session.get('admin_name', '')
    log_action(user_type, uid, uname, f'{user_type.capitalize()} logout')
    session.clear()
    return jsonify({'success': True})

@app.route('/api/session', methods=['GET'])
def check_session():
    if session.get('admin_id'):
        return jsonify({'type': 'admin', 'id': session['admin_id'], 'name': session.get('admin_name'), 'role': session.get('admin_role')})
    if session.get('teacher_id'):
        return jsonify({'type': 'teacher', 'id': session['teacher_id'], 'name': session.get('teacher_name')})
    return jsonify({'type': None})

# ─────────────────────────────────────────
# SETTINGS APIs
# ─────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
def get_settings_api():
    s = get_settings()
    return jsonify({
        'school_name': s.school_name,
        'morning_route_active': s.morning_route_active,
        'public_link': s.public_link or '',
        'link_label': s.link_label or 'Weekly School Transport Link'
    })

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    data = request.get_json()
    s = get_settings()
    if 'school_name' in data:
        s.school_name = data['school_name']
    if 'morning_route_active' in data:
        s.morning_route_active = data['morning_route_active']
    if 'public_link' in data:
        s.public_link = data['public_link']
    if 'link_label' in data:
        s.link_label = data['link_label']
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Settings updated: {data}')
    return jsonify({'success': True})

# ─────────────────────────────────────────
# TEACHER APIs
# ─────────────────────────────────────────

@app.route('/api/teachers', methods=['GET'])
def get_teachers():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    teachers = Teacher.query.all()
    return jsonify([{
        'id': t.id, 'name': t.name, 'teaching_code': t.teaching_code,
        'active': t.active, 'authorised': t.authorised
    } for t in teachers])

@app.route('/api/teachers', methods=['POST'])
def add_teacher():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    data = request.get_json()
    if Teacher.query.filter_by(teaching_code=data['teaching_code']).first():
        return jsonify({'error': 'Teaching code already exists'}), 400
    t = Teacher(
        name=data['name'],
        teaching_code=data['teaching_code'],
        passcode=data['passcode'],
        authorised=data.get('authorised', False)
    )
    db.session.add(t)
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Added teacher: {t.name}')
    return jsonify({'success': True, 'id': t.id})

@app.route('/api/teachers/<int:tid>', methods=['PUT'])
def update_teacher(tid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    t = Teacher.query.get_or_404(tid)
    data = request.get_json()
    for field in ['name', 'teaching_code', 'passcode', 'active', 'authorised']:
        if field in data:
            setattr(t, field, data[field])
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Updated teacher: {t.name}')
    return jsonify({'success': True})

@app.route('/api/teachers/<int:tid>', methods=['DELETE'])
def delete_teacher(tid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    t = Teacher.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Deleted teacher: {t.name}')
    return jsonify({'success': True})

# ─────────────────────────────────────────
# ROUTE APIs
# ─────────────────────────────────────────

@app.route('/api/routes', methods=['GET'])
def get_routes():
    routes = Route.query.all()
    return jsonify([{
        'id': r.id, 'name': r.name, 'description': r.description,
        'is_morning': r.is_morning, 'active': r.active
    } for r in routes])

@app.route('/api/routes', methods=['POST'])
def add_route():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    data = request.get_json()
    r = Route(
        name=data['name'],
        description=data.get('description', ''),
        is_morning=data.get('is_morning', False)
    )
    db.session.add(r)
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Added route: {r.name}')
    return jsonify({'success': True, 'id': r.id})

@app.route('/api/routes/<int:rid>', methods=['PUT'])
def update_route(rid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    r = Route.query.get_or_404(rid)
    data = request.get_json()
    for field in ['name', 'description', 'is_morning', 'active']:
        if field in data:
            setattr(r, field, data[field])
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Updated route: {r.name}')
    return jsonify({'success': True})

@app.route('/api/routes/<int:rid>', methods=['DELETE'])
def delete_route(rid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    r = Route.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Deleted route: {r.name}')
    return jsonify({'success': True})

# ─────────────────────────────────────────
# ROSTER APIs
# ─────────────────────────────────────────

@app.route('/api/roster/generate', methods=['POST'])
def generate_roster_api():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    data = request.get_json()
    target = date.fromisoformat(data.get('date', date.today().isoformat()))
    if is_weekend(target):
        return jsonify({'error': 'Cannot generate roster for weekends', 'is_weekend': True}), 400
    assignments = generate_roster(target)
    save_roster(assignments, target)
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Generated roster for {target}')
    return jsonify({'success': True, 'assignments': assignments})

@app.route('/api/roster', methods=['GET'])
def get_roster():
    target_str = request.args.get('date', date.today().isoformat())
    target = date.fromisoformat(target_str)
    assignments = DutyAssignment.query.filter_by(duty_date=target).all()
    return jsonify([{
        'id': a.id,
        'teacher_id': a.teacher_id,
        'teacher_name': a.teacher.name,
        'teaching_code': a.teacher.teaching_code,
        'route_id': a.route_id,
        'route_name': a.route.name,
        'is_morning': a.is_morning,
        'status': a.status,
        'duty_date': a.duty_date.isoformat()
    } for a in assignments])

@app.route('/api/roster/teacher', methods=['GET'])
def get_teacher_roster():
    if not session.get('teacher_id'):
        return jsonify({'error': 'Unauthorised'}), 403
    tid = session['teacher_id']
    target_str = request.args.get('date', date.today().isoformat())
    target = date.fromisoformat(target_str)
    assignments = DutyAssignment.query.filter_by(duty_date=target, teacher_id=tid).all()
    return jsonify([{
        'id': a.id,
        'route_name': a.route.name,
        'is_morning': a.is_morning,
        'status': a.status,
        'duty_date': a.duty_date.isoformat()
    } for a in assignments])

@app.route('/api/roster/week', methods=['GET'])
def get_week_roster():
    start_str = request.args.get('start', date.today().isoformat())
    start = date.fromisoformat(start_str)
    days = []
    d = start
    for _ in range(7):
        if not is_weekend(d):
            assignments = DutyAssignment.query.filter_by(duty_date=d).all()
            days.append({
                'date': d.isoformat(),
                'day': d.strftime('%A'),
                'assignments': [{
                    'teacher_name': a.teacher.name,
                    'teaching_code': a.teacher.teaching_code,
                    'route_name': a.route.name,
                    'is_morning': a.is_morning,
                    'status': a.status
                } for a in assignments]
            })
        d += timedelta(days=1)
    return jsonify(days)

@app.route('/api/roster/<int:aid>/absent', methods=['POST'])
def mark_absent(aid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    a = DutyAssignment.query.get_or_404(aid)
    a.status = 'absent'
    db.session.commit()
    suggestions = get_replacement_suggestions(a.teacher_id, a.route_id, a.duty_date)
    log_action('admin', session['admin_id'], session.get('admin_name'),
               f'Marked absent: {a.teacher.name} on {a.duty_date}')
    return jsonify({'success': True, 'suggestions': suggestions})

@app.route('/api/roster/<int:aid>/replace', methods=['POST'])
def replace_teacher(aid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    a = DutyAssignment.query.get_or_404(aid)
    data = request.get_json()
    new_teacher = Teacher.query.get_or_404(data['teacher_id'])
    old_name = a.teacher.name
    a.teacher_id = data['teacher_id']
    a.status = 'assigned'
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'),
               f'Replaced {old_name} with {new_teacher.name} on route {a.route.name}')
    return jsonify({'success': True})

# ─────────────────────────────────────────
# AUDIT LOG APIs
# ─────────────────────────────────────────

@app.route('/api/logs', methods=['GET'])
def get_logs():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    limit = int(request.args.get('limit', 100))
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return jsonify([{
        'id': l.id,
        'timestamp': l.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'user_type': l.user_type,
        'user_name': l.user_name,
        'action': l.action,
        'ip': l.ip_address
    } for l in logs])

# ─────────────────────────────────────────
# ADMIN MANAGEMENT
# ─────────────────────────────────────────

@app.route('/api/admins', methods=['GET'])
def get_admins():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    admins = Admin.query.all()
    return jsonify([{'id': a.id, 'username': a.username, 'role': a.role} for a in admins])

@app.route('/api/admins', methods=['POST'])
def add_admin():
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    data = request.get_json()
    if Admin.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    a = Admin(username=data['username'], role=data.get('role', 'coordinator'))
    a.set_password(data['password'])
    db.session.add(a)
    db.session.commit()
    log_action('admin', session['admin_id'], session.get('admin_name'), f'Added admin: {a.username}')
    return jsonify({'success': True})

@app.route('/api/admins/<int:aid>', methods=['DELETE'])
def delete_admin(aid):
    if not is_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    a = Admin.query.get_or_404(aid)
    db.session.delete(a)
    db.session.commit()
    return jsonify({'success': True})

# ─────────────────────────────────────────
# INIT DB + SEED
# ─────────────────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        # Default settings
        if not Settings.query.first():
            db.session.add(Settings(school_name='My School'))
            db.session.commit()
        # Default admin
        if not Admin.query.first():
            a = Admin(username='admin', role='it')
            a.set_password('admin123')
            db.session.add(a)
            db.session.commit()
        # Seed 6 routes
        if not Route.query.first():
            routes = [
                Route(name='Route 1 - North', description='North suburb area'),
                Route(name='Route 2 - South', description='South suburb area'),
                Route(name='Route 3 - East', description='East suburb area'),
                Route(name='Route 4 - West', description='West suburb area'),
                Route(name='Route 5 - Central', description='Central area'),
                Route(name='Route 6 - Morning North', description='Morning north route', is_morning=True),
            ]
            db.session.bulk_save_objects(routes)
            db.session.commit()
        # Seed 12 teachers
        if not Teacher.query.first():
            teachers = [
                Teacher(name='Alice Mwangi', teaching_code='TCH001', passcode='1001', authorised=True),
                Teacher(name='Bob Odhiambo', teaching_code='TCH002', passcode='1002', authorised=True),
                Teacher(name='Carol Njeri', teaching_code='TCH003', passcode='1003', authorised=True),
                Teacher(name='David Kamau', teaching_code='TCH004', passcode='1004', authorised=True),
                Teacher(name='Eve Wanjiru', teaching_code='TCH005', passcode='1005', authorised=True),
                Teacher(name='Frank Otieno', teaching_code='TCH006', passcode='1006', authorised=True),
                Teacher(name='Grace Achieng', teaching_code='TCH007', passcode='1007', authorised=True),
                Teacher(name='Henry Mutua', teaching_code='TCH008', passcode='1008', authorised=True),
                Teacher(name='Irene Chebet', teaching_code='TCH009', passcode='1009', authorised=True),
                Teacher(name='James Kariuki', teaching_code='TCH010', passcode='1010', authorised=True),
                Teacher(name='Karen Auma', teaching_code='TCH011', passcode='1011', authorised=True),
                Teacher(name='Liam Ndirangu', teaching_code='TCH012', passcode='1012', authorised=True),
            ]
            db.session.bulk_save_objects(teachers)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
