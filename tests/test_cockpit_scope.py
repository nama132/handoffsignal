"""Every number on the first post-login screen is scoped to the reader (plan section 7).

The cockpit at `/app/` is `LOGIN_REDIRECT_URL` -- the first thing anyone sees after signing
in, and the screen a prospect sees first in a demo. It previously scoped its headline and
its recent-case list but not its severity tiles or its money, so a supervisor holding zero
site grants read "Open cases: 0" beside "Medium: 1" and an organization-wide candidate
total. The contradiction was the symptom; the leak was that the second number was never
that reader's to see.

These tests assert rendered output, not helper return values, because the defect lived in
what reached the HTML.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.exceptions import selectors
from apps.operations.models import Site
from apps.organizations.models import MembershipSiteGrant, User
from apps.organizations.policy import effective_site_scope
from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db

#: The exact rendered token for the demo's candidate value. Never assert the bare digits
#: "480": the source-freshness panel prints an elapsed age in minutes, which grows past
#: 14808 and contains "480" as a substring, so a bare check both passes and fails for the
#: wrong reasons. Every money assertion below reads a NAMED stage out of the financial
#: section instead.
CANDIDATE = "$480.00"

MONEY_SECTION = re.compile(r'<section aria-labelledby="money-heading">(.*?)</section>', re.S)
STAGE_TILE = re.compile(r"<dt>([^<]+)</dt>\s*<dd>(.*?)</dd>", re.S)
SEVERITY_TILE = re.compile(r'<div class="tile tile--\w+"><dt>(\w+)</dt><dd>(\d+)</dd></div>')


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    return loaded_atlas()


def cockpit(client, email):  # type: ignore[no-untyped-def]
    client.force_login(User.objects.get(email=email))
    response = client.get(reverse("app:home"))
    assert response.status_code == 200
    return response.content.decode()


def money_section(html: str) -> str:
    """Just the financial-stage section, so no other number can be mistaken for money."""
    match = MONEY_SECTION.search(html)
    assert match, "the financial-stage section did not render at all"
    return match.group(1)


def stage_values(html: str) -> dict[str, str]:
    """{'Candidate value': '$480.00', 'Invoiced': 'not available in this phase', ...}."""
    return {
        label.strip(): re.sub(r"<[^>]+>", "", value).strip()
        for label, value in STAGE_TILE.findall(money_section(html))
    }


def stage(html: str, label: str) -> str:
    values = stage_values(html)
    assert label in values, f"no financial stage named {label!r}; saw {sorted(values)}"
    return values[label]


def severity_tiles(html: str) -> dict[str, str]:
    """Parse the rendered severity tiles: {'low': '0', 'medium': '1', ...}."""
    return {m.group(1).lower(): m.group(2) for m in SEVERITY_TILE.finditer(html)}


def headline(html: str) -> str:
    return re.search(r"Open cases:\s*(\d+)", html).group(1)


class TestTenantWideRolesSeeEverything:
    """Requirements 1, 2 and 9."""

    @pytest.mark.parametrize("email", ["owner@atlas.example", "finance@atlas.example"])
    def test_owner_and_finance_see_the_case_and_its_candidate_value(
        self, atlas, client, email
    ) -> None:  # type: ignore[no-untyped-def]
        html = cockpit(client, email)
        assert headline(html) == "1"
        assert severity_tiles(html)["medium"] == "1"
        assert stage(html, "Candidate value") == CANDIDATE

    def test_a_tenant_wide_role_stays_tenant_wide_even_with_a_site_grant(
        self, atlas, client
    ) -> None:  # type: ignore[no-untyped-def]
        """Requirement 9. A grant must never *narrow* someone who is already tenant-wide."""
        other = (
            Site.objects.filter(organization=atlas.organization)
            .exclude(id=atlas.item.work_order.site_id)
            .first()
        )
        MembershipSiteGrant.objects.create(membership=atlas.finance, site=other)
        assert effective_site_scope(atlas.finance) is None
        html = cockpit(client, "finance@atlas.example")
        assert headline(html) == "1"
        assert stage(html, "Candidate value") == CANDIDATE


class TestZeroGrantSupervisorSeesNothing:
    """Requirement 3 -- the reported defect, asserted on rendered HTML."""

    def test_the_scope_really_is_empty(self, atlas) -> None:  # type: ignore[no-untyped-def]
        assert effective_site_scope(atlas.supervisor) == set()

    def test_headline_severity_tiles_and_money_all_agree_on_nothing(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        html = cockpit(client, "supervisor@atlas.example")
        assert headline(html) == "0"
        tiles = severity_tiles(html)
        assert tiles, "precondition: the severity tiles rendered at all"
        assert set(tiles.values()) == {"0"}, f"a severity tile leaked a count: {tiles}"
        assert stage(html, "Candidate value") == "none", (
            "the cockpit leaked an organization-wide money total"
        )
        assert atlas.case.case_number not in html

    def test_no_stage_shows_a_value_from_an_ungranted_site(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        html = cockpit(client, "supervisor@atlas.example")
        rendered = [v for v in stage_values(html).values() if v.startswith("$")]
        assert rendered == [], f"money rendered to a zero-grant reader: {rendered}"

    def test_the_page_still_renders_for_them(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity: the assertions above must not be passing on an error page."""
        html = cockpit(client, "supervisor@atlas.example")
        assert "What needs attention now" in html
        assert "Financial stages" in html


