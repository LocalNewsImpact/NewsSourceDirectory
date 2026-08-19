"""Point django.contrib.sites at the real hostname.

    python manage.py configure_site --domain sources.localnewsimpact.org

Django ships Site 1 as `example.com`. allauth builds OAuth callback URLs from
it, so a fresh database sends Google a callback on example.com and the login
fails with nothing useful in the logs.

Idempotent, and run from the deploy so it cannot be forgotten on a rebuild.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Set the Site domain used to build OAuth callback URLs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            default="",
            help="defaults to ADMIN_HOST, then the first entry in ALLOWED_HOSTS",
        )
        parser.add_argument("--name", default="News Source Directory")

    def handle(self, *args, **options):
        domain = options["domain"].strip() or self._infer()
        if not domain or domain in {"*", "example.com"}:
            raise CommandError(
                "no usable domain — pass --domain, or set ADMIN_HOST on the service."
            )

        site, _ = Site.objects.get_or_create(pk=settings.SITE_ID)
        was = site.domain
        site.domain = domain
        site.name = options["name"]
        site.save()

        if was == domain:
            self.stdout.write(f"site {settings.SITE_ID} already {domain}")
        else:
            self.stdout.write(self.style.SUCCESS(f"site {settings.SITE_ID}: {was} -> {domain}"))

    @staticmethod
    def _infer() -> str:
        admin_host = os.environ.get("ADMIN_HOST", "").strip()
        if admin_host:
            return admin_host
        for host in settings.ALLOWED_HOSTS:
            # Skip wildcards and the Cloud Run URL suffix; neither is the
            # hostname a person types or that Google redirects back to.
            if host and not host.startswith((".", "*")):
                return host
        return ""
