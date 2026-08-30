"""Custom user model, sign-in, and sign-out."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.organizations.models import User

pytestmark = pytest.mark.django_db


class TestUserModel:
    def test_email_is_normalized_to_lowercase(self) -> None:
        user = User.objects.create_user(email="  Finance.Reviewer@Example.TEST ", password="pw")
        assert user.email == "finance.reviewer@example.test"

    def test_email_is_unique_case_insensitively(self) -> None:
        """A duplicate differing only by case must be rejected.

        full_clean() runs before the INSERT, so this surfaces as ValidationError;
        the database unique index is asserted separately in test_migrations.py.
        """
        User.objects.create_user(email="owner@example.test", password="pw")
        from django.core.exceptions import ValidationError
        from django.db import IntegrityError

        with pytest.raises((ValidationError, IntegrityError)):
            User.objects.create_user(email="OWNER@EXAMPLE.TEST", password="pw")

    def test_primary_key_is_a_uuid(self) -> None:
        import uuid

        user = User.objects.create_user(email="uuid@example.test", password="pw")
        assert isinstance(user.pk, uuid.UUID)

    def test_user_has_no_organization_field(self) -> None:
        """Tenancy is expressed through memberships, never on User (section 22.2)."""
        field_names = {field.name for field in User._meta.get_fields()}
        assert "organization" not in field_names

    def test_blank_email_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            User.objects.create_user(email="", password="pw")

    def test_superuser_requires_platform_flags(self) -> None:
        user = User.objects.create_superuser(email="root@example.test", password="pw")
        assert user.is_staff and user.is_superuser

    def test_superuser_rejects_contradictory_flags(self) -> None:
        with pytest.raises(ValueError):
            User.objects.create_superuser(email="bad@example.test", password="pw", is_staff=False)

    def test_new_user_is_not_platform_staff(self) -> None:
        """is_staff is platform administration and must never default on."""
        user = User.objects.create_user(email="plain@example.test", password="pw")
        assert user.is_staff is False
        assert user.is_superuser is False


class TestAuthenticationFlow:
    def test_login_succeeds_with_correct_credentials(self, client, user, user_password) -> None:
        response = client.post(
            reverse("login"), {"username": user.email, "password": user_password}
        )
        assert response.status_code == 302
        assert response.url == reverse("app:home")

    def test_login_is_case_insensitive_on_email(self, client, user, user_password) -> None:
        response = client.post(
            reverse("login"),
            {"username": user.email.upper(), "password": user_password},
        )
        assert response.status_code == 302

    def test_login_fails_with_wrong_password(self, client, user) -> None:
        response = client.post(
            reverse("login"), {"username": user.email, "password": "wrong-password"}
        )
        assert response.status_code == 200
        assert response.wsgi_request.user.is_anonymous

    def test_inactive_user_cannot_authenticate(self, client, user, user_password) -> None:
        user.is_active = False
        user.save()
        response = client.post(
            reverse("login"), {"username": user.email, "password": user_password}
        )
        assert response.status_code == 200
        assert response.wsgi_request.user.is_anonymous

    def test_logout_requires_post(self, client, user) -> None:
        client.force_login(user)
        assert client.get(reverse("logout")).status_code == 405

    def test_logout_via_post_ends_the_session(self, client, user) -> None:
        client.force_login(user)
        response = client.post(reverse("logout"))
        assert response.status_code == 302
        assert client.get(reverse("app:foundation-status")).status_code == 302


class TestFoundationStatusPage:
    def test_requires_authentication(self, client) -> None:
        response = client.get(reverse("app:foundation-status"))
        assert response.status_code == 302
        assert reverse("login") in response.url

    def test_user_without_a_membership_cannot_reach_the_shell(self, client, user) -> None:
        """The Phase 1 fixture user has no membership, so the shell is not reachable."""
        client.force_login(user)
        response = client.get(reverse("app:home"))
        assert response.status_code == 302
        assert reverse("organizations:select-organization") in response.url

    def test_cockpit_is_truthful_about_route_b_scope(self, client) -> None:
        """The cockpit says plainly which exception types do NOT exist (section 30.1)."""
        from apps.organizations.roles import Role
        from tests.factories import make_tenant

        tenant = make_tenant("truthful-shell", roles=(Role.OWNER,))
        client.force_login(tenant.user)
        response = client.get(reverse("app:home"))
        assert response.status_code == 200
        import re

        body = re.sub(rb"\s+", b" ", response.content)
        assert b"Attendance and quality detectors do not exist" in body

    def test_root_redirects_to_the_app(self, client) -> None:
        assert client.get("/").status_code == 302


class TestNoPublicSignup:
    @pytest.mark.parametrize(
        "path", ["/accounts/signup/", "/accounts/register/", "/signup/", "/app/seed/"]
    )
    def test_signup_and_seed_routes_do_not_exist(self, client, path: str) -> None:
        assert client.get(path).status_code == 404
