"""Create an organization and its bootstrap owner.

There is no public signup (section 9.3), so the first account of any organization is
created here by an operator with shell access.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.organizations.management.commands._guards import refuse_outside_local_or_demo
from apps.organizations.models import Membership, MembershipRoleGrant, Organization, User
from apps.organizations.roles import Role


class Command(BaseCommand):
    help = "Create an organization and its bootstrap owner membership."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--organization", required=True, help="Display name.")
        parser.add_argument("--slug", default="", help="Defaults to a slug of the display name.")
        parser.add_argument("--timezone", default="America/New_York")
        parser.add_argument("--display-name", default="", help="Owner's display name.")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        refuse_outside_local_or_demo("create_owner")

        email = User.objects.normalize_login_email(options["email"])
        slug = options["slug"] or slugify(options["organization"])[:64]

        organization, created_org = Organization.objects.get_or_create(
            slug=slug,
            defaults={
                "display_name": options["organization"],
                "default_timezone": options["timezone"],
            },
        )
        organization.full_clean()

        user, created_user = User.objects.get_or_create(
            email=email, defaults={"display_name": options["display_name"] or email}
        )
        if created_user:
            # No password is set here: the operator sets one with changepassword, so a
            # known default never exists.
            user.set_unusable_password()
            user.save(update_fields=["password"])

        membership, _ = Membership.objects.get_or_create(
            organization=organization, user=user, defaults={"is_active": True}
        )
        grant, created_grant = MembershipRoleGrant.objects.get_or_create(
            membership=membership, role=Role.OWNER, revoked_at=None
        )
        if not created_grant and grant.revoked_at is not None:  # pragma: no cover
            raise CommandError("An owner grant exists but is revoked; resolve it manually.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Organization {organization.slug!r} "
                f"({'created' if created_org else 'existing'}); "
                f"owner {email} ({'created' if created_user else 'existing'})."
            )
        )
        if created_user:
            self.stdout.write("No password was set. Run: manage.py changepassword " + email)
