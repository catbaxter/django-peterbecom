import os
import tempfile


REDIS_BACKENDS = {
    'master': 'redis://localhost:6379?socket_timeout=0.5&db=8'
}

CELERY_ALWAYS_EAGER = True
CELERY_EAGER_PROPAGATES_EXCEPTIONS = True


FSCACHE_ROOT = os.path.join(
    tempfile.gettempdir(),
    'test-peterbecom-fscache'
)