"""Cockpit, inbox, and case detail: routes, role gating, tenancy, site scope (sections 29, 30, 33.3)."""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from apps.exceptions.detectors import revenue_unbilled as det
from apps.exceptions.models import CaseState, ExceptionCase
from apps.exceptions.services import runs
from apps.organizations.models import (
    Membership,
    MembershipRoleGrant,
    MembershipSiteGrant,
    Organization,
    User,
)
from apps.organizations.roles import Role
from tests.phase4_helpers import AS_OF, load_atlas, seed_atlas

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    organization, actor = seed_atlas()
    loaded = load_atlas(organization, actor)
    runs.evaluate_and_persist(run=loaded.run, detector_code=det.RULE_CODE, as_of=AS_OF)
    loaded.case = ExceptionCase.objects.get(organization=organization)
    return loaded


def login(client, email):  # type: ignore[no-untyped-def]
    client.force_login(User.objects.get(email=email))


def flat(body: str) -> str:
    """Collapse template whitespace so a phrase wrapped across lines still matches."""
    import re

    return re.sub(r"\s+", " ", body)


class TestCockpit:
    def test_cockpit_shows_candidate_and_labels_other_stages_unavailable(
        self, client, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        body = flat(client.get(reverse("app:home")).content.decode())
        assert "Candidate value" in body and "$480.00" in body
        assert body.count("not available in this phase") == 3
        # Section 26/30.5: no tile or heading may be TITLED "recovered revenue". The
        # phrase may appear only inside the disclaimer saying the stages are not that.
        assert "<dt>Recovered revenue" not in body
        assert 'none of them is "recovered revenue"' in body

    def test_cockpit_counts_open_cases_by_severity(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "owner@atlas.example")
        body = client.get(reverse("app:home")).content.decode()
        assert "Open cases: 1" in body

    def test_cockpit_states_that_only_one_exception_type_exists(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "owner@atlas.example")
        body = client.get(reverse("app:home")).content.decode()
        assert (
            "Attendance\n  and quality detectors do not exist" in body
            or "quality detectors do not exist" in body
        )


class TestInbox:
    def test_lists_the_case_with_rule_and_freshness(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        body = client.get(reverse("exceptions:inbox")).content.decode()
        assert atlas.case.case_number in body
        assert "Meridian Business Center" in body

    def test_filters_are_preserved_in_the_url_and_applied(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        assert (
            atlas.case.case_number
            in client.get(reverse("exceptions:inbox") + "?state=new").content.decode()
        )
        assert (
            atlas.case.case_number
            not in client.get(reverse("exceptions:inbox") + "?state=resolved").content.decode()
        )

    def test_auditor_may_read_the_inbox(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "auditor@atlas.example")
        assert client.get(reverse("exceptions:inbox")).status_code == 200


class TestCaseDetail:
    def test_shows_rule_explanation_money_labels_and_timeline(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        body = flat(
            client.get(
                reverse("exceptions:case-detail", kwargs={"case_id": atlas.case.id})
            ).content.decode()
        )
        assert "Why this was flagged" in body
        assert "declared complete coverage" in body
        assert "$480.00" in body and "candidate" in body.lower()
        assert "not recovered revenue" in body
        assert "detected" in body  # timeline event

    def test_finance_reviewer_sees_the_acknowledge_button(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        body = client.get(
            reverse("exceptions:case-detail", kwargs={"case_id": atlas.case.id})
        ).content.decode()
        assert "Acknowledge" in body

    def test_auditor_sees_no_action_controls(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 30.3: the UI must not expose buttons the role cannot use."""
        login(client, "auditor@atlas.example")
        body = client.get(
            reverse("exceptions:case-detail", kwargs={"case_id": atlas.case.id})
        ).content.decode()
        assert ">Acknowledge<" not in body
        assert "Apply transition" not in body
        assert "Assign owner" not in body


class TestTransitionsOverHttp:
    def test_finance_reviewer_can_acknowledge_via_post(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        response = client.post(
            reverse("exceptions:acknowledge", kwargs={"case_id": atlas.case.id}),
            {"version": atlas.case.version},
        )
        assert response.status_code == 302
        atlas.case.refresh_from_db()
        assert atlas.case.state == CaseState.ACKNOWLEDGED

    @pytest.mark.parametrize("email", ["auditor@atlas.example", "supervisor@atlas.example"])
    def test_direct_post_from_a_denied_role_fails_closed(self, client, atlas, email) -> None:  # type: ignore[no-untyped-def]
        login(client, email)
        response = client.post(
            reverse("exceptions:acknowledge", kwargs={"case_id": atlas.case.id}),
            {"version": atlas.case.version},
        )
        assert response.status_code in (403, 404)
        atlas.case.refresh_from_db()
        assert atlas.case.state == CaseState.NEW

    def test_stale_version_does_not_apply(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        client.post(
            reverse("exceptions:acknowledge", kwargs={"case_id": atlas.case.id}), {"version": 1}
        )
        response = client.post(
            reverse("exceptions:transition", kwargs={"case_id": atlas.case.id}),
            {"version": 1, "to_state": "dismissed", "reason_code": "false_positive", "note": "x"},
        )
        assert response.status_code == 302
        atlas.case.refresh_from_db()
        assert atlas.case.state == CaseState.ACKNOWLEDGED  # the stale dismissal was refused

    def test_csrf_is_enforced(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from django.test import Client

        enforcing = Client(enforce_csrf_checks=True)
        enforcing.force_login(User.objects.get(email="finance@atlas.example"))
        response = enforcing.post(
            reverse("exceptions:acknowledge", kwargs={"case_id": atlas.case.id}),
            {"version": atlas.case.version},
        )
        assert response.status_code == 403
        atlas.case.refresh_from_db()
        assert atlas.case.state == CaseState.NEW

    def test_get_on_a_transition_route_is_rejected(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "finance@atlas.example")
        assert (
            client.get(
                reverse("exceptions:acknowledge", kwargs={"case_id": atlas.case.id})
            ).status_code
            == 405
        )


class TestCrossTenant:
    def test_beacon_owner_gets_404_for_an_atlas_case_by_real_uuid(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        beacon = Organization.objects.get(slug="beacon-building-care")
        membership = Membership.objects.get(organization=beacon, user__email="owner@beacon.example")
        MembershipRoleGrant.objects.get_or_create(
            membership=membership, role=Role.OWNER, revoked_at=None
        )
        login(client, "owner@beacon.example")
        url = reverse("exceptions:case-detail", kwargs={"case_id": atlas.case.id})
        assert client.get(url).status_code == 404
        assert (
            client.post(
                reverse("exceptions:acknowledge", kwargs={"case_id": atlas.case.id}), {"version": 1}
            ).status_code
            == 404
        )
        assert (
            atlas.case.case_number not in client.get(reverse("exceptions:inbox")).content.decode()
        )

    def test_a_random_uuid_is_indistinguishable_from_a_foreign_one(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "owner@atlas.example")
        assert (
            client.get(
                reverse("exceptions:case-detail", kwargs={"case_id": uuid.uuid4()})
            ).status_code
            == 404
        )

    def test_a_detector_run_for_one_tenant_creates_no_case_in_another(self, atlas) -> None:  # type: ignore[no-untyped-def]
        beacon = Organization.objects.get(slug="beacon-building-care")
        assert ExceptionCase.objects.filter(organization=beacon).count() == 0
        assert ExceptionCase.objects.filter(organization=atlas.organization).count() == 1


class TestSupervisorSiteScope:
    def test_supervisor_without_a_grant_sees_no_case(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        login(client, "supervisor@atlas.example")
        body = client.get(reverse("exceptions:inbox")).content.decode()
        assert atlas.case.case_number not in body
        assert (
            client.get(
                reverse("exceptions:case-detail", kwargs={"case_id": atlas.case.id})
            ).status_code
            == 404
        )

    def test_supervisor_with_a_grant_to_that_site_sees_it(self, client, atlas) -> None:  # type: ignore[no-untyped-def]
        membership = Membership.objects.get(
            organization=atlas.organization, user__email="supervisor@atlas.example"
        )
        MembershipSiteGrant.objects.create(membership=membership, site=atlas.case.work_order.site)
        login(client, "supervisor@atlas.example")
        assert atlas.case.case_number in client.get(reverse("exceptions:inbox")).content.decode()
        assert (
            client.get(
                reverse("exceptions:case-detail", kwargs={"case_id": atlas.case.id})
            ).status_code
            == 200
        )

    def test_supervisor_with_a_grant_to_another_site_still_sees_nothing(
        self, client, atlas
    ) -> None:  # type: ignore[no-untyped-def]
        from apps.operations.models import Site

        membership = Membership.objects.get(
            organization=atlas.organization, user__email="supervisor@atlas.example"
        )
        other = Site.objects.get(organization=atlas.organization, name="Capital Retail Gallery")
        MembershipSiteGrant.objects.create(membership=membership, site=other)
        login(client, "supervisor@atlas.example")
        assert (
            atlas.case.case_number not in client.get(reverse("exceptions:inbox")).content.decode()
        )
