"""Startup script for Render deployment."""
import os
os.environ['RENDER'] = '1'
from app import init_db, app
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
