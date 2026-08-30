"""Request correlation.

Every audit and timeline record carries a request ID (sections 22.5, 22.6). The
middleware assigns one per request so later phases can correlate a domain change
with the request that caused it. No request body is read or logged.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"
_MAX_INBOUND_LENGTH = 64


class RequestIDMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        # An inbound value is untrusted: accept it only if it is short and safe.
        if inbound and len(inbound) <= _MAX_INBOUND_LENGTH and inbound.replace("-", "").isalnum():
            request_id = inbound
        else:
            request_id = str(uuid.uuid4())

        request.request_id = request_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response
