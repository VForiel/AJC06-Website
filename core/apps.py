from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from . import security  # noqa: F401  (branche les récepteurs des échecs de connexion)
