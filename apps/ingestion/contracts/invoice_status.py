"""`invoice_status.csv` — section 28.7.

"This is a separate accounting-source export. It must not be merged into the work-order
file."

One row per invoice/payment relation. Repeated invoice fields across several payment
rows must agree exactly; the commit service normalizes one canonical invoice plus
distinct canonical payments and never counts the invoice amount per row.
"""

from __future__ import annotations

from apps.ingestion.contracts.base import Column, Contract, Requirement, require_together

INVOICE_STATUSES = ("posted", "void", "disputed")
PAYMENT_STATUSES = ("posted", "reversed", "disputed")

CONTRACT = Contract(
    kind="invoice_status",
    columns=(
        Column("source_system", meaning="Accounting source namespace."),
        Column("invoice_external_id", meaning="Stable canonical invoice identity."),
        Column("work_order_source_system", Requirement.OPTIONAL),
        Column(
            "work_order_external_id",
            Requirement.OPTIONAL,
            meaning="Often absent: the accounting system need not know work orders.",
        ),
        Column("customer_source_system"),
        Column("customer_external_id"),
        Column("site_source_system"),
        Column("site_external_id"),
        Column("service_date", kind="date", meaning="Site-local date used in reconciliation."),
        Column("invoice_reference"),
        Column("invoice_amount", kind="decimal"),
        Column("invoiced_at", kind="timestamp"),
        Column("invoice_status", choices=INVOICE_STATUSES),
        Column("payment_external_id", Requirement.CONDITIONAL),
        Column("payment_reference", Requirement.OPTIONAL),
        Column("collected_amount", Requirement.CONDITIONAL, kind="decimal"),
        Column("collected_at", Requirement.CONDITIONAL, kind="timestamp"),
        Column("payment_status", Requirement.CONDITIONAL, choices=PAYMENT_STATUSES),
        Column("currency", choices=("USD",)),
        Column("source_updated_at", Requirement.OPTIONAL, kind="timestamp"),
        Column("source_as_of_at", kind="timestamp"),
    ),
    row_validators=(
        require_together(
            "payment_external_id", "collected_amount", "collected_at", "payment_status"
        ),
        require_together("work_order_external_id", "work_order_source_system"),
    ),
)
