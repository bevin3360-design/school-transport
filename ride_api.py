"""Obsolete duplicate of sts-platform/ride_api.py.

The deployed ride-hailing blueprint lives in sts-platform/ride_api.py. This
module is disabled so an accidental root-level import cannot load an outdated
copy or bind the wrong SQLAlchemy instance.
"""
raise ImportError(
    'The ride-hailing blueprint lives in sts-platform/ride_api.py; '
    'import it from the platform directory instead.'
)
