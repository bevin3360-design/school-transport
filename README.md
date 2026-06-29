# School Transport System (STS)

## Default Login Credentials

### Admin
- **URL:** http://localhost:5000
- **Username:** `admin`
- **Password:** `admin123`
- **Role:** IT Expert (full access)

### Sample Teachers (12 pre-loaded)
| Name | Teaching Code | Passcode |
|------|--------------|---------|
| Alice Mwangi | TCH001 | 1001 |
| Bob Odhiambo | TCH002 | 1002 |
| Carol Njeri | TCH003 | 1003 |
| David Kamau | TCH004 | 1004 |
| Eve Wanjiru | TCH005 | 1005 |
| Frank Otieno | TCH006 | 1006 |
| Grace Achieng | TCH007 | 1007 |
| Henry Mutua | TCH008 | 1008 |
| Irene Chebet | TCH009 | 1009 |
| James Kariuki | TCH010 | 1010 |
| Karen Auma | TCH011 | 1011 |
| Liam Ndirangu | TCH012 | 1012 |

## Running Locally
```
python app.py
```
Open: http://localhost:5000

## Deploying to Render (Free Internet Hosting)
1. Create account at https://render.com
2. Push this folder to a GitHub repo
3. On Render: New → Web Service → connect your repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `python -c "from app import init_db; init_db()" && gunicorn app:app`
6. Free tier gives you a public URL like `https://your-app.onrender.com`

## Admin Features
- Set school name
- Activate/deactivate morning routes
- Add/edit/delete teachers and routes
- Generate daily duty roster (auto-skips weekends)
- Mark absent → auto-suggests replacements
- View full audit log
- Manage admin accounts (Coordinator / Headteacher / IT)

## Allocation Rules
1. Teacher who worked yesterday is rested today
2. Teacher must rotate through ALL routes before repeating any
3. No teacher dominates a single route
4. Morning routes only run when activated by admin
