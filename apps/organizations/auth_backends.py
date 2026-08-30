"""Authentication backend.

The User model normalizes email to lowercase on save, so the default ModelBackend —
which looks up USERNAME_FIELD exactly — would reject a correct password typed with
different capitalisation. This backend applies the same normalization to the
supplied identifier before lookup.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.organizations.models import User, UserManager


class EmailBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        identifier = username if username is not None else kwargs.get(User.USERNAME_FIELD)
        if identifier:
            try:
                identifier = UserManager.normalize_login_email(identifier)
            except ValueError:
                return None
        return super().authenticate(request, username=identifier, password=password, **kwargs)
