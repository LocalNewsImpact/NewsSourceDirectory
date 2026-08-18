"""Data-quality rules for the News Source Directory.

The same rules run in CI against fixtures and at publish time against the live
export, so a defect cannot reach sites.json by taking a different code path.
"""

from checks.rules import ALL_RULES, Severity, Violation, run_all

__all__ = ["ALL_RULES", "Severity", "Violation", "run_all"]
