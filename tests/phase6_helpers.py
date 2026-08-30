"""Fixtures for the Route B revenue slice: a loaded, detected, ready-to-approve Atlas."""

from __future__ import annotations

from types import SimpleNamespace

from django.core.management import call_command

from apps.exceptions.models import ExceptionCase, FinancialRecoveryItem
from apps.organizations.models import Membership, Organization, User


def loaded_atlas():  # type: ignore[no-untyped-def]
    """Seed, import all four files, resolve identities, and run the detector."""
    call_command("seed_demo", verbosity=0)
    call_command("demo_load", verbosity=0)
    organization = Organization.objects.get(slug="atlas-facility-services")
    return SimpleNamespace(
        organization=organization,
        case=ExceptionCase.objects.get(organization=organization),
        item=FinancialRecoveryItem.objects.get(organization=organization),
        finance=Membership.objects.get(
            organization=organization, user__email="finance@atlas.example"
        ),
        owner=Membership.objects.get(organization=organization, user__email="owner@atlas.example"),
        ops=Membership.objects.get(organization=organization, user__email="ops@atlas.example"),
        supervisor=Membership.objects.get(
            organization=organization, user__email="supervisor@atlas.example"
        ),
        auditor=Membership.objects.get(
            organization=organization, user__email="auditor@atlas.example"
        ),
        actor=User.objects.get(email="owner@atlas.example"),
    )
