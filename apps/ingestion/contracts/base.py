"""Column specifications and typed coercion shared by every CSV contract.

Section 28 defines each file as a table of columns with a required/conditional flag and
a validation meaning. This module turns that table into data so a contract is declared
rather than hand-coded, and so the required-column set can be checked mechanically.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from apps.ingestion.errors import ErrorCode, RowError

_TRUE = {"true", "1", "yes", "y"}
_FALSE = {"false", "0", "no", "n"}


class Requirement:
    REQUIRED = "required"
    OPTIONAL = "optional"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class Column:
    name: str
    requirement: str = Requirement.REQUIRED
    kind: str = "text"
    choices: tuple[str, ...] = ()
    max_length: int = 200
    #: Human-readable meaning, surfaced in the downloadable template documentation.
    meaning: str = ""
    #: Set for columns the contract must accept but Route B does not persist.
    unused_in_route_b: bool = False

    @property
    def is_required(self) -> bool:
        return self.requirement == Requirement.REQUIRED


@dataclass
class RowResult:
    values: dict[str, object] = field(default_factory=dict)
    errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not [e for e in self.errors if not e.is_warning]


def coerce_boolean(raw: str) -> bool:
    """Strict boolean parsing. Anything outside the two vocabularies is an error."""
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError


def coerce_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError from exc
    if not value.is_finite():
        raise ValueError
    return value


def coerce_date(raw: str) -> dt.date:
    return dt.date.fromisoformat(raw.strip())


def coerce_time(raw: str) -> dt.time:
    return dt.time.fromisoformat(raw.strip())


def coerce_timestamp(raw: str) -> dt.datetime:
    """Parse an ISO 8601 timestamp that MUST carry an explicit offset.

    Section 18: "Import timestamps must declare a timezone or use an explicitly
    selected site timezone; never silently assume the server timezone." A naive
    timestamp therefore raises a distinct error so the message can say why.
    """
    parsed = dt.datetime.fromisoformat(raw.strip())
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise TimezoneMissing
    return parsed


class TimezoneMissing(ValueError):
    """Raised when a timestamp parsed but carried no UTC offset."""


_COERCERS: dict[str, Callable[[str], object]] = {
    "text": lambda raw: raw.strip(),
    "boolean": coerce_boolean,
    "decimal": coerce_decimal,
    "date": coerce_date,
    "time": coerce_time,
    "timestamp": coerce_timestamp,
    "integer": lambda raw: int(raw.strip()),
}

_ERROR_FOR_KIND = {
    "boolean": ErrorCode.INVALID_BOOLEAN,
    "decimal": ErrorCode.INVALID_DECIMAL,
    "integer": ErrorCode.INVALID_DECIMAL,
    "date": ErrorCode.INVALID_DATE,
    "time": ErrorCode.INVALID_TIMESTAMP,
    "timestamp": ErrorCode.INVALID_TIMESTAMP,
}


@dataclass(frozen=True)
class Contract:
    """One CSV file type."""

    kind: str
    columns: tuple[Column, ...]
    #: Extra checks that need more than one column.
    row_validators: tuple[Callable[[dict[str, object]], list[RowError]], ...] = ()

    @property
    def column_names(self) -> set[str]:
        return {c.name for c in self.columns}

    @property
    def required_columns(self) -> set[str]:
        return {c.name for c in self.columns if c.is_required}

    def column(self, name: str) -> Column | None:
        for candidate in self.columns:
            if candidate.name == name:
                return candidate
        return None

    def validate_row(self, raw: dict[str, str], row_number: int) -> RowResult:
        """Coerce and validate one row against this contract."""
        result = RowResult()
        for column in self.columns:
            raw_value = raw.get(column.name, "")

            if raw_value == "":
                if column.is_required:
                    result.errors.append(
                        RowError(
                            ErrorCode.BLANK_REQUIRED_VALUE,
                            column=column.name,
                            row_number=row_number,
                        )
                    )
                result.values[column.name] = None
                continue

            if len(raw_value) > column.max_length:
                result.errors.append(
                    RowError(ErrorCode.ROW_TOO_LARGE, column=column.name, row_number=row_number)
                )
                continue

            if column.choices and raw_value.strip() not in column.choices:
                result.errors.append(
                    RowError(ErrorCode.INVALID_ENUM, column=column.name, row_number=row_number)
                )
                continue

            try:
                result.values[column.name] = _COERCERS[column.kind](raw_value)
            except TimezoneMissing:
                result.errors.append(
                    RowError(ErrorCode.TIMEZONE_REQUIRED, column=column.name, row_number=row_number)
                )
            except (ValueError, TypeError):
                result.errors.append(
                    RowError(
                        _ERROR_FOR_KIND.get(column.kind, ErrorCode.INVALID_ENUM),
                        column=column.name,
                        row_number=row_number,
                    )
                )

        if result.is_valid:
            for validator in self.row_validators:
                for error in validator(result.values):
                    result.errors.append(
                        RowError(error.code, column=error.column, row_number=row_number)
                    )
        return result


def require_end_after_start(
    start_key: str, end_key: str
) -> Callable[[dict[str, object]], list[RowError]]:
    def validator(values: dict[str, object]) -> list[RowError]:
        start, end = values.get(start_key), values.get(end_key)
        if start is not None and end is not None and end <= start:  # type: ignore[operator]
            return [RowError(ErrorCode.END_BEFORE_START, column=end_key)]
        return []

    return validator


def require_together(
    trigger_key: str, *required_keys: str
) -> Callable[[dict[str, object]], list[RowError]]:
    """Conditional columns: if the trigger is present, the others must be too."""

    def validator(values: dict[str, object]) -> list[RowError]:
        if values.get(trigger_key) in (None, ""):
            return []
        return [
            RowError(ErrorCode.BLANK_REQUIRED_VALUE, column=key)
            for key in required_keys
            if values.get(key) in (None, "")
        ]

    return validator
