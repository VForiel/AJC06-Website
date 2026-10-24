"""Point d'entrée pour Phusion Passenger (hébergement mutualisé o2switch / cPanel « Setup Python App »)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402,F401
