from django.apps import AppConfig


class DirectoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "directory"
    verbose_name = "News source directory"

    def ready(self):
        # Import for the side effect of registering the model admins.
        from directory import admin  # noqa: F401
