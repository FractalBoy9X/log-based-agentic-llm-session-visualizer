"""
ASGI config for Agentic Thinking Visualization project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agentic_app.settings')

application = get_asgi_application()