class TestGrantedSupervisorSeesOnlyTheirSite:
    """Requirements 4 and 5."""

    def test_granting_the_case_site_reveals_exactly_that_case(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        MembershipSiteGrant.objects.create(
            membership=atlas.supervisor, site=atlas.item.work_order.site
        )
        html = cockpit(client, "supervisor@atlas.example")
        assert headline(html) == "1"
        assert severity_tiles(html)["medium"] == "1"
        assert stage(html, "Candidate value") == CANDIDATE

    def test_granting_a_different_site_reveals_nothing(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        other = (
            Site.objects.filter(organization=atlas.organization)
            .exclude(id=atlas.item.work_order.site_id)
            .first()
        )
        MembershipSiteGrant.objects.create(membership=atlas.supervisor, site=other)
        html = cockpit(client, "supervisor@atlas.example")
        assert headline(html) == "0"
        assert set(severity_tiles(html).values()) == {"0"}
        assert stage(html, "Candidate value") == "none"


class TestEmptySetIsNeverNone:
    """Requirement 6, asserted directly on the selector, not through a view."""

    def test_open_case_counts_distinguishes_empty_set_from_none(self, atlas) -> None:  # type: ignore[no-untyped-def]
        org = atlas.organization.id
        tenant_wide = selectors.open_case_counts(org, limit_to_site_ids=None)
        no_sites = selectors.open_case_counts(org, limit_to_site_ids=set())
        assert sum(tenant_wide.values()) == 1, "precondition: there is one open case"
        assert sum(no_sites.values()) == 0, "the empty set widened to tenant-wide"
        assert set(no_sites) == set(tenant_wide), "the shape must not change with scope"

    def test_the_granted_set_is_applied_verbatim(self, atlas) -> None:  # type: ignore[no-untyped-def]
        org = atlas.organization.id
        site_id = atlas.item.work_order.site_id
        assert sum(selectors.open_case_counts(org, limit_to_site_ids={site_id}).values()) == 1
        other = Site.objects.filter(organization=atlas.organization).exclude(id=site_id).first()
        assert sum(selectors.open_case_counts(org, limit_to_site_ids={other.id}).values()) == 0


class TestCrossTenant:
    """Requirement 7."""

    def test_a_beacon_user_infers_no_atlas_count_or_money(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        html = cockpit(client, "owner@beacon.example")
        assert headline(html) == "0"
        assert set(severity_tiles(html).values()) == {"0"}
        assert stage(html, "Candidate value") == "none"
        assert "Meridian" not in html and "Atlas" not in html


class TestCockpitAndLedgerAgree:
    """Requirement 8, plus the semantic change the plan asked to be stated and tested."""

    def test_the_same_actor_sees_the_same_candidate_total_on_both_screens(
        self, atlas, client
    ) -> None:  # type: ignore[no-untyped-def]
        client.force_login(User.objects.get(email="finance@atlas.example"))
        cockpit_html = client.get(reverse("app:home")).content.decode()
        ledger_html = client.get(reverse("recovery:ledger")).content.decode()
        assert stage(cockpit_html, "Candidate value") == CANDIDATE
        assert CANDIDATE in ledger_html
        assert "480.0000" not in cockpit_html, "money must be quantized to cents for display"

    def test_the_cockpit_now_counts_items_whose_case_is_not_open(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        """SEMANTIC CHANGE, deliberate and recorded (plan section 8.4).

        The retired Phase 4 selector totalled only items whose exception case was OPEN.
        The Phase 6 selector the cockpit now uses totals every recovery item in scope. A
        case that has been resolved still has a real candidate value and still belongs in
        the handoff view, so this is the intended behaviour -- but it means the cockpit's
        candidate total can differ from the old one, and that must not be a surprise.
        """
        from apps.exceptions.services import financial, transitions

        assert financial.stage_totals(atlas.organization.id)["candidate"] == Decimal("480.00")

        # Dismiss through the real transition service, not a queryset update: the case
        # lifecycle has exactly one door and a database constraint that refuses a
        # dismissal without a code. A shortcut here would test a state the product
        # cannot actually reach.
        atlas.case.refresh_from_db()
        transitions.transition(
            membership=atlas.finance,
            req=transitions.TransitionRequest(
                case_id=atlas.case.id,
                expected_version=atlas.case.version,
                to_state="dismissed",
                reason_code="already_invoiced",
                note="Dismissed to exercise the cockpit's selector change.",
            ),
        )

        # The retired selector now reports nothing; the shipped one still reports the value.
        assert financial.stage_totals(atlas.organization.id)["candidate"] is None
        html = cockpit(client, "finance@atlas.example")
        assert stage(html, "Candidate value") == CANDIDATE, (
            "a dismissed case's candidate value vanished from the cockpit"
        )
        assert headline(html) == "0", "but it is no longer an OPEN case"


class TestRegressionGuard:
    """Plan task 11: this must fail if any first-screen number widens an empty scope."""

    def test_no_first_screen_number_survives_an_empty_site_scope(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        html = cockpit(client, "supervisor@atlas.example")
        numbers = [n for n in re.findall(r"<dd>(\d+)</dd>", html) if n != "0"]
        assert numbers == [], f"a non-zero tile rendered to a zero-grant reader: {numbers}"
        assert [v for v in stage_values(html).values() if v.startswith("$")] == []
        assert headline(html) == "0"


class TestWithheldTotalsAreExplained:
    """A withheld total must never render as a bare "none" that reads like zero.

    Pointing the cockpit at the Phase 6 selector brought its mixed-currency behaviour with
    it: the selector returns `candidate=None` when the visible rows span more than one
    currency. Without the explanation beside it, the first screen after login would show a
    tenant with real money as though it had none -- a new dishonesty introduced by the fix,
    which is exactly the kind of thing that ships unnoticed.
    """

    def test_a_mixed_currency_tenant_sees_the_reason_not_a_bare_none(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        from tests.test_recovery_ledger import _second_item_in

        _second_item_in(atlas, currency="EUR")
        html = cockpit(client, "finance@atlas.example")
        assert "More than one currency is in view" in html
        assert stage(html, "Candidate value") == "none", (
            "a total was still rendered across two currencies"
        )

    def test_a_single_currency_tenant_sees_no_such_warning(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity control: the banner must not be permanently on."""
        html = cockpit(client, "finance@atlas.example")
        assert "More than one currency is in view" not in html
        assert stage(html, "Candidate value") == CANDIDATE


class TestTheMoneyAssertionsCannotBeFooled:
    """Requirement 7: why these tests no longer search the page for the digits "480".

    The cockpit's source-freshness panel prints an elapsed age in minutes. That number
    grows, and it has already passed 14808 -- which contains "480". A bare substring check
    therefore breaks in both directions: `"480" in html` passes when no money rendered,
    and `"480" not in html` fails when no money leaked. Neither failure looks like a test
    bug; both look like the product being wrong.
    """

    DECOY = (
        '<section aria-labelledby="fresh-heading"><ul><li>ar_ledger - 14808 min old</li></ul>'
        "</section>"
        '<section aria-labelledby="money-heading"><dl>'
        "<div><dt>Candidate value</dt><dd><span>none</span></dd></div>"
        "<div><dt>Invoiced</dt><dd><span>not available in this phase</span></dd></div>"
        "</dl></section>"
    )

    def test_the_bare_substring_check_would_be_fooled(self) -> None:
        assert "480" in self.DECOY, "precondition: the decoy contains the digits"

    def test_the_stage_parser_is_not(self) -> None:
        assert stage(self.DECOY, "Candidate value") == "none"
        assert [v for v in stage_values(self.DECOY).values() if v.startswith("$")] == []

    def test_the_parser_reads_a_real_value_when_there_is_one(self) -> None:
        """Non-vacuity: it must not simply return "none" for everything."""
        html = self.DECOY.replace("<span>none</span>", "$480.00")
        assert stage(html, "Candidate value") == CANDIDATE

    def test_the_parser_ignores_numbers_outside_the_money_section(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        html = cockpit(client, "supervisor@atlas.example")
        assert "min old" in html, "precondition: the freshness panel rendered"
        assert stage(html, "Candidate value") == "none"
