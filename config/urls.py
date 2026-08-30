"""Root URL configuration.

Phase 1 exposes only authentication, a foundation-status page, and health probes.
There is deliberately no public signup, seed, demo-reset, or business route
(section 29; Phase 1 implementation rules).
"""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from apps.common import health
from apps.dashboard import views as dashboard_views
from apps.exceptions import views as exception_views
from apps.ingestion import views as ingestion_views
from apps.organizations import views as organization_views
from apps.recovery import views as recovery_views

app_patterns = (
    [
        path("", exception_views.cockpit, name="home"),
        path("organization/", dashboard_views.home, name="organization"),
        path("foundation-status/", dashboard_views.home, name="foundation-status"),
    ],
    "app",
)

recovery_patterns = (
    [
        path("recovery-ledger/", recovery_views.ledger, name="ledger"),
        path(
            "recovery-ledger/<uuid:item_id>/approve/",
            recovery_views.approve_invoice_ready,
            name="approve-invoice-ready",
        ),
        path("recovery-ledger/export/", recovery_views.export_csv, name="export"),
        path(
            "exports/<uuid:export_id>/download/",
            recovery_views.export_download,
            name="export-download",
        ),
    ],
    "recovery",
)

exception_patterns = (
    [
        path("exceptions/", exception_views.inbox, name="inbox"),
        path("exceptions/<uuid:case_id>/", exception_views.case_detail, name="case-detail"),
        path(
            "exceptions/<uuid:case_id>/acknowledge/",
            exception_views.acknowledge,
            name="acknowledge",
        ),
        path(
            "exceptions/<uuid:case_id>/assign-owner/",
            exception_views.assign_owner,
            name="assign-owner",
        ),
        path(
            "exceptions/<uuid:case_id>/transition/", exception_views.transition, name="transition"
        ),
    ],
    "exceptions",
)

ingestion_patterns = (
    [
        path("imports/", ingestion_views.import_list, name="import-list"),
        path("imports/new/", ingestion_views.import_new, name="import-new"),
        path(
            "imports/<uuid:batch_id>/preview/",
            ingestion_views.import_preview,
            name="import-preview",
        ),
        path(
            "imports/<uuid:batch_id>/commit/", ingestion_views.import_commit, name="import-commit"
        ),
        path(
            "imports/<uuid:batch_id>/results/",
            ingestion_views.import_results,
            name="import-results",
        ),
        path("identity-resolution/", ingestion_views.identity_queue, name="identity-queue"),
        path(
            "identity-resolution/<uuid:issue_id>/resolve/",
            ingestion_views.identity_resolve,
            name="identity-resolve",
        ),
        path(
            "reconciliation-issues/",
            ingestion_views.reconciliation_queue,
            name="reconciliation-queue",
        ),
        path(
            "reconciliation-issues/<uuid:issue_id>/resolve/",
            ingestion_views.reconciliation_resolve,
            name="reconciliation-resolve",
        ),
    ],
    "ingestion",
)

organization_patterns = (
    [
        path(
            "select-organization/",
            organization_views.select_organization,
            name="select-organization",
        ),
    ],
    "organizations",
)

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="app:foundation-status", permanent=False)),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    # Django 5.2 requires POST for logout.
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("app/", include(app_patterns, namespace="app")),
    path("app/", include(organization_patterns, namespace="organizations")),
    path("app/", include(ingestion_patterns, namespace="ingestion")),
    path("app/", include(exception_patterns, namespace="exceptions")),
    path("app/", include(recovery_patterns, namespace="recovery")),
    path("health/live/", health.liveness, name="health-live"),
    path("health/ready/", health.readiness, name="health-ready"),
]
