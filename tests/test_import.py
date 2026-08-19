"""Importing a source spreadsheet.

Coverage records are evidence: imported verbatim, never corrected on the way in.
These tests pin what "verbatim" has to mean in practice.
"""

import csv

import pytest
from django.core.management import call_command

from directory.models import CoverageRecord, SourceImport

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

HEADERS = [
    "outlet_id",
    "outlet_name_raw",
    "url",
    "medium",
    "state",
    "county",
    "city",
    "notes",
    "mun_id",
    "gnis",
    "ownership",
    "source_file",
]


@pytest.fixture
def csv_file(tmp_path):
    def write(rows, name="sample.csv"):
        path = tmp_path / name
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, HEADERS)
            writer.writeheader()
            for row in rows:
                writer.writerow({h: row.get(h, "") for h in HEADERS})
        return str(path)

    return write


def run(path, **kwargs):
    call_command("import_source", path, verbosity=0, **kwargs)


def test_rows_become_coverage_records(csv_file):
    run(csv_file([{"outlet_name_raw": "A"}, {"outlet_name_raw": "B"}]))
    assert CoverageRecord.objects.count() == 2


def test_the_import_is_recorded_as_a_batch(csv_file):
    """A bad import has to be reversible as a unit."""
    run(csv_file([{"outlet_name_raw": "A"}]))
    batch = SourceImport.objects.get()
    assert batch.filename == "sample.csv"
    assert batch.row_count == 1


def test_source_values_are_not_normalised(csv_file):
    """'Type' in the medium column is wrong, and must survive anyway — the
    rebuild decides what to do with it, and a reviewer needs to see it."""
    run(csv_file([{"outlet_name_raw": "A", "medium": "Type", "state": "MS"}]))
    record = CoverageRecord.objects.get()
    assert record.medium_raw == "Type"
    assert record.state_raw == "MS"


@pytest.mark.parametrize("nullish", ["nan", "NaN", "None", "n/a", "-", ""])
def test_placeholders_become_empty_rather_than_text(csv_file, nullish):
    """Storing the string 'nan' as a city is how 'nan' ends up on a public page."""
    run(csv_file([{"outlet_name_raw": "A", "city": nullish}]))
    assert CoverageRecord.objects.get().city == ""


def test_rows_without_a_name_are_skipped(csv_file):
    """A row naming no outlet cannot be reviewed or attributed."""
    run(csv_file([{"outlet_name_raw": "A"}, {"outlet_name_raw": ""}]))
    assert CoverageRecord.objects.count() == 1


def test_the_prototype_grouping_is_kept_but_not_used(csv_file):
    """Recorded only so the rebuild can be measured against it."""
    run(csv_file([{"outlet_name_raw": "A", "outlet_id": "439"}]))
    record = CoverageRecord.objects.get()
    assert record.legacy_outlet_id == "439"
    assert record.outlet is None


def test_dry_run_writes_nothing(csv_file):
    run(csv_file([{"outlet_name_raw": "A"}]), dry_run=True)
    assert CoverageRecord.objects.count() == 0
    assert SourceImport.objects.count() == 0


def test_replace_removes_the_previous_import_of_that_file(csv_file):
    path = csv_file([{"outlet_name_raw": "A"}])
    run(path)
    run(path, replace=True)
    assert CoverageRecord.objects.count() == 1
    assert SourceImport.objects.count() == 1


def test_importing_twice_without_replace_duplicates(csv_file):
    """Documented rather than prevented: two files can legitimately describe the
    same outlets, and silently dropping the second would lose evidence."""
    path = csv_file([{"outlet_name_raw": "A"}])
    run(path)
    run(path)
    assert CoverageRecord.objects.count() == 2


def test_an_overlong_value_is_truncated_not_dropped(csv_file):
    """Losing a whole row to one long field would lose an outlet."""
    run(csv_file([{"outlet_name_raw": "A", "city": "x" * 400}]))
    record = CoverageRecord.objects.get()
    assert record.outlet_name_raw == "A"
    assert len(record.city) <= 128


def test_a_missing_file_fails_clearly(tmp_path):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="no such file"):
        run(str(tmp_path / "absent.csv"))


def test_a_file_without_the_name_column_is_refused(tmp_path):
    from django.core.management.base import CommandError

    path = tmp_path / "wrong.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(CommandError, match="missing required column"):
        run(str(path))
