"""
core_api/apps.py

Registers signals inside ready() to avoid circular imports.
IMPORTANT: INSTALLED_APPS in settings.py must use the full path:
    'core_api.apps.CoreApiConfig'
not just:
    'core_api'
Otherwise ready() is never called and signals won't fire.
"""

from django.apps import AppConfig


class CoreApiConfig(AppConfig):
    name = "core_api"
    verbose_name = "Core API"

    def ready(self):
        import core_api.signals  # noqa: F401