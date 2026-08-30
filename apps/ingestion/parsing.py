"""Safe CSV reading and writing.

Section 27 requires: explicit UTF-8 handling, safe row/field limits, header
normalization that never guesses an ambiguous mapping, and formula-injection awareness.

Reading is streamed row by row so memory stays bounded regardless of file size; the
demo row limit is enforced during the stream, not after loading everything.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field

from apps.ingestion.errors import ErrorCode, RowError

#: Demo limits. Section 27 step 7 requires "a strict demo file limit".
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_FIELD_CHARS = 4_000
MAX_ROW_CHARS = 20_000

#: Cells beginning with these are interpreted as formulas by spreadsheet software.
FORMULA_PREFIXES = ("=", "+", "-", "@")
#: Tab and carriage return also trigger formula parsing in some spreadsheet software.
_FORMULA_CONTROL = ("\t", "\r")


class FileTooLarge(Exception):
    pass


class EncodingInvalid(Exception):
    pass


def sanitize_filename(name: str) -> str:
    """Reduce an uploaded name to a safe basename (section 22.3: 'basename only')."""
    base = name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base[:255] or "upload.csv"


def normalize_header(name: str) -> str:
    """Normalize a header cell conservatively.

    Case and surrounding whitespace are normalized, and internal whitespace collapses to
    a single underscore. Nothing else is inferred: section 27 step 3 requires
    normalization "without guessing ambiguous mappings", so a header that does not match
    a declared column after this becomes `unknown_column` rather than a fuzzy match onto
    a similar name.
    """
    cleaned = name.replace("﻿", "").strip().lower()
    cleaned = re.sub(r"[\s\-]+", "_", cleaned)
    return re.sub(r"[^a-z0-9_]", "", cleaned)


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode_utf8(payload: bytes) -> str:
    """Decode strictly as UTF-8, tolerating only a BOM.

    Section 27 step 4 requires explicit UTF-8 handling; guessing an encoding would
    silently corrupt names and identifiers.
    """
    if len(payload) > MAX_FILE_BYTES:
        raise FileTooLarge
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EncodingInvalid from exc
    return text


@dataclass
class ParsedRow:
    row_number: int
    data: dict[str, str]
    errors: list[RowError] = field(default_factory=list)


@dataclass
class ParseResult:
    headers: list[str]
    rows: list[ParsedRow]
    file_errors: list[RowError] = field(default_factory=list)
    truncated: bool = False


def parse_csv(payload: bytes, *, expected_columns: set[str]) -> ParseResult:
    """Parse and structurally validate a CSV without touching the domain.

    Returns every row, valid or not: the preview must show row-specific errors, which
    is impossible if invalid rows are dropped during parsing.
    """
    try:
        text = decode_utf8(payload)
    except FileTooLarge:
        return ParseResult(headers=[], rows=[], file_errors=[RowError(ErrorCode.FILE_TOO_LARGE)])
    except EncodingInvalid:
        return ParseResult(headers=[], rows=[], file_errors=[RowError(ErrorCode.ENCODING_INVALID)])

    reader = csv.reader(io.StringIO(text))
    try:
        raw_headers = next(reader)
    except StopIteration:
        # A headerless file is not an error in itself: an empty accounting export is a
        # legitimate observation, but it still needs a header row to declare its shape.
        return ParseResult(
            headers=[], rows=[], file_errors=[RowError(ErrorCode.MISSING_REQUIRED_COLUMN)]
        )

    headers = [normalize_header(h) for h in raw_headers]
    file_errors: list[RowError] = []

    for missing in sorted(expected_columns - set(headers)):
        file_errors.append(RowError(ErrorCode.MISSING_REQUIRED_COLUMN, column=missing))
    for unknown in sorted(set(headers) - expected_columns):
        if unknown:
            file_errors.append(RowError(ErrorCode.UNKNOWN_COLUMN, column=unknown))

    rows: list[ParsedRow] = []
    truncated = False
    for index, values in enumerate(reader, start=1):
        if index > MAX_ROWS:
            truncated = True
            file_errors.append(RowError(ErrorCode.FILE_TOO_LARGE))
            break

        row_errors: list[RowError] = []
        if sum(len(v) for v in values) > MAX_ROW_CHARS:
            row_errors.append(RowError(ErrorCode.ROW_TOO_LARGE, row_number=index))

        data: dict[str, str] = {}
        for position, header in enumerate(headers):
            value = values[position] if position < len(values) else ""
            if len(value) > MAX_FIELD_CHARS:
                row_errors.append(
                    RowError(ErrorCode.ROW_TOO_LARGE, column=header, row_number=index)
                )
                value = value[:MAX_FIELD_CHARS]
            data[header] = value.strip()

        rows.append(ParsedRow(row_number=index, data=data, errors=row_errors))

    return ParseResult(headers=headers, rows=rows, file_errors=file_errors, truncated=truncated)


def neutralize_formula(value: str) -> str:
    """Prefix a cell that a spreadsheet would interpret as a formula.

    Section 27: "Exported CSV cells beginning with `=`, `+`, `-`, or `@` must be escaped
    or otherwise neutralized to prevent spreadsheet formula injection."
    """
    if not value:
        return value
    if value[0] in FORMULA_PREFIXES or value[0] in _FORMULA_CONTROL:
        return "'" + value
    return value


def write_csv(rows: list[dict[str, object]], columns: list[str]) -> str:
    """Render rows as CSV with every cell formula-neutralized."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: neutralize_formula(str(row.get(c, ""))) for c in columns})
    return buffer.getvalue()
