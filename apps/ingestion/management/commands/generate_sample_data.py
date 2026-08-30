"""Generate the synthetic Atlas CSV fixtures and blank templates.

Section 28: "The demo management command must generate valid example files and
intentionally invalid fixtures."

The three sources use deliberately different identifier dialects, because the wedge is
cross-system reconciliation and a shared key would prove nothing:

    contract_register       UPPER-HYPHEN-TOKENS   a register a person maintains
    opsplatform_workorders  00000000              a leaked autoincrement primary key
    ar_ledger               8000nnnn-<epoch>      an accounting list id

The accounting export deliberately carries **no work-order identifier**, so
reconciliation must run on the confirmed customer/site crosswalk plus service date.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ingestion.contracts.registry import CONTRACTS
from apps.ingestion.parsing import write_csv
from apps.organizations.management.commands._guards import refuse_outside_local_or_demo

OUTPUT_DIR = Path(settings.BASE_DIR) / "sample_data" / "atlas_facility_services"

#: (customer id, customer name, site id, site name, site_type, region, contract id,
#:  obligation id, uninvoiced delay days, scope_kind)
#: Capital Retail's quarterly burnish is CONTRACT-SCOPE periodic work; only the other two
#: obligations are authorized extras, so only they require authorization evidence.
SITES = [
    (
        "MERIDIAN-PG",
        "Meridian Property Group",
        "MBC-NOVA-01",
        "Meridian Business Center",
        "office",
        "NOVA-CENTRAL",
        "CT-2026-MERIDIAN-01",
        "OB-MBC-PCC-01",
        7,
        "authorized_extra",
    ),
    (
        "CAPITAL-RP",
        "Capital Retail Partners",
        "CRG-DCCORE-01",
        "Capital Retail Gallery",
        "retail",
        "DC-CORE",
        "CT-2026-CAPITAL-01",
        "OB-CRG-PERIODIC-01",
        10,
        "periodic",
    ),
    (
        "POTOMAC-LOG",
        "Potomac Logistics LLC",
        "PDA-MDMONT-01",
        "Potomac Distribution Annex",
        "light_industrial",
        "MD-MONTGOMERY",
        "CT-2026-POTOMAC-01",
        "OB-PDA-EXTRA-01",
        5,
        "authorized_extra",
    ),
]

#: canonical -> ops platform identifier (a leaked autoincrement key, no type prefix)
OPS_IDS = {
    "MERIDIAN-PG": "00084120",
    "CAPITAL-RP": "00084307",
    "POTOMAC-LOG": "00084915",
    "MBC-NOVA-01": "00093011",
    "CRG-DCCORE-01": "00093044",
    "PDA-MDMONT-01": "00093088",
    "CT-2026-MERIDIAN-01": "00077450",
    "CT-2026-CAPITAL-01": "00077612",
    "CT-2026-POTOMAC-01": "00077880",
    "OB-MBC-PCC-01": "00060213",
    "OB-CRG-PERIODIC-01": "00060402",
    "OB-PDA-EXTRA-01": "00060577",
}

#: canonical -> accounting list id
AR_IDS = {
    "MERIDIAN-PG": "80000042-1739216455",
    "CAPITAL-RP": "80000058-1739216455",
    "POTOMAC-LOG": "80000071-1739216455",
    "MBC-NOVA-01": "80000107-1739216455",
    "CRG-DCCORE-01": "80000119-1739216455",
    "PDA-MDMONT-01": "80000124-1739216455",
}


def _sites_contracts_rows() -> list[dict[str, Any]]:
    rows = []
    for (
        cust_id,
        cust_name,
        site_id,
        site_name,
        site_type,
        region,
        contract_id,
        obligation_id,
        delay,
        scope_kind,
    ) in SITES:
        rows.append(
            {
                "source_system": "contract_register",
                "customer_external_id": cust_id,
                "customer_name": cust_name,
                "site_external_id": site_id,
                "site_name": site_name,
                "site_type": site_type,
                "site_timezone": "America/New_York",
                "region_code": region,
                "contract_external_id": contract_id,
                "contract_status": "active",
                "starts_on": "2026-01-01",
                "ends_on": "",
                "service_obligation_external_id": obligation_id,
                "service_obligation_label": f"{site_name} authorized extra work",
                "service_type": "janitorial_detail",
                "scope_kind": scope_kind,
                "service_window_start": "18:00",
                "service_window_end": "02:00",
                "service_weekdays": "mon,tue,wed,thu,fri",
                "role_code": "cleaner",
                "required_coverage_count": 2,
                "substitution_required_when_below_count": "true",
                "billing_basis": "fixed_work_order",
                "default_bill_rate": "",
                "currency": "USD",
                "extra_work_requires_authorization": "true"
                if scope_kind == "authorized_extra"
                else "false",
                "uninvoiced_delay_days": delay,
                # Journey A / C columns: present in the contract, unused under Route B.
                "no_show_grace_minutes": 15,
                "replacement_buffer_minutes": 30,
                "attendance_escalation_minutes": 45,
                "deficiency_response_minutes": 60,
                "deficiency_correction_minutes": 240,
                "weekly_hours_warning_threshold": "40.0",
                "weekly_hours_hard_limit": "",
                "workweek_start_weekday": "monday",
                "workweek_start_local_time": "00:00",
                "availability_evidence_policy": "conflicts_only",
                "client_notification_required": "true",
                "required_qualification_code": "",
                "required_program_version": "",
                "requirement_kind": "",
                "requirement_effective_from": "",
                "requirement_effective_to": "",
            }
        )
    return rows


def _crosswalk_rows() -> list[dict[str, Any]]:
    """Map both alias dialects onto the contract register's canonical identifiers.

    One row is deliberately omitted — the Potomac site in the accounting dialect — so a
    dependent invoice row quarantines and the identity queue has something real to show.
    """
    rows = []
    for canonical, alias in OPS_IDS.items():
        entity_type = (
            "customer"
            if canonical.endswith(("-PG", "-RP", "-LOG"))
            else "contract"
            if canonical.startswith("CT-")
            else "service_obligation"
            if canonical.startswith("OB-")
            else "site"
        )
        rows.append(
            {
                "entity_type": entity_type,
                "alias_source_system": "opsplatform_workorders",
                "alias_external_id": alias,
                "canonical_source_system": "contract_register",
                "canonical_external_id": canonical,
                "match_method": "deterministic_exact",
                "approval_reference": "",
                "mapping_note": "",
            }
        )
    for canonical, alias in AR_IDS.items():
        if canonical == "PDA-MDMONT-01":
            continue  # deliberately unmapped: blocks a dependent invoice row
        entity_type = "customer" if canonical.endswith(("-PG", "-RP", "-LOG")) else "site"
        rows.append(
            {
                "entity_type": entity_type,
                "alias_source_system": "ar_ledger",
                "alias_external_id": alias,
                "canonical_source_system": "contract_register",
                "canonical_external_id": canonical,
                "match_method": "partner_canonical_key",
                "approval_reference": "ATLAS-MAP-2026-01",
                "mapping_note": "",
            }
        )
    return rows


def _work_order_rows() -> list[dict[str, Any]]:
    """Four work orders, three of which are deliberate controls."""
    common = {
        "source_system": "opsplatform_workorders",
        "record_type": "work_order",
        "customer_source_system": "opsplatform_workorders",
        "site_source_system": "opsplatform_workorders",
        "contract_source_system": "opsplatform_workorders",
        "service_obligation_source_system": "opsplatform_workorders",
        "severity": "",
        "received_at": "",
        "response_due_at": "",
        "correction_due_at": "",
        "corrected_at": "",
        "approved_hours": "",
        "bill_rate": "",
        "source_updated_at": "",
        "source_as_of_at": "2026-08-20T06:00:00-04:00",
    }
    return [
        # 1. The star case: completed, authorized, billable, $480, never invoiced.
        {
            **common,
            "record_external_id": "00518774",
            "customer_external_id": OPS_IDS["MERIDIAN-PG"],
            "site_external_id": OPS_IDS["MBC-NOVA-01"],
            "contract_external_id": OPS_IDS["CT-2026-MERIDIAN-01"],
            "service_obligation_external_id": OPS_IDS["OB-MBC-PCC-01"],
            "summary": "Post-construction detail clean, floors 3-4",
            "occurred_at": "2026-07-06T18:00:00-04:00",
            "scheduled_at": "2026-07-06T18:00:00-04:00",
            "completed_at": "2026-07-06T23:30:00-04:00",
            "source_status": "completed",
            "billable": "true",
            "authorization_required": "true",
            "authorization_reference": "MER-AUTH-8841",
            "authorized_at": "2026-07-02T14:12:00-04:00",
            "billing_basis": "fixed_work_order",
            "approved_fixed_amount": "480.00",
        },
        # 2. Negative control: already invoiced, so no candidate may be created.
        {
            **common,
            "record_external_id": "00518801",
            "customer_external_id": OPS_IDS["CAPITAL-RP"],
            "site_external_id": OPS_IDS["CRG-DCCORE-01"],
            "contract_external_id": OPS_IDS["CT-2026-CAPITAL-01"],
            "service_obligation_external_id": OPS_IDS["OB-CRG-PERIODIC-01"],
            "summary": "Quarterly floor burnish",
            "occurred_at": "2026-07-11T19:00:00-04:00",
            "scheduled_at": "2026-07-11T19:00:00-04:00",
            "completed_at": "2026-07-11T22:00:00-04:00",
            "source_status": "completed",
            "billable": "true",
            "authorization_required": "false",
            "authorization_reference": "",
            "authorized_at": "",
            "billing_basis": "fixed_work_order",
            "approved_fixed_amount": "610.00",
        },
        # 3. Negative control: extra work with authorization required but NOT obtained.
        {
            **common,
            "record_external_id": "00518830",
            "customer_external_id": OPS_IDS["POTOMAC-LOG"],
            "site_external_id": OPS_IDS["PDA-MDMONT-01"],
            "contract_external_id": OPS_IDS["CT-2026-POTOMAC-01"],
            "service_obligation_external_id": OPS_IDS["OB-PDA-EXTRA-01"],
            "summary": "Dock degrease requested on site",
            "occurred_at": "2026-07-14T20:00:00-04:00",
            "scheduled_at": "",
            "completed_at": "2026-07-14T23:00:00-04:00",
            "source_status": "completed",
            "billable": "true",
            "authorization_required": "true",
            "authorization_reference": "",
            "authorized_at": "",
            "billing_basis": "fixed_work_order",
            "approved_fixed_amount": "295.00",
        },
        # 4. Negative control: still open, so nothing is owed yet.
        {
            **common,
            "record_external_id": "00518902",
            "customer_external_id": OPS_IDS["MERIDIAN-PG"],
            "site_external_id": OPS_IDS["MBC-NOVA-01"],
            "contract_external_id": OPS_IDS["CT-2026-MERIDIAN-01"],
            "service_obligation_external_id": OPS_IDS["OB-MBC-PCC-01"],
            "summary": "Carpet extraction, lobby",
            "occurred_at": "2026-08-18T18:00:00-04:00",
            "scheduled_at": "2026-08-18T18:00:00-04:00",
            "completed_at": "",
            "source_status": "open",
            "billable": "true",
            "authorization_required": "false",
            "authorization_reference": "",
            "authorized_at": "",
            "billing_basis": "fixed_work_order",
            "approved_fixed_amount": "",
        },
    ]


def _invoice_rows() -> list[dict[str, Any]]:
    """The accounting ledger. Note: no work-order identifier on any row."""
    common = {
        "source_system": "ar_ledger",
        "work_order_source_system": "",
        "work_order_external_id": "",
        "customer_source_system": "ar_ledger",
        "site_source_system": "ar_ledger",
        "currency": "USD",
        "source_updated_at": "",
        "source_as_of_at": "2026-08-20T06:00:00-04:00",
    }
    return [
        # Matches work order 2 by customer/site/service date: the already-invoiced control.
        {
            **common,
            "invoice_external_id": "80000913-1751903102",
            "customer_external_id": AR_IDS["CAPITAL-RP"],
            "site_external_id": AR_IDS["CRG-DCCORE-01"],
            "service_date": "2026-07-11",
            "invoice_reference": "3391",
            "invoice_amount": "610.00",
            "invoiced_at": "2026-07-18T09:02:00-04:00",
            "invoice_status": "posted",
            "payment_external_id": "",
            "payment_reference": "",
            "collected_amount": "",
            "collected_at": "",
            "payment_status": "",
        },
        # An unrelated older invoice, partially collected across two payment rows.
        {
            **common,
            "invoice_external_id": "80000877-1748102400",
            "customer_external_id": AR_IDS["MERIDIAN-PG"],
            "site_external_id": AR_IDS["MBC-NOVA-01"],
            "service_date": "2026-06-02",
            "invoice_reference": "3310",
            "invoice_amount": "1200.00",
            "invoiced_at": "2026-06-09T09:00:00-04:00",
            "invoice_status": "posted",
            "payment_external_id": "90001-1748900000",
            "payment_reference": "ACH-5512",
            "collected_amount": "700.00",
            "collected_at": "2026-06-30T09:00:00-04:00",
            "payment_status": "posted",
        },
        {
            **common,
            "invoice_external_id": "80000877-1748102400",
            "customer_external_id": AR_IDS["MERIDIAN-PG"],
            "site_external_id": AR_IDS["MBC-NOVA-01"],
            "service_date": "2026-06-02",
            "invoice_reference": "3310",
            "invoice_amount": "1200.00",
            "invoiced_at": "2026-06-09T09:00:00-04:00",
            "invoice_status": "posted",
            "payment_external_id": "90002-1749900000",
            "payment_reference": "ACH-5599",
            "collected_amount": "500.00",
            "collected_at": "2026-07-12T09:00:00-04:00",
            "payment_status": "posted",
        },
        # Quarantine control: this row references the Potomac site in the accounting
        # dialect, whose crosswalk row is deliberately absent. The row must NOT import;
        # it must land in the identity-resolution queue for an owner to confirm.
        {
            **common,
            "invoice_external_id": "80000944-1753000000",
            "customer_external_id": AR_IDS["POTOMAC-LOG"],
            "site_external_id": AR_IDS["PDA-MDMONT-01"],
            "service_date": "2026-07-14",
            "invoice_reference": "3402",
            "invoice_amount": "295.00",
            "invoiced_at": "2026-07-22T09:00:00-04:00",
            "invoice_status": "posted",
            "payment_external_id": "",
            "payment_reference": "",
            "collected_amount": "",
            "collected_at": "",
            "payment_status": "",
        },
    ]


INVALID_FIXTURES: dict[str, tuple[str, str]] = {
    "invalid_missing_column.csv": (
        "entity_type,alias_source_system,alias_external_id\ncustomer,ar_ledger,X-1\n",
        "missing_required_column",
    ),
    "invalid_blank_required.csv": (
        "entity_type,alias_source_system,alias_external_id,canonical_source_system,"
        "canonical_external_id,match_method,approval_reference,mapping_note\n"
        "customer,ar_ledger,,contract_register,MERIDIAN-PG,manual,REF-1,\n",
        "blank_required_value",
    ),
    "invalid_enum.csv": (
        "entity_type,alias_source_system,alias_external_id,canonical_source_system,"
        "canonical_external_id,match_method,approval_reference,mapping_note\n"
        "spaceship,ar_ledger,X-1,contract_register,MERIDIAN-PG,manual,REF-1,\n",
        "invalid_enum",
    ),
    "invalid_naive_timestamp.csv": (
        "source_system,record_type,record_external_id,customer_source_system,customer_external_id,"
        "site_source_system,site_external_id,contract_source_system,contract_external_id,"
        "service_obligation_source_system,service_obligation_external_id,summary,severity,"
        "occurred_at,received_at,scheduled_at,completed_at,source_status,billable,"
        "authorization_required,authorization_reference,authorized_at,billing_basis,"
        "approved_fixed_amount,approved_hours,bill_rate,response_due_at,correction_due_at,"
        "corrected_at,source_updated_at,source_as_of_at\n"
        "opsplatform_workorders,work_order,00519999,opsplatform_workorders,00084120,"
        "opsplatform_workorders,00093011,opsplatform_workorders,00077450,,,No offset on this one,,"
        "2026-07-06T18:00:00,,,,open,true,false,,,fixed_work_order,,,,,,,,2026-08-20T06:00:00-04:00\n",
        "timezone_required",
    ),
    "invalid_quality_record_type.csv": (
        "source_system,record_type,record_external_id,customer_source_system,customer_external_id,"
        "site_source_system,site_external_id,contract_source_system,contract_external_id,"
        "service_obligation_source_system,service_obligation_external_id,summary,severity,"
        "occurred_at,received_at,scheduled_at,completed_at,source_status,billable,"
        "authorization_required,authorization_reference,authorized_at,billing_basis,"
        "approved_fixed_amount,approved_hours,bill_rate,response_due_at,correction_due_at,"
        "corrected_at,source_updated_at,source_as_of_at\n"
        "opsplatform_workorders,inspection_failure,00520001,opsplatform_workorders,00084120,"
        "opsplatform_workorders,00093011,opsplatform_workorders,00077450,,,Journey C is unbuilt,high,"
        "2026-07-06T18:00:00-04:00,2026-07-06T19:00:00-04:00,,,open,,,,,,,,,,,,,"
        "2026-08-20T06:00:00-04:00\n",
        "invalid_enum (Journey C record types are rejected under Route B)",
    ),
}


class Command(BaseCommand):
    help = "Write the synthetic Atlas CSV fixtures, blank templates, and invalid examples."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--output", default=str(OUTPUT_DIR))

    def handle(self, *args: Any, **options: Any) -> None:
        refuse_outside_local_or_demo("generate_sample_data")
        out = Path(options["output"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "templates").mkdir(exist_ok=True)
        (out / "invalid").mkdir(exist_ok=True)

        datasets = {
            "sites_contracts.csv": ("sites_contracts", _sites_contracts_rows()),
            "entity_crosswalk.csv": ("entity_crosswalk", _crosswalk_rows()),
            "work_orders_service_events.csv": ("work_orders_service_events", _work_order_rows()),
            "invoice_status.csv": ("invoice_status", _invoice_rows()),
        }

        for filename, (kind, rows) in datasets.items():
            columns = [c.name for c in CONTRACTS[kind].columns]
            (out / filename).write_text(write_csv(rows, columns), encoding="utf-8")
            # A blank template with the header row only, for a partner to fill in.
            (out / "templates" / filename).write_text(write_csv([], columns), encoding="utf-8")
            self.stdout.write(f"  {filename}: {len(rows)} row(s)")

        for filename, (content, reason) in INVALID_FIXTURES.items():
            (out / "invalid" / filename).write_text(content, encoding="utf-8")
            self.stdout.write(f"  invalid/{filename}: expects {reason}")

        (out / "README.md").write_text(_readme(), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote synthetic fixtures to {out}"))


def _readme() -> str:
    return """# Atlas Facility Services — synthetic fixtures

