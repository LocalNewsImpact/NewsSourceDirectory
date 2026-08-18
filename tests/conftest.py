import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list[dict[str, str]]:
    with (FIXTURES / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="session")
def outlets() -> list[dict[str, str]]:
    """A sample of the real prototype data, chosen to contain every known defect."""
    return _load("outlets_sample.csv")


@pytest.fixture(scope="session")
def coverage() -> list[dict[str, str]]:
    return _load("coverage_sample.csv")


@pytest.fixture
def clean_outlet() -> dict[str, str]:
    return {
        "outlet_id": "1",
        "outlet_name": "Columbia Missourian",
        "canonical_url": "https://www.columbiamissourian.com/",
        "domain": "columbiamissourian.com",
        "primary_medium": "Newspaper",
        "states": "Missouri",
        "cities": "Columbia",
        "counties": "Boone",
        "needs_review": "",
    }
