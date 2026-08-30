"""Detector contract (master prompt section 24.4).

A detector is a near-pure domain service: it takes an immutable reconciliation manifest
and an injected `as_of`, reads tenant-scoped source records, and returns typed results.
It never sends a message, never mutates a source record, and never reaches the network.

Every result carries the rule code and version so the decision can be reproduced later,
and every non-match carries a skip reason so "nothing found" is distinguishable from
"could not decide".
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal


class SkipReason:
    """Controlled codes for a candidate the detector declined to flag."""

    NOT_COMPLETED = "not_completed"
    NOT_BILLABLE = "not_billable"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    DELAY_NOT_ELAPSED = "delay_not_elapsed"
    NO_SERVICE_OBLIGATION = "no_service_obligation"
    CONTRACT_NOT_ACTIVE = "contract_not_active"
    BILLING_BASIS_UNSUPPORTED = "billing_basis_unsupported"
    AUTHORIZATION_MISSING = "authorization_missing"
    INVOICE_PRESENT = "invoice_present"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    ACCOUNTING_STALE = "accounting_stale"
    OPERATIONS_STALE = "operations_stale"
    BLOCKING_RECONCILIATION_ISSUE = "blocking_reconciliation_issue"
    ALREADY_REPRESENTED = "already_represented"


@dataclass(frozen=True)
class FinancialInputs:
    """Everything needed to reproduce a candidate-value calculation."""

    basis: str
    candidate_value: Decimal | None
    assumptions: dict[str, object]


@dataclass
class DetectionResult:
    """Section 24.4: what every detector returns for one evaluated subject."""

    matched: bool
    rule_code: str
    rule_version: int
    subject_id: str
    service_date: dt.date | None = None
    fingerprint_inputs: dict[str, str] = field(default_factory=dict)
    source_version_ids: list[str] = field(default_factory=list)
    freshness_status: str = "unknown"
    severity: str = "medium"
    deadline_at: dt.datetime | None = None
    explanation_code: str = ""
    explanation: str = ""
    recommended_next_action: str = ""
    recommended_next_action_explanation: str = ""
    financial: FinancialInputs | None = None
    skip_reason: str = ""

    @property
    def fingerprint(self) -> str:
        """Stable deduplication hash (section 18).

        Built from organization, rule, source object, service occurrence, and rule
        version. Two evaluations of the same occurrence dedup; a new occurrence for the
        same work order, or a rule-version bump, produces a new fingerprint.
        """
        payload = json.dumps(self.fingerprint_inputs, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class DetectorOutput:
    """Aggregate of one detector's evaluation of one manifest."""

    rule_code: str
    rule_version: int
    as_of: dt.datetime
    results: list[DetectionResult] = field(default_factory=list)
    scanned: int = 0
    freshness: dict[str, str] = field(default_factory=dict)

    @property
    def matches(self) -> list[DetectionResult]:
        return [r for r in self.results if r.matched]

    @property
    def skip_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            if not result.matched and result.skip_reason:
                counts[result.skip_reason] = counts.get(result.skip_reason, 0) + 1
        return counts
