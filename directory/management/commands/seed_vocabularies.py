"""Populate the controlled vocabularies.

Without this a fresh database has empty dropdowns, and the first editor to open
the admin invents their own spellings — which is how the source data ended up
with "Public Broadcasting" beside "Public Broadcast".

Idempotent: safe to rerun, and it never renames what someone has since edited.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from directory.models import Category, Medium, State

# Six media carry all but a handful of the source records. See
# docs/schema-decisions.md for the counts.
MEDIA = [
    ("newspaper", "Newspaper", 10),
    ("television", "Television", 20),
    ("radio", "Radio", 30),
    ("online", "Online", 40),
    ("magazine", "Magazine", 50),
    ("public-broadcasting", "Public Broadcasting", 60),
]

# The second axis the source data conflated with medium.
CATEGORIES = [
    ("ethnic", "Ethnic Outlet"),
    ("network-site", "Network Site"),
    ("student", "Student Publication"),
    ("nonprofit", "Nonprofit"),
]

STATES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]


class Command(BaseCommand):
    help = "Create the controlled vocabularies: media, categories and states."

    @transaction.atomic
    def handle(self, *args, **options):
        made = {"media": 0, "categories": 0, "states": 0}

        for slug, label, order in MEDIA:
            _, created = Medium.objects.get_or_create(
                slug=slug, defaults={"label": label, "sort_order": order}
            )
            made["media"] += created

        for slug, label in CATEGORIES:
            _, created = Category.objects.get_or_create(slug=slug, defaults={"label": label})
            made["categories"] += created

        for code, name in STATES:
            _, created = State.objects.get_or_create(code=code, defaults={"name": name})
            made["states"] += created

        for kind, n in made.items():
            self.stdout.write(f"  {kind}: {n} created, {0 if n else 'already present'}")
        self.stdout.write(self.style.SUCCESS("vocabularies ready"))
