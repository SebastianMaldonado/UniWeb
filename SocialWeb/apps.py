from django.apps import AppConfig
from django.conf import settings


class SocialwebConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'SocialWeb'

    def ready(self):  # Configure neomodel connection on app load
        try:
            from neomodel import config
            # Prefer settings.NEO4J_BOLT_URL; fallback to env if needed
            bolt_url = getattr(settings, 'NEO4J_BOLT_URL', None)
            if bolt_url:
                config.DATABASE_URL = bolt_url
        except Exception:
            # Avoid raising during collectstatic/checks if neomodel not installed yet
            pass
