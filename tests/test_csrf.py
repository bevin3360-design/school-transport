import os
import re
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import app, db


class CsrfProtectionTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        app.config['WTF_CSRF_ENABLED'] = False

    def issue_token(self):
        page = self.client.get('/login')
        match = re.search(
            r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True))
        self.assertIsNotNone(match, 'token meta tag missing from the sign-in page')
        return match.group(1)

    def test_pages_expose_the_token_and_fetch_helper(self):
        page = self.client.get('/login')
        body = page.get_data(as_text=True)
        self.assertIn('name="csrf-token"', body)
        self.assertIn('/static/js/csrf.js', body)

    def test_state_changing_request_without_a_token_is_rejected(self):
        response = self.client.post('/api/admin/login', json={
            'username': 'nobody', 'password': 'whatever1'
        })
        self.assertEqual(response.status_code, 400)

    def test_state_changing_request_with_a_token_reaches_the_view(self):
        token = self.issue_token()
        response = self.client.post('/api/admin/login', json={
            'username': 'nobody', 'password': 'whatever1'
        }, headers={'X-CSRFToken': token})
        self.assertEqual(response.status_code, 401)

    def test_read_requests_do_not_need_a_token(self):
        self.assertEqual(self.client.get('/api/session').status_code, 200)


if __name__ == '__main__':
    unittest.main()
