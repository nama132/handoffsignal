"""Single-line structured JSON logging.

Master prompt section 20: never log request bodies, secrets, message content, full
phone numbers, addresses, or tokens. This formatter emits a fixed, allowlisted set
of fields so a stray object cannot leak into the log stream.
"""

from __future__ import annotations

import json
import logging

# Fields copied from a LogRecord. Anything not listed here is never emitted.
_ALLOWED_RECORD_FIELDS = ("name", "levelname", "module", "funcName", "lineno")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _ALLOWED_RECORD_FIELDS:
            value = getattr(record, field, None)
            if value is not None and field not in ("name", "levelname"):
                payload[field] = value

        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id

        if record.exc_info:
            payload["exc_type"] = getattr(record.exc_info[0], "__name__", "Exception")

        return json.dumps(payload, default=str, separators=(",", ":"))
