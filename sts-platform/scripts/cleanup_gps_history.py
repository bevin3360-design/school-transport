import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, cleanup_location_history


if __name__ == '__main__':
    with app.app_context():
        deleted = cleanup_location_history()
    print(f'Removed {deleted} expired GPS history records.')
