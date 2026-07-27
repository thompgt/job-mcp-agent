"""Shared dependencies: the service instance and the optional bearer token."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from careercraft.service import CareerCraftService
from careercraft.settings import Settings


def get_service(request: Request) -> CareerCraftService:
    """The one service instance, created in the app lifespan."""
    return request.app.state.service  # type: ignore[no-any-return]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def require_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Check the bearer token, when one is configured.

    No token configured means no check — the default deployment is a loopback
    bind that only the user can reach, and demanding a secret there would just
    push people towards disabling it. ``Settings.check_bind_safety`` is what
    makes sure the token exists whenever the bind is not loopback.
    """
    settings: Settings = request.app.state.settings
    if not settings.auth_token:
        return

    expected = f"Bearer {settings.auth_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


ServiceDep = Annotated[CareerCraftService, Depends(get_service)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
AuthDep = Annotated[None, Depends(require_token)]
