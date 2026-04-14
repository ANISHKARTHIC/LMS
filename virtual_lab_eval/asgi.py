"""ASGI config for virtual_lab_eval project."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "virtual_lab_eval.settings")

application = get_asgi_application()
