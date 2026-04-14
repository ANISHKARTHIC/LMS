"""WSGI config for virtual_lab_eval project."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "virtual_lab_eval.settings")

application = get_wsgi_application()
