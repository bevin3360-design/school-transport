"""Compatibility shim: the deployed application lives in sts-platform/app.py.

This file used to be a stale copy of the platform, which let an accidental
``gunicorn app:app`` run outdated code with an insecure fallback secret. It now
loads the deployed module so every entrypoint uses the maintained app.
"""
import importlib.util
import os
import sys

_PLATFORM_DIR = os.path.join(os.path.dirname(__file__), 'sts-platform')
if _PLATFORM_DIR not in sys.path:
    sys.path.insert(0, _PLATFORM_DIR)

_platform_path = os.path.join(_PLATFORM_DIR, 'app.py')
_spec = importlib.util.spec_from_file_location('_sts_platform_app', _platform_path)
_platform = importlib.util.module_from_spec(_spec)
sys.modules['_sts_platform_app'] = _platform
_spec.loader.exec_module(_platform)
sys.modules[__name__] = _platform
