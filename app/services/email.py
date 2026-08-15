"""Pluggable email sending. Today only a logging stub; real providers can plug in later."""

from __future__ import annotations

import logging
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send_invitation_email(
        self,
        *,
        to: str,
        family_name: str,
        invite_url: str,
        invited_by_name: str,
    ) -> None: ...


class LoggingEmailSender:
    def send_invitation_email(
        self,
        *,
        to: str,
        family_name: str,
        invite_url: str,
        invited_by_name: str,
    ) -> None:
        logger.info(
            "invitation_email stub to=%s family=%r invited_by=%r url=%s",
            to,
            family_name,
            invited_by_name,
            invite_url,
        )


def get_email_sender() -> EmailSender:
    provider = get_settings().email_provider.strip().lower()
    if provider in ("", "log", "logging", "console"):
        return LoggingEmailSender()
    # Unknown providers fall back to logging until a real integration exists.
    logger.warning("Unknown EMAIL_PROVIDER=%r; using logging stub", provider)
    return LoggingEmailSender()


def try_send_invitation_email(
    *,
    to: str,
    family_name: str,
    invite_url: str,
    invited_by_name: str,
) -> None:
    """Best-effort invite email; never raises to the caller."""
    try:
        get_email_sender().send_invitation_email(
            to=to,
            family_name=family_name,
            invite_url=invite_url,
            invited_by_name=invited_by_name,
        )
    except Exception:
        logger.exception("Failed to send invitation email to %s", to)
