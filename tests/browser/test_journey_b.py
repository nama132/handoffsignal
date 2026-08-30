"""Route B browser controls (master prompt sections 33.3, 30.5).

Section 33.3 asks Route B to automate "only the selected Journey B slice plus its
already-invoiced, insufficient-coverage, wrong-role, cross-tenant, replay, and 375px
controls" and explicitly forbids building fake Journey A/C paths to pad the list.
Each control below maps to one of those seven, and to nothing else.

These drive a real Chromium against a real server, so they assert what an operator
would actually see: a button that is absent rather than merely disabled, a denial that
does not name the object it is hiding, and a page that does not overflow on a phone.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="pytest-playwright is not installed")

from apps.exceptions.models import ExceptionCase, FinancialRecoveryItem  # noqa: E402
from apps.ingestion.models import ImportCoverage  # noqa: E402
from apps.organizations.management.commands.seed_demo import DEMO_PASSWORD  # noqa: E402
from apps.recovery.models import FinanceExport  # noqa: E402
from tests.phase6_helpers import loaded_atlas  # noqa: E402

pytestmark = [
    pytest.mark.browser,
    pytest.mark.django_db(transaction=True),
]


def _chromium_missing() -> bool:
    """Chromium is installed once with `uv run playwright install chromium`."""
    if shutil.which("chromium"):  # pragma: no cover - system install
        return False
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache.exists():
        cache = Path.home() / ".cache" / "ms-playwright"
    return not any(cache.glob("chromium*")) if cache.exists() else True


pytest.mark.skipif(_chromium_missing(), reason="run `uv run playwright install chromium` first")


@pytest.fixture(autouse=True)
def _skip_without_chromium() -> None:
    if _chromium_missing():  # pragma: no cover - environment dependent
        pytest.skip("run `uv run playwright install chromium` first")


@pytest.fixture
def atlas():  # type: ignore[no-untyped-def]
    return loaded_atlas()


def sign_in(page, live_server, email: str) -> None:
    page.goto(f"{live_server.url}/accounts/login/")
    page.fill("#id_username", email)
    page.fill("#id_password", DEMO_PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


def ledger(page, live_server) -> None:
    page.goto(f"{live_server.url}/app/recovery-ledger/")


def csrf_post(page, url: str, data: dict[str, str]):  # type: ignore[no-untyped-def]
    """POST directly, bypassing the rendered UI. A hidden button is not a control."""
    token = next(c["value"] for c in page.context.cookies() if c["name"] == "csrftoken")
    return page.request.post(
        url, form=data, headers={"X-CSRFToken": token, "Referer": page.url}, max_redirects=0
    )


class TestJourneyB:
    """Control 1: finance reviewer reaches an invoice-ready export and a formula-safe CSV."""

    def test_finance_reviewer_completes_the_revenue_journey(  # noqa: PLR0915
        self, page, live_server, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)

        # The four stages are shown as four separate facts, never one total.
        body = page.inner_text("body")
        for heading in (
            "Candidate value",
            "Invoice-ready value",
            "Confirmed invoiced",
            "Confirmed collected",
        ):
            assert heading in body
        assert "$480" in body
        assert page.locator("text=REV-00001").count() == 1

        # Evidence is complete, so the approval control is present.
        approve = page.get_by_role("button", name="Approve invoice-ready")
        assert approve.count() == 1
        approve.click()
        page.wait_for_load_state("networkidle")
        assert "No invoice was created" in page.inner_text("body")

        atlas.item.refresh_from_db()
        assert atlas.item.workflow_state == FinancialRecoveryItem.WorkflowState.INVOICE_READY

        # Export the approved item. The export hands the operator the file directly.
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Export 1 approved item(s)").click()
        export = FinanceExport.objects.get()
        assert export.row_count == 1
        assert download_info.value.suggested_filename == export.filename

        content = Path(download_info.value.path()).read_text(encoding="utf-8-sig")
        header, row = content.splitlines()[:2]
        assert "invoice_ready_value" in header
        assert "480.0000" in row
        assert "00518774" in row, "the export must carry the source identifier"
        for cell in row.split(","):
            assert not cell.startswith(("=", "+", "@")), f"live formula in export: {cell}"

    def test_the_case_never_claims_recovered_revenue(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 26: candidate value is not money in the bank, and the UI must say so."""
        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)
        body = page.inner_text("body")
        assert "never a single total" in body.lower()
        assert "not recovered revenue" in body.lower()
        assert "recovered revenue: $" not in body.lower()


