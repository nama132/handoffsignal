"""The data dictionary must match the migrations.

Section 48: "Documentation must describe what exists, not planned behavior as though
already implemented." This test fails when a model is added without an entry, and when
the dictionary describes a model or table that no longer exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings

DICTIONARY = Path(settings.BASE_DIR) / "docs" / "DATA_DICTIONARY.md"
V2_APP_LABELS = ("organizations", "operations", "ingestion")


@pytest.fixture(scope="module")
def dictionary_text() -> str:
    return DICTIONARY.read_text(encoding="utf-8")


def v2_models():  # type: ignore[no-untyped-def]
    for label in V2_APP_LABELS:
        yield from apps.get_app_config(label).get_models()


def test_dictionary_exists() -> None:
    assert DICTIONARY.is_file()


@pytest.mark.parametrize("model", list(v2_models()), ids=lambda m: m.__name__)
def test_every_model_is_documented(model, dictionary_text: str) -> None:  # type: ignore[no-untyped-def]
    assert model.__name__ in dictionary_text, (
        f"{model.__name__} has no data-dictionary entry. Add one to docs/DATA_DICTIONARY.md."
    )


@pytest.mark.parametrize("model", list(v2_models()), ids=lambda m: m.__name__)
def test_every_table_name_is_documented(model, dictionary_text: str) -> None:  # type: ignore[no-untyped-def]
    assert model._meta.db_table in dictionary_text, (
        f"Table {model._meta.db_table} is not named in the data dictionary."
    )


def test_documented_tables_all_exist() -> None:
    """The dictionary must not describe a table that was removed.

    Table names are read only from `###` heading lines. Scanning the whole document
    would mistake identifiers that merely share a prefix — the role code
    `operations_manager`, for instance — for table names.
    """
    import re

    documented: set[str] = set()
    for line in DICTIONARY.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            documented.update(
                re.findall(r"`((?:organizations|operations|ingestion)_[a-z_]+)`", line)
            )

    actual = {m._meta.db_table for m in v2_models()}
    assert documented, "No table names were found in the dictionary headings."
    stale = documented - actual
    assert not stale, f"Data dictionary describes tables that do not exist: {sorted(stale)}"


def test_route_b_omissions_are_recorded(dictionary_text: str) -> None:
    """Omitted models must be documented as omitted, not silently missing."""
    for omitted in ("Worker", "Shift", "TimeEntry", "QualityEvent", "SiteOperationalRule"):
        assert omitted in dictionary_text

    for deferred in ("ImportBatch", "ImportCoverage", "SourceRecordVersion", "ReconciliationRun"):
        assert deferred in dictionary_text


def test_er_diagram_is_present(dictionary_text: str) -> None:
    """A mermaid erDiagram renders in Markdown without adding a dependency."""
    assert "```mermaid" in dictionary_text
    assert "erDiagram" in dictionary_text
