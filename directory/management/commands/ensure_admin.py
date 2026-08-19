"""Grant a person admin access, idempotently.

    python manage.py ensure_admin matt@localnewsimpact.org

Run as a Cloud Run job against production, or locally against the dev database.
Rerunning is safe: an existing account is granted the flags it lacks and nothing
else about it changes.

Sign-in goes through Google once an OAuth client is configured, at which point
the account here is what the Google identity attaches to. Until then, pass
--set-password to give it a password so someone can actually get in.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or promote an admin account by email address."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument(
            "--staff-only",
            action="store_true",
            help="admin access without superuser rights",
        )
        parser.add_argument(
            "--set-password",
            action="store_true",
            help="generate a password and print it once (for use before Google sign-in exists)",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        domain = getattr(settings, "ALLOWED_GOOGLE_DOMAIN", "")
        if domain and not email.endswith(f"@{domain}"):
            raise CommandError(
                f"{email} is outside {domain}. Google sign-in would refuse it, so an "
                "account here would be unusable."
            )

        User = get_user_model()
        user, created = User.objects.get_or_create(username=email, defaults={"email": email})

        user.email = email
        user.is_staff = True
        user.is_superuser = not options["staff_only"]

        password = None
        if options["set_password"] or created:
            if options["set_password"]:
                password = secrets.token_urlsafe(16)
                user.set_password(password)
            elif created:
                # Created without a password: the account exists for Google to
                # attach to and cannot be logged into directly.
                user.set_unusable_password()

        user.save()

        what = "created" if created else "updated"
        role = "staff" if options["staff_only"] else "superuser"
        self.stdout.write(self.style.SUCCESS(f"{email} {what} as {role}"))

        if password:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"  password: {password}"))
            self.stdout.write("  Shown once. Change it after signing in.")
        elif created:
            self.stdout.write(
                "  No password set — sign in with Google, or rerun with --set-password."
            )