class TestAlreadyInvoicedControl:
    """Control 2: work already billed must never be surfaced as unbilled."""

    def test_an_invoiced_work_order_is_not_a_case(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)
        body = page.inner_text("body")
        assert "REV-00001" in body, "precondition: the ledger rendered with its one real case"
        assert "00518801" not in body, "an already-invoiced work order was surfaced as unbilled"
        assert ExceptionCase.objects.count() == 1


class TestInsufficientCoverageControl:
    """Control 3: without complete authoritative coverage there is no approval."""

    def test_partial_coverage_removes_the_approval_control_and_rejects_a_direct_post(
        self, page, live_server, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        ImportCoverage.objects.filter(
            query_contract_code=ImportCoverage.QueryContract.ACCOUNTING_SERVICE_DATE_LEDGER_V1
        ).update(completeness=ImportCoverage.Completeness.PARTIAL)

        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)
        assert "REV-00001" in page.inner_text("body"), "precondition: the case is still shown"
        assert page.get_by_role("button", name="Approve invoice-ready").count() == 0
        assert "blocked by evidence" in page.inner_text("body")

        response = csrf_post(
            page,
            f"{live_server.url}/app/recovery-ledger/{atlas.item.id}/approve/",
            {"version": str(atlas.item.version)},
        )
        assert response.status in (302, 200)
        atlas.item.refresh_from_db()
        assert atlas.item.workflow_state == FinancialRecoveryItem.WorkflowState.CANDIDATE, (
            "a direct POST approved an item whose evidence was incomplete"
        )


