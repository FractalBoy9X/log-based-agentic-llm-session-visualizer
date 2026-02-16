"""
WSGI config for Agentic Thinking Visualization project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agentic_app.settings')

application = get_wsgi_application()
