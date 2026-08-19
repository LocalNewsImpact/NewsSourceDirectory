"""Grant people admin access, idempotently.

    python manage.py ensure_admin matt@localnewsimpact.org
    python manage.py ensure_admin a@... b@... c@localnewsimpact.org
    python manage.py ensure_admin --staff-only editor@localnewsimpact.org

Accounts can be created before anyone signs in: SOCIALACCOUNT_EMAIL_AUTHENTICATION
lets a Google identity attach to a matching address on first login. So adding an
editor is one command, not a sign-in-then-promote dance.

Rerunning is safe. An existing account is granted the flags it lacks and nothing
else about it changes — a rerun never demotes anyone or resets a password.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create or promote admin accounts by email address."

    def add_arguments(self, parser):
        parser.add_argument("emails", nargs="+", help="one or more addresses")
        parser.add_argument(
            "--staff-only", action="store_true", help="admin access without superuser rights"
        )
        parser.add_argument(
            "--set-password",
            action="store_true",
            help="generate a password and print it once, for use without Google sign-in",
        )

    def handle(self, *args, **options):
        domain = getattr(settings, "ALLOWED_GOOGLE_DOMAIN", "")
        emails = [e.strip().lower() for e in options["emails"] if e.strip()]

        outside = [e for e in emails if domain and not e.endswith(f"@{domain}")]
        if outside:
            # Refused as a set rather than one at a time: a half-applied batch is
            # worse than none, because nobody can tell which half.
            raise CommandError(
                f"outside {domain}: {', '.join(outside)}. Google sign-in would refuse "
                "these, so the accounts would be unusable."
            )

        User = get_user_model()
        results = []

        with transaction.atomic():
            for email in emails:
                user = User.objects.filter(email__iexact=email).first()
                created = user is None
                if created:
                    user = User(username=email, email=email)

                user.email = email
                user.is_staff = True
                user.is_superuser = not options["staff_only"]

                password = None
                if options["set_password"]:
                    password = secrets.token_urlsafe(16)
                    user.set_password(password)
                elif created:
                    # No password: the account exists for Google to attach to and
                    # cannot be logged into directly.
                    user.set_unusable_password()

                user.save()
                results.append((email, created, password))

        role = "staff" if options["staff_only"] else "superuser"
        for email, created, password in results:
            self.stdout.write(
                self.style.SUCCESS(f"  {email}: {'created' if created else 'updated'} as {role}")
            )
            if password:
                self.stdout.write(self.style.WARNING(f"    password: {password}"))

        self.stdout.write(f"\n{len(results)} account(s) ready.")
        if not options["set_password"]:
            self.stdout.write("They sign in with Google; no password is set.")