class TestWrongRoleControl:
    """Control 4: the button is absent AND the direct POST is rejected."""

    @pytest.mark.parametrize("email", ["ops@atlas.example", "supervisor@atlas.example"])
    def test_button_absent_for_non_finance_roles(self, page, live_server, atlas, email) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, email)
        ledger(page, live_server)
        # Positive precondition: an absence assertion on a blank or errored page proves
        # nothing, so first confirm the ledger actually rendered for this reader.
        assert "Recovery ledger" in page.inner_text("h1")
        assert page.get_by_role("button", name="Approve invoice-ready").count() == 0
        assert page.get_by_role("button", name="Export 1 approved item(s)").count() == 0

    def test_the_same_page_does_offer_the_button_to_finance(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity control: the data is present and the control is reachable."""
        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)
        assert "REV-00001" in page.inner_text("body")
        assert page.get_by_role("button", name="Approve invoice-ready").count() == 1

    def test_direct_post_from_operations_is_rejected(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, "ops@atlas.example")
        ledger(page, live_server)
        response = csrf_post(
            page,
            f"{live_server.url}/app/recovery-ledger/{atlas.item.id}/approve/",
            {"version": str(atlas.item.version)},
        )
        assert response.status == 403
        atlas.item.refresh_from_db()
        assert atlas.item.workflow_state == FinancialRecoveryItem.WorkflowState.CANDIDATE

    def test_direct_export_post_from_operations_is_rejected(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, "ops@atlas.example")
        ledger(page, live_server)
        response = csrf_post(page, f"{live_server.url}/app/recovery-ledger/export/", {})
        assert response.status == 403
        assert FinanceExport.objects.count() == 0


class TestCrossTenantControl:
    """Control 5: another tenant's UUID returns a denial that leaks nothing."""

    def test_beacon_owner_cannot_read_an_atlas_case(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, "owner@beacon.example")
        response = page.goto(f"{live_server.url}/app/exceptions/{atlas.case.id}/")
        assert response.status == 404
        body = page.inner_text("body")
        assert atlas.case.case_number not in body
        assert "Meridian" not in body and "Potomac" not in body

    def test_beacon_owner_cannot_download_an_atlas_export(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.recovery.services import approvals, exports

        approvals.approve_invoice_ready(
            membership=atlas.finance,
            req=approvals.ApprovalRequest(
                item_id=atlas.item.id, expected_version=atlas.item.version
            ),
        )
        export, _ = exports.export_invoice_ready(membership=atlas.finance, item_ids=[atlas.item.id])

        sign_in(page, live_server, "owner@beacon.example")
        response = page.goto(f"{live_server.url}/app/exports/{export.id}/download/")
        assert response.status == 404
        assert "480" not in page.inner_text("body")

    def test_an_unknown_uuid_is_indistinguishable_from_another_tenants(
        self, page, live_server, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        """The two must look the same, or 404 vs 403 becomes an existence oracle."""
        sign_in(page, live_server, "owner@beacon.example")
        unknown = page.goto(f"{live_server.url}/app/exceptions/{uuid.uuid4()}/")
        unknown_body = page.inner_text("body")
        foreign = page.goto(f"{live_server.url}/app/exceptions/{atlas.case.id}/")
        assert unknown.status == foreign.status == 404
        assert page.inner_text("body") == unknown_body


class TestReplayControl:
    """Control 6: a resubmitted export is the same handoff, not a second one."""

    def test_double_submitting_the_export_form_does_not_mint_a_second_export(
        self, page, live_server, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)
        page.get_by_role("button", name="Approve invoice-ready").click()
        page.wait_for_load_state("networkidle")

        with page.expect_download():
            page.get_by_role("button", name="Export 1 approved item(s)").click()
        first = FinanceExport.objects.get()

        # The operator hits back and submits the same form again.
        ledger(page, live_server)
        response = csrf_post(
            page,
            f"{live_server.url}/app/recovery-ledger/export/",
            {"item_id": str(atlas.item.id)},
        )
        assert response.status in (200, 302)
        assert FinanceExport.objects.count() == 1
        assert FinanceExport.objects.get().id == first.id


class TestSmallViewportControl:
    """Control 7: the critical paths render at 375px without blocking overflow."""

    @pytest.mark.parametrize(
        "path",
        [
            "/app/recovery-ledger/",
            "/app/exceptions/",
            "/app/",
            "/app/imports/",
            "/app/organization/",
        ],
    )
    def test_no_horizontal_page_overflow_at_375px(self, page, live_server, atlas, path) -> None:  # type: ignore[no-untyped-def]
        page.set_viewport_size({"width": 375, "height": 812})
        sign_in(page, live_server, "finance@atlas.example")
        page.goto(f"{live_server.url}{path}")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1, f"{path} overflows by {overflow}px at 375px"

    def test_the_case_detail_does_not_overflow_at_375px(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        page.set_viewport_size({"width": 375, "height": 812})
        sign_in(page, live_server, "finance@atlas.example")
        page.goto(f"{live_server.url}/app/exceptions/{atlas.case.id}/")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1, f"the case detail overflows by {overflow}px at 375px"
        assert "$480" in page.inner_text("body")

    def test_the_approval_control_is_reachable_at_375px(self, page, live_server, atlas) -> None:  # type: ignore[no-untyped-def]
        """A wide table must scroll inside its own container, not off the page."""
        page.set_viewport_size({"width": 375, "height": 812})
        sign_in(page, live_server, "finance@atlas.example")
        ledger(page, live_server)
        approve = page.get_by_role("button", name="Approve invoice-ready")
        approve.scroll_into_view_if_needed()
        assert approve.is_visible()
        approve.click()
        page.wait_for_load_state("networkidle")
        atlas.item.refresh_from_db()
        assert atlas.item.workflow_state == FinancialRecoveryItem.WorkflowState.INVOICE_READY
