import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOYED_APP = REPO_ROOT / 'sts-platform' / 'app.py'


class RootEntrypointTests(unittest.TestCase):
    def test_root_app_module_delegates_to_the_deployed_app(self):
        env = os.environ.copy()
        env.update({
            'STS_SKIP_DB_INIT': '1',
            'DATABASE_URL': 'sqlite:///:memory:',
            'SECRET_KEY': 'test-only-key',
        })
        result = subprocess.run(
            [sys.executable, '-c', 'import app; print(app.__file__)'],
            cwd=str(REPO_ROOT), env=env,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(), DEPLOYED_APP.resolve())


if __name__ == '__main__':
    unittest.main()
