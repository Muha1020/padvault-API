from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Users'

    def ready(self):
        import sys
        # Only start the scheduler when running the server, not during management commands
        skip_commands = {'migrate', 'makemigrations', 'shell', 'test', 'collectstatic'}
        if not any(cmd in sys.argv for cmd in skip_commands):
            from rent_core_service.scheduler import start
            start()
