from app import app, db, Admin

with app.app_context():
    # Fix RAY BEN -> ben.ray
    wrong = Admin.query.filter_by(username='RAY BEN').first()
    if wrong:
        wrong.username = 'ben.ray'
        wrong.set_password('0000')
        db.session.commit()
        print('Fixed RAY BEN -> ben.ray')

    # Reset all passwords to 0000
    for uname in ['evance.mwembe', 'kevin.ogutu', 'ben.ray', 'admin']:
        a = Admin.query.filter_by(username=uname).first()
        if a:
            a.set_password('0000')
            print(f'Password reset: {uname}')

    db.session.commit()

    print('\nAll admins:')
    for a in Admin.query.all():
        print(f'  [{a.username}] - {a.role} - password: 0000')
    print('\nDONE')
