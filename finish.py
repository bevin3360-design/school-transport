from app import app, db, Settings
import sqlalchemy

with app.app_context():
    # Add evening_route_active column if missing
    try:
        with db.engine.connect() as conn:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE settings ADD COLUMN evening_route_active BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        print("Added evening_route_active column")
    except Exception as e:
        print(f"Column note: {e}")

    # Update settings
    s = Settings.query.first()
    s.school_name = 'FSL School'
    s.morning_route_active = False
    s.evening_route_active = False
    s.public_link = 'https://school-transport-c0gs.onrender.com'
    s.link_label = 'Weekly School Transport Link'
    db.session.commit()
    print(f"Settings saved:")
    print(f"  School: {s.school_name}")
    print(f"  Morning: {s.morning_route_active}")
    print(f"  Evening: {s.evening_route_active}")
    print(f"  Link: {s.public_link}")
    print("DONE")
