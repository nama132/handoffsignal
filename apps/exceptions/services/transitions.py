"""The one place ExceptionCase.state changes (master prompt section 23).

"Use one transition service. Do not set ExceptionCase.state directly from a view, admin
action, detector, or task."

Every transition:
  * locks the case row and re-checks the caller's role under that organization,
  * requires the caller's expected version to match (optimistic concurrency, section 19),
  * validates the transition against the state machine and its required data,
  * writes the timeline event and the audit event in the SAME transaction,
  * and only then authorizes the model to accept the new state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.audit import models as audit
from apps.exceptions.models import (
    REVENUE_DISMISSAL_CODES,
    REVENUE_RESOLUTION_CODES,
    CaseState,
    ExceptionCase,
    ExceptionEvent,
    ExceptionType,
)
from apps.organizations.models import Membership
from apps.organizations.policy import Denied, require
from apps.organizations.roles import Action, Role


class TransitionError(Exception):
    """A transition that the state machine, its data rules, or versioning refuses."""


class StaleVersion(TransitionError):
    """The caller's expected version no longer matches: someone else acted first."""


#: The state machine from the section 23 diagram. Only the edges are encoded here;
#: role and data requirements are checked separately below.
ALLOWED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {
        (CaseState.NEW, CaseState.ACKNOWLEDGED),
        (CaseState.NEW, CaseState.DISMISSED),
        (CaseState.ACKNOWLEDGED, CaseState.ACTION_PENDING),
        (CaseState.ACKNOWLEDGED, CaseState.ESCALATED),
        (CaseState.ACKNOWLEDGED, CaseState.DISMISSED),
        (CaseState.ACKNOWLEDGED, CaseState.RESOLVED),
        (CaseState.ACTION_PENDING, CaseState.WAITING_EXTERNAL),
        (CaseState.ACTION_PENDING, CaseState.RESOLVED),
        (CaseState.ACTION_PENDING, CaseState.ESCALATED),
        (CaseState.ACTION_PENDING, CaseState.DISMISSED),
        (CaseState.WAITING_EXTERNAL, CaseState.ACTION_PENDING),
        (CaseState.WAITING_EXTERNAL, CaseState.RESOLVED),
        (CaseState.WAITING_EXTERNAL, CaseState.ESCALATED),
        (CaseState.WAITING_EXTERNAL, CaseState.DISMISSED),
        (CaseState.ESCALATED, CaseState.ACTION_PENDING),
        (CaseState.ESCALATED, CaseState.RESOLVED),
        (CaseState.ESCALATED, CaseState.DISMISSED),
    }
)

#: Edges that Phase 4 can actually drive for a revenue case. `waiting_external` needs
#: an approved handoff (Phase 5/6); it is encoded above for fidelity but has no trigger.
PHASE_4_REACHABLE_TARGETS: frozenset[str] = frozenset(
    {
        CaseState.ACKNOWLEDGED,
        CaseState.ACTION_PENDING,
        CaseState.ESCALATED,
        CaseState.RESOLVED,
        CaseState.DISMISSED,
    }
)


@dataclass(frozen=True)
class TransitionRequest:
    case_id: uuid.UUID
    expected_version: int
    to_state: str
    reason_code: str = ""
    note: str = ""
    owner_membership_id: uuid.UUID | None = None
    request_id: str = ""


def _roles_for(case: ExceptionCase, to_state: str) -> frozenset[str]:
    """Section 23 transition table, specialised for a revenue case.

    A finance reviewer may acknowledge and resolve a revenue case (line 1345, 1350);
    operations roles may not resolve it. Owner may do both.
    """
    if case.exception_type != ExceptionType.REVENUE_COMPLETED_UNBILLED:
        # Route B has no other type; refuse rather than guess a role set.
        return frozenset()
    if to_state == CaseState.RESOLVED:
        return frozenset({Role.OWNER, Role.FINANCE_REVIEWER})
    if to_state == CaseState.DISMISSED:
        return frozenset({Role.OWNER, Role.FINANCE_REVIEWER})
    return frozenset({Role.OWNER, Role.FINANCE_REVIEWER, Role.OPERATIONS_MANAGER})


def _require_role(membership: Membership, roles: frozenset[str]) -> None:
    require(membership, Action.VIEW_ORGANIZATION)  # membership/org state checks
    if not (membership.active_roles & roles):
        raise Denied(f"Role not permitted for this transition: requires one of {sorted(roles)}")


def _validate_data(case: ExceptionCase, req: TransitionRequest) -> None:
    if req.to_state == CaseState.RESOLVED:
        if req.reason_code not in REVENUE_RESOLUTION_CODES:
            raise TransitionError(
                "A resolution requires a resolution code valid for a revenue case."
            )
        if not req.note.strip():
            raise TransitionError("A resolution requires a reason note.")
    elif req.to_state == CaseState.DISMISSED:
        if req.reason_code not in REVENUE_DISMISSAL_CODES:
            raise TransitionError("A dismissal requires a dismissal code valid for a revenue case.")
        if not req.note.strip():
            raise TransitionError("A dismissal requires a reason note.")
    elif req.to_state == CaseState.ESCALATED:
        if not req.note.strip():
            raise TransitionError("An escalation requires a reason.")
        if req.owner_membership_id is None:
            raise TransitionError("An escalation requires a target owner.")
    elif req.to_state == CaseState.ACTION_PENDING:
        if req.owner_membership_id is None and case.owner_membership_id is None:
            raise TransitionError("Action pending requires an owner.")


