"""Identity models.

Section 22.2 requires a custom user model from the first migration, even though it
initially adds only a UUID and a unique normalized email: changing the user model
later is expensive.

Deliberately absent in Phase 1: Organization, Membership, MembershipRoleGrant and
MembershipSiteGrant. Those are Phase 2 deliverables. Note that no organization is
stored on User — tenancy is expressed through memberships (section 22.2).
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import TimestampedModel, UUIDPrimaryKeyModel
from apps.common.validators import validate_iana_timezone
from apps.organizations.roles import Role


class UserManager(BaseUserManager["User"]):
    """Creates users from a normalized email address. There is no public signup."""

    use_in_migrations = True

    @staticmethod
    def normalize_login_email(email: str) -> str:
        """Normalize for uniqueness: trim, lowercase the whole address.

        Django's BaseUserManager.normalize_email only lowercases the domain. Login
        identity here is case-insensitive in full so two accounts cannot differ by
        capitalisation alone.
        """
        if not email:
            raise ValueError("An email address is required.")
        return email.strip().lower()

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        user = self.model(email=self.normalize_login_email(email), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(UUIDPrimaryKeyModel, AbstractBaseUser, PermissionsMixin):
    """Platform login identity.

    `is_staff` is PLATFORM administration and is distinct from the tenant `owner`
    role that arrives in Phase 2. It must never be granted through a tenant UI
    (section 22.2).
    """

    email = models.EmailField(unique=True, max_length=254)
    display_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Platform administration only. Never granted through tenant UI.",
    )
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        db_table = "organizations_user"
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        self.email = UserManager.normalize_login_email(self.email)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Normalize on every write path, including direct .save() calls.
        self.email = UserManager.normalize_login_email(self.email)
        super().save(*args, **kwargs)

    def get_full_name(self) -> str:
        return self.display_name or self.email

    def get_short_name(self) -> str:
        return self.display_name or self.email.split("@")[0]


class Organization(UUIDPrimaryKeyModel, TimestampedModel):
    """A tenant. Every operational row in the system belongs to exactly one.

    Section 22.2. `demo_mode` controls synthetic labelling only — it can never bypass
    authentication or validation (line 819).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    class Currency(models.TextChoices):
        # Initially USD only, but modelled as a field rather than a hidden assumption
        # (section 18).
        USD = "USD", "US dollar"

    slug = models.SlugField(max_length=64, unique=True)
    display_name = models.CharField(max_length=200)
    default_timezone = models.CharField(
        max_length=64,
        default="America/New_York",
        validators=[validate_iana_timezone],
        help_text="IANA timezone used for organization-wide reporting.",
    )
    currency = models.CharField(max_length=3, choices=Currency, default=Currency.USD)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    demo_mode = models.BooleanField(
        default=False,
        help_text="Synthetic labelling only. Never an authentication or validation bypass.",
    )

    class Meta:
        db_table = "organizations_organization"
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name

    def clean(self) -> None:
        super().clean()
        validate_iana_timezone(self.default_timezone)

    @property
    def is_operational(self) -> bool:
        """Only an active organization may be acted upon.

        A suspended or archived organization is readable by nothing in the tenant UI;
        the policy service refuses every action including read.
        """
        return self.status == self.Status.ACTIVE


class Membership(UUIDPrimaryKeyModel, TimestampedModel):
    """Binds a user to one organization. Tenancy is expressed here, never on User."""

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        "organizations.User", on_delete=models.PROTECT, related_name="memberships"
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="memberships_created",
        help_text="Null only for the bootstrap owner (section 22.2).",
    )

    class Meta:
        db_table = "organizations_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="uniq_membership_org_user"
            )
        ]
        ordering = ["organization__display_name", "user__email"]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.organization.slug}"

    @property
    def active_roles(self) -> set[str]:
        """Union of currently active role grants (section 9.3, line 382)."""
        return {grant.role for grant in self.role_grants.all() if grant.revoked_at is None}


class MembershipRoleGrant(UUIDPrimaryKeyModel, TimestampedModel):
    """One role held by one membership.

    A membership may hold several concurrently; permissions are the union of active
    grants (line 382). Revocation is recorded rather than deleted so the grant history
    remains auditable.
    """

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="role_grants")
    role = models.CharField(max_length=32, choices=Role)
    granted_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="role_grants_made",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "organizations_membership_role_grant"
        constraints = [
            # One ACTIVE grant per (membership, role). A revoked grant may coexist with
            # a later re-grant, which is why this is a partial unique index.
            models.UniqueConstraint(
                fields=["membership", "role"],
                condition=models.Q(revoked_at__isnull=True),
                name="uniq_active_role_grant_per_membership",
            )
        ]
        ordering = ["membership", "role"]

    def __str__(self) -> str:
        state = "active" if self.revoked_at is None else "revoked"
        return f"{self.role} ({state})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class MembershipSiteGrant(UUIDPrimaryKeyModel, TimestampedModel):
    """Grants one membership access to one site.

    Deny by default (line 841): "Required for every site a supervisor may access;
    absence of a grant means no site access. Do not use a wildcard or interpret an
    empty grant set as tenant-wide access."

    There is deliberately no "all sites" flag. Adding one would make the deny-by-default
    guarantee unprovable.
    """

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="site_grants")
    site = models.ForeignKey(
        "operations.Site", on_delete=models.CASCADE, related_name="membership_grants"
    )
    granted_by = models.ForeignKey(
        "organizations.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="site_grants_made",
    )

    class Meta:
        db_table = "organizations_membership_site_grant"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "site"], name="uniq_site_grant_per_membership"
            )
        ]
        ordering = ["membership", "site"]

    def __str__(self) -> str:
        return f"{self.membership} -> {self.site}"

    def clean(self) -> None:
        """A membership may only be granted a site inside its own organization."""
        super().clean()
        if self.membership_id and self.site_id:
            if self.membership.organization_id != self.site.organization_id:
                raise ValidationError({"site": "This site belongs to a different organization."})
