"""Roles, actions, and the permission matrix.

This module is a direct transcription of the tables in master prompt section 9.3. It
is data, not logic: `apps/organizations/policy.py` interprets it. Keeping the matrix
declarative means a permission question is answered by reading one table rather than
by tracing conditionals through views.

Two rules govern every entry:

* **Deny by default.** An action not listed for a role is denied. There is no implicit
  inheritance between roles: a tenant owner is not "operations manager plus more" by
  construction, it is listed explicitly wherever it applies.
* **Visibility is not authority** (line 378). An identity or reconciliation decision
  that crosses the operational/financial boundary requires the owner; broader power is
  never inferred from being able to see a record.
"""

from __future__ import annotations

from django.db import models


class Role(models.TextChoices):
    """The five demo roles (section 9.3).

    `OWNER` is the tenant-administration role. It is distinct from Django's `is_staff`,
    which is platform administration and must never be granted through tenant UI
    (section 22.2).
    """

    OWNER = "owner", "Organization owner"
    OPERATIONS_MANAGER = "operations_manager", "Operations manager"
    SUPERVISOR = "supervisor", "Site supervisor"
    FINANCE_REVIEWER = "finance_reviewer", "Finance reviewer"
    AUDITOR = "auditor", "Auditor / read-only"


class Action(models.TextChoices):
    """Every decision-critical action named in section 9.3.

    Actions whose objects do not exist yet are still declared here so the matrix stays
    a faithful copy of the specification, and so a later phase cannot quietly invent a
    permission. `PHASE_2_ENFORCEABLE` below records which are reachable today.
    """

    # --- configuration (owner only) ---
    MANAGE_MEMBERSHIPS = "manage_memberships", "Manage memberships and role grants"
    MANAGE_DATA_SOURCES = "manage_data_sources", "Manage data sources"
    MANAGE_SOURCE_PRECEDENCE = "manage_source_precedence", "Manage source precedence rules"
    MANAGE_SITE_RULES = "manage_site_rules", "Manage site operational rules"

    # --- import (Phase 3) ---
    UPLOAD_PREVIEW_FILES = "upload_preview_files", "Upload and preview operational files"
    COMMIT_OPERATIONAL_IMPORT = (
        "commit_operational_import",
        "Commit workers/schedule/time/service_events import",
    )
    COMMIT_FINANCIAL_IMPORT = "commit_financial_import", "Commit contracts or invoice_status import"
    COMMIT_CROSSWALK_IMPORT = "commit_crosswalk_import", "Commit identity-crosswalk import"

    # --- identity and reconciliation ---
    RESOLVE_IDENTITY = "resolve_identity", "Manually confirm or reject an identity mapping"
    RESOLVE_OPERATIONAL_RECONCILIATION = (
        "resolve_operational_reconciliation",
        "Resolve a non-financial reconciliation issue",
    )
    RESOLVE_FINANCIAL_RECONCILIATION = (
        "resolve_financial_reconciliation",
        "Resolve a contract/rate/invoice reconciliation issue",
    )

    # --- cases (Phase 4) ---
    ACT_ON_CASE = "act_on_case", "Act on an attendance or quality case"

    # --- approvals and export (Phases 5 and 6) ---
    APPROVE_OPERATIONAL_HANDOFF = (
        "approve_operational_handoff",
        "Approve an operational draft handoff",
    )
    APPROVE_INVOICE_READY = "approve_invoice_ready", "Approve invoice-ready value"
    EXPORT_FINANCE_CSV = "export_finance_csv", "Export or download the approved finance CSV"

    # --- read ---
    VIEW_ORGANIZATION = "view_organization", "View the organization shell and its records"


#: Roles permitted to perform each action. Absence means denied.
#: Transcribed from the section 9.3 matrix (lines 364-376).
ACTION_ROLES: dict[str, frozenset[str]] = {
    Action.MANAGE_MEMBERSHIPS: frozenset({Role.OWNER}),
    Action.MANAGE_DATA_SOURCES: frozenset({Role.OWNER}),
    Action.MANAGE_SOURCE_PRECEDENCE: frozenset({Role.OWNER}),
    Action.MANAGE_SITE_RULES: frozenset({Role.OWNER}),
    Action.UPLOAD_PREVIEW_FILES: frozenset({Role.OWNER, Role.OPERATIONS_MANAGER}),
    Action.COMMIT_OPERATIONAL_IMPORT: frozenset({Role.OWNER, Role.OPERATIONS_MANAGER}),
    Action.COMMIT_FINANCIAL_IMPORT: frozenset({Role.OWNER, Role.FINANCE_REVIEWER}),
    # Owner only: this crosses the operational/financial identity boundary (line 372).
    Action.COMMIT_CROSSWALK_IMPORT: frozenset({Role.OWNER}),
    Action.RESOLVE_IDENTITY: frozenset({Role.OWNER}),
    Action.RESOLVE_OPERATIONAL_RECONCILIATION: frozenset({Role.OWNER, Role.OPERATIONS_MANAGER}),
    Action.RESOLVE_FINANCIAL_RECONCILIATION: frozenset({Role.OWNER, Role.FINANCE_REVIEWER}),
    Action.ACT_ON_CASE: frozenset({Role.OWNER, Role.OPERATIONS_MANAGER, Role.SUPERVISOR}),
    Action.APPROVE_OPERATIONAL_HANDOFF: frozenset({Role.OWNER, Role.OPERATIONS_MANAGER}),
    Action.APPROVE_INVOICE_READY: frozenset({Role.OWNER, Role.FINANCE_REVIEWER}),
    Action.EXPORT_FINANCE_CSV: frozenset({Role.OWNER, Role.FINANCE_REVIEWER}),
    Action.VIEW_ORGANIZATION: frozenset(
        {
            Role.OWNER,
            Role.OPERATIONS_MANAGER,
            Role.SUPERVISOR,
            Role.FINANCE_REVIEWER,
            Role.AUDITOR,
        }
    ),
}

#: Actions whose permission additionally narrows to the sites a supervisor was granted.
#: A supervisor with no active MembershipSiteGrant reaches no site at all (line 378):
#: an empty grant set means no access, never tenant-wide access.
SITE_SCOPED_ACTIONS: frozenset[str] = frozenset(
    {
        Action.ACT_ON_CASE,
        Action.RESOLVE_OPERATIONAL_RECONCILIATION,
    }
)

#: Actions that are never permitted to a read-only auditor, restated explicitly so a
#: future edit to ACTION_ROLES cannot silently grant one (section 33.3, line 2084:
#: "An auditor cannot POST any state-changing action").
STATE_CHANGING_ACTIONS: frozenset[str] = frozenset(ACTION_ROLES) - {Action.VIEW_ORGANIZATION}

#: Actions reachable in Phase 2, because their objects exist. The rest are declared
#: above but have no route yet; asserting this keeps the matrix honest about what is
#: actually enforced today versus merely written down.
PHASE_2_ENFORCEABLE: frozenset[str] = frozenset(
    {
        Action.VIEW_ORGANIZATION,
        Action.MANAGE_MEMBERSHIPS,
        Action.MANAGE_DATA_SOURCES,
        Action.MANAGE_SOURCE_PRECEDENCE,
        Action.RESOLVE_IDENTITY,
        Action.RESOLVE_OPERATIONAL_RECONCILIATION,
        Action.RESOLVE_FINANCIAL_RECONCILIATION,
    }
)
