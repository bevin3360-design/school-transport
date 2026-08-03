"""
SCHOOL TRANSPORT SYSTEM — Multi-Tenant Platform
Owner: Super Admin controls all schools
Payment: M-Pesa to 0753538323
Trial: 30 days free per school
"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import os, re, json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'STS-PLATFORM-2026-SUPERKEY')
if os.environ.get('RENDER'):
    db_path = '/tmp/sts_platform.db'
else:
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'instance', 'sts_platform.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

# ── PAYMENT CONFIG ──────────────────────
MPESA_NUMBER = "0753538323"
MPESA_NAME   = "BEN RAY"
PLANS = {
    'basic':    {'name': 'Basic',    'price': 500,  'teachers': 10, 'routes': 4},
    'standard': {'name': 'Standard', 'price': 1500, 'teachers': 20, 'routes': 8},
    'premium':  {'name': 'Premium',  'price': 3000, 'teachers': 999,'routes': 999},
}
TRIAL_DAYS = 30

# ════════════════════════════════════════
# MODELS
# ════════════════════════════════════════

class School(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(200), nullable=False)
    code          = db.Column(db.String(20), unique=True, nullable=False)
    email         = db.Column(db.String(120))
    phone         = db.Column(db.String(20))
    county        = db.Column(db.String(100))
    plan          = db.Column(db.String(20), default='basic')
    status        = db.Column(db.String(20), default='trial')  # trial/active/expired/suspended
    trial_start   = db.Column(db.Date, default=date.today)
    trial_end     = db.Column(db.Date)
    subscription_end = db.Column(db.Date)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    morning_active = db.Column(db.Boolean, default=False)
    evening_active = db.Column(db.Boolean, default=False)
    public_link   = db.Column(db.String(300), default='')

    def is_active(self):
        today = date.today()
        if self.status == 'trial':
            return today <= (self.trial_end or today)
        if self.status == 'active':
            return today <= (self.subscription_end or today)
        return False

    def days_remaining(self):
        today = date.today()
        if self.status == 'trial':
            end = self.trial_end or today
        elif self.status == 'active':
            end = self.subscription_end or today
        else:
            return 0
        return max(0, (end - today).days)

class SchoolAdmin(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    school_id     = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    username      = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role          = db.Column(db.String(50), default='coordinator')
    school        = db.relationship('School', backref='admins')

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

class Teacher(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    school_id     = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    name          = db.Column(db.String(120), nullable=False)
    teaching_code = db.Column(db.String(20), nullable=False)
    passcode      = db.Column(db.String(20), nullable=False)
    active        = db.Column(db.Boolean, default=True)
    authorised    = db.Column(db.Boolean, default=False)
    school        = db.relationship('School', backref='teachers')

class Route(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    name       = db.Column(db.String(100), nullable=False)
    description= db.Column(db.String(200))
    is_morning = db.Column(db.Boolean, default=False)
    active     = db.Column(db.Boolean, default=True)
    school     = db.relationship('School', backref='routes')

class DutyAssignment(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    route_id   = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=False)
    duty_date  = db.Column(db.Date, nullable=False)
    is_morning = db.Column(db.Boolean, default=False)
    status     = db.Column(db.String(20), default='assigned')
    teacher    = db.relationship('Teacher', backref='assignments')
    route      = db.relationship('Route', backref='assignments')

class Payment(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    school_id   = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    mpesa_code  = db.Column(db.String(20), nullable=False)
    amount      = db.Column(db.Integer, nullable=False)
    plan        = db.Column(db.String(20), nullable=False)
    phone       = db.Column(db.String(20))
    status      = db.Column(db.String(20), default='pending')  # pending/verified/rejected
    submitted_at= db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime)
    school      = db.relationship('School', backref='payments')

class SuperAdmin(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

class AuditLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, nullable=True)
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow)
    user_type  = db.Column(db.String(20))
    user_name  = db.Column(db.String(120))
    action     = db.Column(db.String(300))
    ip         = db.Column(db.String(50))

# ════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════
def log_action(school_id, user_type, user_name, action):
    db.session.add(AuditLog(
        school_id=school_id, user_type=user_type,
        user_name=user_name, action=action,
        ip=request.remote_addr))
    db.session.commit()

def sanitize(v, ml=200):
    if not v: return ''
    return re.sub(r'[<>\\]', '', str(v).strip()[:ml])

def is_super(): return session.get('super_id') is not None
def is_school_admin(): return session.get('school_admin_id') is not None
def current_school_id(): return session.get('school_id')

def get_school_or_403():
    sid = current_school_id()
    if not sid: return None, (jsonify({'error':'Unauthorised'}), 403)
    s = School.query.get(sid)
    if not s or not s.is_active():
        return None, (jsonify({'error':'School subscription expired or inactive'}), 403)
    return s, None

def is_weekend(d): return d.weekday() >= 5

# ── ALLOCATION ALGORITHM ────────────────
def generate_roster(school_id, target_date):
    if is_weekend(target_date): return []
    school = School.query.get(school_id)
    teachers = Teacher.query.filter_by(school_id=school_id, active=True, authorised=True).all()
    all_routes = Route.query.filter_by(school_id=school_id, active=True).all()
    routes = []
    for r in all_routes:
        if r.is_morning and school.morning_active: routes.append(r)
        elif not r.is_morning and school.evening_active: routes.append(r)
    if not teachers or not routes: return []

    yesterday = target_date - timedelta(days=1)
    while is_weekend(yesterday): yesterday -= timedelta(days=1)
    worked_yesterday = {a.teacher_id for a in
        DutyAssignment.query.filter_by(school_id=school_id, duty_date=yesterday).all()}
    available = [t for t in teachers if t.id not in worked_yesterday] or teachers

    assignments = []
    used = set()
    for route in routes:
        history = [a.teacher_id for a in
            DutyAssignment.query.filter_by(school_id=school_id, route_id=route.id)
            .order_by(DutyAssignment.duty_date.desc()).all()]
        best = None
        for t in available:
            if t.id in used: continue
            tr_hist = [a.route_id for a in
                DutyAssignment.query.filter_by(school_id=school_id, teacher_id=t.id)
                .order_by(DutyAssignment.duty_date.desc()).all()]
            recent = tr_hist[:len(routes)]
            if route.id in recent and len(set(recent)) < len(routes): continue
            if best is None or history.count(t.id) < history.count(best.id):
                best = t
        if best is None:
            cands = [t for t in available if t.id not in used]
            if cands:
                best = min(cands, key=lambda t: history.count(t.id))
        if best:
            used.add(best.id)
            assignments.append({
                'teacher_id': best.id, 'teacher_name': best.name,
                'teaching_code': best.teaching_code,
                'route_id': route.id, 'route_name': route.name,
                'is_morning': route.is_morning,
                'duty_date': target_date.isoformat()
            })
    return assignments

def save_roster(school_id, assignments, target_date):
    DutyAssignment.query.filter_by(school_id=school_id, duty_date=target_date).delete()
    for a in assignments:
        db.session.add(DutyAssignment(
            school_id=school_id, teacher_id=a['teacher_id'],
            route_id=a['route_id'], duty_date=target_date,
            is_morning=a['is_morning'], status='assigned'))
    db.session.commit()

# ════════════════════════════════════════
# PAGES
# ════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/super')
def super_panel():
    if not is_super(): return redirect('/')
    return render_template('super.html')

@app.route('/admin')
def admin_panel():
    if not is_school_admin(): return redirect('/')
    return render_template('admin.html')

@app.route('/teacher')
def teacher_panel():
    if not session.get('teacher_id'): return redirect('/')
    return render_template('teacher.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/payment')
def payment_page():
    if not is_school_admin(): return redirect('/')
    return render_template('payment.html')

# ════════════════════════════════════════
# AUTH APIs
# ════════════════════════════════════════
@app.route('/api/super/login', methods=['POST'])
def super_login():
    data = request.get_json()
    sa = SuperAdmin.query.filter_by(username=sanitize(data.get('username',''))).first()
    if sa and sa.check_password(data.get('password','')):
        session['super_id'] = sa.id
        session['super_name'] = sa.username
        log_action(None, 'super', sa.username, 'Super admin login')
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = sanitize(data.get('username',''))
    password = data.get('password','')
    admin = SchoolAdmin.query.filter_by(username=username).first()
    if admin and admin.check_password(password):
        school = School.query.get(admin.school_id)
        if not school.is_active():
            return jsonify({'success': False,
                'message': f'Subscription expired. Please renew to continue.'}), 403
        session['school_admin_id'] = admin.id
        session['school_id'] = admin.school_id
        session['school_name'] = school.name
        session['admin_role'] = admin.role
        log_action(school.id, 'admin', username, 'Admin login')
        return jsonify({'success': True, 'school': school.name,
                        'role': admin.role, 'days_left': school.days_remaining()})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/teacher/login', methods=['POST'])
def teacher_login():
    data = request.get_json()
    code = sanitize(data.get('teaching_code',''))
    passcode = sanitize(data.get('passcode',''))
    school_code = sanitize(data.get('school_code',''))
    school = School.query.filter_by(code=school_code).first()
    if not school or not school.is_active():
        return jsonify({'success': False, 'message': 'School not found or inactive'}), 401
    teacher = Teacher.query.filter_by(
        school_id=school.id, teaching_code=code,
        passcode=passcode, authorised=True, active=True).first()
    if teacher:
        session['teacher_id'] = teacher.id
        session['teacher_name'] = teacher.name
        session['school_id'] = school.id
        session['school_name'] = school.name
        log_action(school.id, 'teacher', teacher.name, 'Teacher login')
        return jsonify({'success': True, 'name': teacher.name, 'school': school.name})
    return jsonify({'success': False, 'message': 'Invalid code or not authorised'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/session')
def check_session():
    if session.get('super_id'):
        return jsonify({'type': 'super', 'name': session.get('super_name')})
    if session.get('school_admin_id'):
        return jsonify({'type': 'admin', 'school': session.get('school_name'),
                        'role': session.get('admin_role'),
                        'school_id': session.get('school_id')})
    if session.get('teacher_id'):
        return jsonify({'type': 'teacher', 'name': session.get('teacher_name'),
                        'school': session.get('school_name'),
                        'school_id': session.get('school_id')})
    return jsonify({'type': None})

# ════════════════════════════════════════
# SCHOOL REGISTRATION
# ════════════════════════════════════════
@app.route('/api/register', methods=['POST'])
def register_school():
    data = request.get_json()
    name   = sanitize(data.get('name',''))
    code   = sanitize(data.get('code','').upper())
    email  = sanitize(data.get('email',''))
    phone  = sanitize(data.get('phone',''))
    county = sanitize(data.get('county',''))
    admin_username = sanitize(data.get('admin_username',''))
    admin_password = data.get('admin_password','')

    if not all([name, code, admin_username, admin_password]):
        return jsonify({'error': 'All fields required'}), 400
    if School.query.filter_by(code=code).first():
        return jsonify({'error': f'School code {code} already exists'}), 400

    trial_end = date.today() + timedelta(days=TRIAL_DAYS)
    school = School(name=name, code=code, email=email, phone=phone,
                    county=county, plan='basic', status='trial',
                    trial_start=date.today(), trial_end=trial_end)
    db.session.add(school)
    db.session.flush()

    admin = SchoolAdmin(school_id=school.id, username=admin_username, role='coordinator')
    admin.set_password(admin_password)
    db.session.add(admin)
    db.session.commit()
    log_action(school.id, 'system', 'registration', f'School {name} registered')
    return jsonify({'success': True, 'school_id': school.id,
                    'trial_end': trial_end.isoformat(),
                    'message': f'Welcome! Your 30-day free trial starts today.'})

# ════════════════════════════════════════
# PAYMENT APIs
# ════════════════════════════════════════
@app.route('/api/payment/info')
def payment_info():
    return jsonify({
        'mpesa_number': MPESA_NUMBER,
        'mpesa_name': MPESA_NAME,
        'plans': PLANS
    })

@app.route('/api/payment/submit', methods=['POST'])
def submit_payment():
    if not is_school_admin():
        return jsonify({'error': 'Unauthorised'}), 403
    data = request.get_json()
    mpesa_code = sanitize(data.get('mpesa_code','').upper())
    amount     = int(data.get('amount', 0))
    plan       = sanitize(data.get('plan','basic'))
    phone      = sanitize(data.get('phone',''))

    if not mpesa_code or not amount:
        return jsonify({'error': 'M-Pesa code and amount required'}), 400
    if Payment.query.filter_by(mpesa_code=mpesa_code).first():
        return jsonify({'error': 'This M-Pesa code has already been submitted'}), 400

    p = Payment(school_id=current_school_id(), mpesa_code=mpesa_code,
                amount=amount, plan=plan, phone=phone, status='pending')
    db.session.add(p)
    db.session.commit()
    log_action(current_school_id(), 'admin', session.get('school_name'),
               f'Payment submitted: {mpesa_code} KES {amount} for {plan}')
    return jsonify({'success': True,
                    'message': 'Payment submitted. Super admin will verify within 24 hours.'})

@app.route('/api/payment/status')
def payment_status():
    if not is_school_admin(): return jsonify({'error': 'Unauthorised'}), 403
    payments = Payment.query.filter_by(school_id=current_school_id())\
               .order_by(Payment.submitted_at.desc()).all()
    school = School.query.get(current_school_id())
    return jsonify({
        'school_status': school.status,
        'days_remaining': school.days_remaining(),
        'plan': school.plan,
        'payments': [{
            'mpesa_code': p.mpesa_code, 'amount': p.amount,
            'plan': p.plan, 'status': p.status,
            'submitted_at': p.submitted_at.strftime('%Y-%m-%d %H:%M')
        } for p in payments]
    })

# ════════════════════════════════════════
# SUPER ADMIN APIs
# ════════════════════════════════════════
@app.route('/api/super/schools')
def super_schools():
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    schools = School.query.order_by(School.created_at.desc()).all()
    return jsonify([{
        'id': s.id, 'name': s.name, 'code': s.code,
        'plan': s.plan, 'status': s.status,
        'days_remaining': s.days_remaining(),
        'trial_end': s.trial_end.isoformat() if s.trial_end else None,
        'subscription_end': s.subscription_end.isoformat() if s.subscription_end else None,
        'phone': s.phone, 'county': s.county,
        'teachers': Teacher.query.filter_by(school_id=s.id).count(),
        'routes': Route.query.filter_by(school_id=s.id).count(),
    } for s in schools])

@app.route('/api/super/payments')
def super_payments():
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    payments = Payment.query.order_by(Payment.submitted_at.desc()).all()
    return jsonify([{
        'id': p.id, 'school': p.school.name, 'school_id': p.school_id,
        'mpesa_code': p.mpesa_code, 'amount': p.amount,
        'plan': p.plan, 'phone': p.phone, 'status': p.status,
        'submitted_at': p.submitted_at.strftime('%Y-%m-%d %H:%M')
    } for p in payments])

@app.route('/api/super/payment/<int:pid>/verify', methods=['POST'])
def verify_payment(pid):
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    p = Payment.query.get_or_404(pid)
    p.status = 'verified'
    p.verified_at = datetime.utcnow()
    # Activate school
    school = School.query.get(p.school_id)
    school.plan = p.plan
    school.status = 'active'
    today = date.today()
    current_end = school.subscription_end or today
    if current_end < today: current_end = today
    school.subscription_end = current_end + timedelta(days=30)
    db.session.commit()
    log_action(None, 'super', session.get('super_name'),
               f'Verified payment {p.mpesa_code} for {school.name} — activated {p.plan} until {school.subscription_end}')
    return jsonify({'success': True,
                    'message': f'{school.name} activated on {p.plan} plan until {school.subscription_end}'})

@app.route('/api/super/payment/<int:pid>/reject', methods=['POST'])
def reject_payment(pid):
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    p = Payment.query.get_or_404(pid)
    p.status = 'rejected'
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/super/school/<int:sid>/suspend', methods=['POST'])
def suspend_school(sid):
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    s = School.query.get_or_404(sid)
    s.status = 'suspended'
    db.session.commit()
    log_action(None, 'super', session.get('super_name'), f'Suspended school: {s.name}')
    return jsonify({'success': True})

@app.route('/api/super/school/<int:sid>/activate', methods=['POST'])
def activate_school(sid):
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    data = request.get_json() or {}
    s = School.query.get_or_404(sid)
    s.status = 'active'
    days = int(data.get('days', 30))
    s.subscription_end = date.today() + timedelta(days=days)
    db.session.commit()
    log_action(None, 'super', session.get('super_name'),
               f'Manually activated: {s.name} for {days} days')
    return jsonify({'success': True})

@app.route('/api/super/stats')
def super_stats():
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    schools = School.query.all()
    payments = Payment.query.filter_by(status='verified').all()
    pending = Payment.query.filter_by(status='pending').count()
    revenue = sum(p.amount for p in payments)
    return jsonify({
        'total_schools': len(schools),
        'active': sum(1 for s in schools if s.status == 'active'),
        'trial': sum(1 for s in schools if s.status == 'trial'),
        'expired': sum(1 for s in schools if s.status == 'expired'),
        'suspended': sum(1 for s in schools if s.status == 'suspended'),
        'total_revenue': revenue,
        'pending_payments': pending,
        'total_teachers': Teacher.query.count(),
    })

@app.route('/api/super/logs')
def super_logs():
    if not is_super(): return jsonify({'error':'Unauthorised'}), 403
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return jsonify([{
        'time': l.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'school_id': l.school_id, 'user_type': l.user_type,
        'user_name': l.user_name, 'action': l.action, 'ip': l.ip
    } for l in logs])

# ════════════════════════════════════════
# SCHOOL ADMIN APIs (scoped to school)
# ════════════════════════════════════════
@app.route('/api/school/settings', methods=['GET'])
def school_settings():
    school, err = get_school_or_403()
    if err: return err
    return jsonify({
        'name': school.name, 'code': school.code,
        'plan': school.plan, 'status': school.status,
        'days_remaining': school.days_remaining(),
        'morning_active': school.morning_active,
        'evening_active': school.evening_active,
        'public_link': school.public_link or '',
        'mpesa_number': MPESA_NUMBER,
        'mpesa_name': MPESA_NAME,
        'plans': PLANS
    })

@app.route('/api/school/settings', methods=['PUT'])
def update_school_settings():
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    school, err = get_school_or_403()
    if err: return err
    data = request.get_json()
    if 'morning_active' in data: school.morning_active = bool(data['morning_active'])
    if 'evening_active' in data: school.evening_active = bool(data['evening_active'])
    if 'public_link' in data: school.public_link = data['public_link'].strip()
    db.session.commit()
    return jsonify({'success': True})

# Teachers
@app.route('/api/teachers', methods=['GET'])
def get_teachers():
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    teachers = Teacher.query.filter_by(school_id=current_school_id()).all()
    return jsonify([{'id':t.id,'name':t.name,'teaching_code':t.teaching_code,
                     'active':t.active,'authorised':t.authorised} for t in teachers])

@app.route('/api/teachers', methods=['POST'])
def add_teacher():
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    school, err = get_school_or_403()
    if err: return err
    data = request.get_json()
    name = sanitize(data.get('name',''))
    code = sanitize(data.get('teaching_code',''))
    passcode = sanitize(data.get('passcode',''))
    if not all([name, code, passcode]):
        return jsonify({'error':'Name, code and passcode required'}), 400
    plan_limit = PLANS.get(school.plan,{}).get('teachers', 10)
    current_count = Teacher.query.filter_by(school_id=school.id, active=True).count()
    if current_count >= plan_limit:
        return jsonify({'error':f'Teacher limit reached for {school.plan} plan ({plan_limit} max). Upgrade to add more.'}), 400
    if Teacher.query.filter_by(school_id=school.id, teaching_code=code).first():
        return jsonify({'error':'Teaching code already exists in your school'}), 400
    t = Teacher(school_id=school.id, name=name, teaching_code=code,
                passcode=passcode, authorised=data.get('authorised',False))
    db.session.add(t)
    db.session.commit()
    return jsonify({'success': True, 'id': t.id})

@app.route('/api/teachers/<int:tid>', methods=['PUT'])
def update_teacher(tid):
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    t = Teacher.query.filter_by(id=tid, school_id=current_school_id()).first_or_404()
    data = request.get_json()
    if 'name' in data: t.name = sanitize(data['name'])
    if 'teaching_code' in data: t.teaching_code = sanitize(data['teaching_code'])
    if 'passcode' in data: t.passcode = sanitize(data['passcode'])
    if 'active' in data: t.active = data['active']
    if 'authorised' in data: t.authorised = data['authorised']
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/teachers/<int:tid>', methods=['DELETE'])
def delete_teacher(tid):
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    t = Teacher.query.filter_by(id=tid, school_id=current_school_id()).first_or_404()
    db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True})

# Routes
@app.route('/api/routes', methods=['GET'])
def get_routes():
    sid = current_school_id()
    if not sid: return jsonify({'error':'Unauthorised'}), 403
    routes = Route.query.filter_by(school_id=sid).all()
    return jsonify([{'id':r.id,'name':r.name,'description':r.description,
                     'is_morning':r.is_morning,'active':r.active} for r in routes])

@app.route('/api/routes', methods=['POST'])
def add_route():
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    school, err = get_school_or_403()
    if err: return err
    data = request.get_json()
    plan_limit = PLANS.get(school.plan,{}).get('routes', 4)
    current_count = Route.query.filter_by(school_id=school.id, active=True).count()
    if current_count >= plan_limit:
        return jsonify({'error':f'Route limit reached for {school.plan} plan ({plan_limit} max). Upgrade to add more.'}), 400
    r = Route(school_id=school.id, name=sanitize(data.get('name','')),
              description=sanitize(data.get('description','')),
              is_morning=data.get('is_morning', False))
    db.session.add(r)
    db.session.commit()
    return jsonify({'success': True, 'id': r.id})

@app.route('/api/routes/<int:rid>', methods=['PUT'])
def update_route(rid):
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    r = Route.query.filter_by(id=rid, school_id=current_school_id()).first_or_404()
    data = request.get_json()
    for f in ['name','description','is_morning','active']:
        if f in data: setattr(r, f, sanitize(data[f]) if f in ['name','description'] else data[f])
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/routes/<int:rid>', methods=['DELETE'])
def delete_route(rid):
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    r = Route.query.filter_by(id=rid, school_id=current_school_id()).first_or_404()
    db.session.delete(r)
    db.session.commit()
    return jsonify({'success': True})

# Roster
@app.route('/api/roster/generate', methods=['POST'])
def generate_roster_api():
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    school, err = get_school_or_403()
    if err: return err
    data = request.get_json()
    target = date.fromisoformat(data.get('date', date.today().isoformat()))
    if is_weekend(target):
        return jsonify({'error':'Cannot generate roster for weekends'}), 400
    assignments = generate_roster(school.id, target)
    save_roster(school.id, assignments, target)
    log_action(school.id, 'admin', session.get('school_name'), f'Generated roster for {target}')
    return jsonify({'success': True, 'assignments': assignments})

@app.route('/api/roster')
def get_roster():
    sid = current_school_id()
    if not sid: return jsonify({'error':'Unauthorised'}), 403
    target = date.fromisoformat(request.args.get('date', date.today().isoformat()))
    assignments = DutyAssignment.query.filter_by(school_id=sid, duty_date=target).all()
    return jsonify([{
        'id':a.id,'teacher_name':a.teacher.name,
        'teaching_code':a.teacher.teaching_code,
        'route_name':a.route.name,'is_morning':a.is_morning,
        'status':a.status,'duty_date':a.duty_date.isoformat()
    } for a in assignments])

@app.route('/api/roster/teacher')
def teacher_roster():
    if not session.get('teacher_id'): return jsonify({'error':'Unauthorised'}), 403
    target = date.fromisoformat(request.args.get('date', date.today().isoformat()))
    assignments = DutyAssignment.query.filter_by(
        school_id=session['school_id'],
        teacher_id=session['teacher_id'], duty_date=target).all()
    return jsonify([{'route_name':a.route.name,'is_morning':a.is_morning,
                     'status':a.status,'duty_date':a.duty_date.isoformat()} for a in assignments])

@app.route('/api/roster/<int:aid>/absent', methods=['POST'])
def mark_absent(aid):
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    a = DutyAssignment.query.filter_by(id=aid, school_id=current_school_id()).first_or_404()
    a.status = 'absent'
    db.session.commit()
    on_duty = {x.teacher_id for x in DutyAssignment.query.filter_by(
        school_id=current_school_id(), duty_date=a.duty_date).all()}
    on_duty.discard(a.teacher_id)
    candidates = Teacher.query.filter_by(school_id=current_school_id(),
                                         active=True, authorised=True).all()
    suggestions = [{'id':t.id,'name':t.name,'teaching_code':t.teaching_code}
                   for t in candidates if t.id not in on_duty]
    return jsonify({'success': True, 'suggestions': suggestions})

@app.route('/api/roster/<int:aid>/replace', methods=['POST'])
def replace_teacher(aid):
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    a = DutyAssignment.query.filter_by(id=aid, school_id=current_school_id()).first_or_404()
    data = request.get_json()
    a.teacher_id = data['teacher_id']
    a.status = 'assigned'
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/logs')
def get_logs():
    if not is_school_admin(): return jsonify({'error':'Unauthorised'}), 403
    logs = AuditLog.query.filter_by(school_id=current_school_id())\
           .order_by(AuditLog.timestamp.desc()).limit(100).all()
    return jsonify([{'time':l.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                     'user_type':l.user_type,'user_name':l.user_name,
                     'action':l.action,'ip':l.ip} for l in logs])

# ════════════════════════════════════════
# SECURITY HEADERS
# ════════════════════════════════════════
@app.after_request
def security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# ════════════════════════════════════════
# INIT DB
# ════════════════════════════════════════
def init_db():
    with app.app_context():
        db.create_all()
        if not SuperAdmin.query.first():
            sa = SuperAdmin(username='superadmin')
            sa.set_password('STS@2026#Owner')
            db.session.add(sa)
            db.session.commit()
            print('Super admin created: superadmin / STS@2026#Owner')

# Always initialise DB — works for both direct run and gunicorn
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
