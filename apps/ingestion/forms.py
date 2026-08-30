"""Import forms.

Section 27 step 6: the user must declare observation mode and bounded coverage
scope/interval/completeness on the form. Nothing is inferred from the filename, the row
count, or the file's freshness.
"""

from __future__ import annotations

from django import forms

from apps.ingestion.contracts.registry import CONTRACTS
from apps.ingestion.models import DataSource, ImportBatch, ImportCoverage
from apps.ingestion.parsing import MAX_FILE_BYTES
from apps.ingestion.services.coverage import RECORD_FAMILIES


class ImportUploadForm(forms.Form):
    """Upload one supported file with its coverage declaration."""

    source = forms.ModelChoiceField(queryset=DataSource.objects.none())
    kind = forms.ChoiceField(choices=[(k, k) for k in sorted(CONTRACTS)])
    upload = forms.FileField()
    source_as_of_at = forms.DateTimeField(
        help_text="When the source system produced this export. Must include a UTC offset."
    )
    observation_mode = forms.ChoiceField(choices=ImportBatch.ObservationMode.choices)
    coverage_start_at = forms.DateTimeField()
    coverage_end_at = forms.DateTimeField()
    completeness = forms.ChoiceField(choices=ImportCoverage.Completeness.choices)
    declaration_basis = forms.ChoiceField(choices=ImportCoverage.DeclarationBasis.choices)
    query_contract_code = forms.ChoiceField(
        choices=[("", "Not applicable")] + list(ImportCoverage.QueryContract.choices),
        required=False,
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["source"].queryset = DataSource.objects.filter(
                organization=organization
            ).order_by("system_key")

    def clean_upload(self):
        upload = self.cleaned_data["upload"]
        if upload.size > MAX_FILE_BYTES:
            raise forms.ValidationError(
                "This file exceeds the demo size limit. Export a narrower date range."
            )
        if not upload.name.lower().endswith(".csv"):
            raise forms.ValidationError("Only .csv files are accepted.")
        return upload

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("coverage_start_at"), cleaned.get("coverage_end_at")
        if start and end and end <= start:
            self.add_error("coverage_end_at", "Coverage must end after it starts.")

        source, kind = cleaned.get("source"), cleaned.get("kind")
        if source and kind and source.domain not in _DOMAINS_FOR_KIND.get(str(kind), ()):
            self.add_error(
                "source",
                "This source's domain does not match the selected file type.",
            )

        if cleaned.get("completeness") == ImportCoverage.Completeness.COMPLETE and source:
            if not source.is_authoritative:
                self.add_error(
                    "completeness",
                    "Only an authoritative source may declare complete coverage.",
                )
        return cleaned

    @property
    def record_family(self) -> str:
        return RECORD_FAMILIES[self.cleaned_data["kind"]][0]


#: Which source domain each file type may be imported into.
_DOMAINS_FOR_KIND: dict[str, tuple[str, ...]] = {
    "sites_contracts": (DataSource.Domain.CONTRACTS,),
    "entity_crosswalk": (DataSource.Domain.IDENTITY_CROSSWALK,),
    "work_orders_service_events": (DataSource.Domain.SERVICE_EVENTS,),
    "invoice_status": (DataSource.Domain.INVOICE_STATUS,),
}