@transaction.atomic
def transition(*, membership: Membership, req: TransitionRequest) -> ExceptionCase:
    """Apply one guarded transition. Raises rather than partially applying."""
    case = (
        ExceptionCase.objects.select_for_update()
        .filter(organization_id=membership.organization_id, id=req.case_id)
        .first()
    )
    if case is None:
        # Cross-tenant or unknown: indistinguishable, per section 17 rule 8.
        raise ExceptionCase.DoesNotExist

    if case.version != req.expected_version:
        raise StaleVersion(
            f"Case is at version {case.version}; you acted on {req.expected_version}."
        )

    if (case.state, req.to_state) not in ALLOWED_EDGES:
        raise TransitionError(f"No transition from {case.state} to {req.to_state}.")

    _require_role(membership, _roles_for(case, req.to_state))
    _validate_data(case, req)

    if req.owner_membership_id is not None:
        owner = Membership.objects.filter(
            organization_id=membership.organization_id, id=req.owner_membership_id, is_active=True
        ).first()
        if owner is None:
            raise TransitionError("The target owner must be an active member of this organization.")
        case.owner_membership = owner

    from_state = case.state
    now = timezone.now()
    case.state = req.to_state
    case.version += 1
    if req.to_state == CaseState.ACKNOWLEDGED and case.first_acknowledged_at is None:
        case.first_acknowledged_at = now
        if case.owner_membership_id is None:
            case.owner_membership = membership  # explicit self-assignment on acknowledge
    if req.to_state == CaseState.RESOLVED:
        case.resolved_at = now
        case.resolution_code = req.reason_code
        case.reason_text = req.note.strip()
    if req.to_state == CaseState.DISMISSED:
        case.dismissal_code = req.reason_code
        case.reason_text = req.note.strip()

    case._state_change_authorized = True
    case.save()

    ExceptionEvent.objects.create(
        organization=case.organization,
        exception_case=case,
        event_type="transition",
        from_state=from_state,
        to_state=req.to_state,
        actor_kind=ExceptionEvent.ActorKind.MEMBERSHIP,
        actor_membership=membership,
        reason_code=req.reason_code,
        note=req.note.strip()[:1000],
        request_id=req.request_id,
        case_version=case.version,
        metadata={
            "from_state": from_state,
            "to_state": req.to_state,
            "object_version": case.version,
        },
    )
    audit.record(
        organization=case.organization,
        action=f"case.transition.{req.to_state}",
        object_type="exceptions.ExceptionCase",
        object_id=case.id,
        actor_membership=membership,
        request_id=req.request_id,
        metadata={
            "from_state": from_state,
            "to_state": req.to_state,
            "reason_code": req.reason_code,
            "case_number": case.case_number,
            "object_version": case.version,
        },
    )
    return case


@transaction.atomic
def assign_owner(
    *,
    membership: Membership,
    case_id: uuid.UUID,
    expected_version: int,
    owner_membership_id: uuid.UUID,
    request_id: str = "",
) -> ExceptionCase:
    """Change the owner without changing state. Still versioned and audited."""
    case = (
        ExceptionCase.objects.select_for_update()
        .filter(organization_id=membership.organization_id, id=case_id)
        .first()
    )
    if case is None:
        raise ExceptionCase.DoesNotExist
    if case.version != expected_version:
        raise StaleVersion(f"Case is at version {case.version}; you acted on {expected_version}.")
    if case.is_terminal:
        raise TransitionError("A resolved or dismissed case cannot be reassigned.")
    _require_role(
        membership, frozenset({Role.OWNER, Role.FINANCE_REVIEWER, Role.OPERATIONS_MANAGER})
    )

    owner = Membership.objects.filter(
        organization_id=membership.organization_id, id=owner_membership_id, is_active=True
    ).first()
    if owner is None:
        raise TransitionError("The target owner must be an active member of this organization.")

    previous = case.owner_membership_id
    case.owner_membership = owner
    case.version += 1
    case.save()

    ExceptionEvent.objects.create(
        organization=case.organization,
        exception_case=case,
        event_type="owner_assigned",
        actor_kind=ExceptionEvent.ActorKind.MEMBERSHIP,
        actor_membership=membership,
        request_id=request_id,
        case_version=case.version,
        metadata={"changed_fields": ["owner_membership"], "object_version": case.version},
    )
    audit.record(
        organization=case.organization,
        action="case.assign_owner",
        object_type="exceptions.ExceptionCase",
        object_id=case.id,
        actor_membership=membership,
        request_id=request_id,
        metadata={
            "changed_fields": ["owner_membership"],
            "object_version": case.version,
            "case_number": case.case_number,
        },
    )
    _ = previous
    return case