Every value here is fictional. No real customer, site, worker, amount, or address
appears in any of these files.

## Load order

Section 27 requires `sites_contracts`, then `entity_crosswalk`, then the fact files.
A fact that arrives before its canonical entity stays quarantined rather than being
guessed.

1. `sites_contracts.csv` — establishes canonical customers, sites, contracts, obligations
2. `entity_crosswalk.csv` — maps the two alias dialects onto those canonical records
3. `work_orders_service_events.csv` — operations facts
4. `invoice_status.csv` — accounting facts

## Three identifier dialects

| Source | Shape | Example |
|---|---|---|
| `contract_register` | UPPER-HYPHEN-TOKENS | `MBC-NOVA-01` |
| `opsplatform_workorders` | zero-padded integer | `00093011` |
| `ar_ledger` | accounting list id | `80000107-1739216455` |

The accounting export carries **no work-order identifier** on any row. Reconciliation
therefore has to run on the confirmed customer/site crosswalk plus service date — which
is the point. If the invoice carried the operations key, the demo would be a join on a
shared column and would prove nothing.

## Deliberate controls

| Fixture | Purpose |
|---|---|
| Work order `00518774` | Completed, authorized, billable, $480, no matching invoice |
| Work order `00518801` | Already invoiced — must never become a candidate |
| Work order `00518830` | Authorization required but absent — must not be billable |
| Work order `00518902` | Still open — nothing owed yet |
| Missing `ar_ledger` crosswalk for `PDA-MDMONT-01` | Invoice `80000944-1753000000` references it, so that row quarantines into the identity queue |
| `invalid/` | One file per representative error code |

The `$480.00` figure is a narrative placeholder. It is not an estimate of anything and
must never be cited as one.
"""
