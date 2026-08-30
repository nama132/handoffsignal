"""Foundation-status view.

Phase 1 deliverable: an authenticated page that truthfully states that no business
workflow exists yet. It must not imply detectors, imports, or cases are available.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def foundation_status(request: HttpRequest) -> HttpResponse:
    return render(request, "foundation_status.html")
