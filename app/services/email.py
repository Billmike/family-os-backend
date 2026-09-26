"""Pluggable email sending. log = stdout stub; resend = Resend HTTP API."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class EmailSender(Protocol):
    def send_invitation_email(
        self,
        *,
        to: str,
        family_name: str,
        invite_url: str,
        invited_by_name: str,
    ) -> None: ...

    def send_password_reset_email(
        self,
        *,
        to: str,
        reset_url: str,
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
        logger.warning(
            "invitation_email stub to=%s family=%r invited_by=%r url=%s",
            to,
            family_name,
            invited_by_name,
            invite_url,
        )

    def send_password_reset_email(
        self,
        *,
        to: str,
        reset_url: str,
    ) -> None:
        logger.warning("password_reset_email stub to=%s url=%s", to, reset_url)


class ResendEmailSender:
    def __init__(self, *, api_key: str, from_address: str) -> None:
        self.api_key = api_key
        self.from_address = from_address

    def send_invitation_email(
        self,
        *,
        to: str,
        family_name: str,
        invite_url: str,
        invited_by_name: str,
    ) -> None:
        self._send(
            to=to,
            subject=f"Join {family_name} on FamilyOS",
            text=(
                f"{invited_by_name} invited you to join {family_name} on FamilyOS.\n\n"
                f"Open this link to join:\n{invite_url}\n"
            ),
        )

    def send_password_reset_email(
        self,
        *,
        to: str,
        reset_url: str,
    ) -> None:
        self._send(
            to=to,
            subject="Reset your FamilyOS password",
            text=(
                "Use this link within one hour to choose a new password:\n"
                f"{reset_url}\n\n"
                "If you did not request this, you can ignore this email.\n"
            ),
        )

    def _send(self, *, to: str, subject: str, text: str) -> None:
        response = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "from": self.from_address,
                "to": [to],
                "subject": subject,
                "text": text,
            },
            timeout=10.0,
        )
        response.raise_for_status()


def get_email_sender() -> EmailSender:
    settings = get_settings()
    provider = settings.email_provider.strip().lower()
    if provider == "resend":
        api_key = settings.resend_api_key.strip()
        if not api_key:
            logger.warning("EMAIL_PROVIDER=resend but RESEND_API_KEY is empty; using logging stub")
            return LoggingEmailSender()
        return ResendEmailSender(api_key=api_key, from_address=settings.email_from)
    if provider not in ("", "log", "logging", "console"):
        logger.warning("Unknown EMAIL_PROVIDER=%r; using logging stub", provider)
    return LoggingEmailSender()


def try_send_invitation_email(
    *,
    to: str,
    family_name: str,
    invite_url: str,
    invited_by_name: str,
) -> bool:
    """Best-effort invite email; never raises to the caller."""
    try:
        get_email_sender().send_invitation_email(
            to=to,
            family_name=family_name,
            invite_url=invite_url,
            invited_by_name=invited_by_name,
        )
        return True
    except Exception:
        logger.exception("Failed to send invitation email to %s", to)
        return False


def try_send_password_reset_email(*, to: str, reset_url: str) -> bool:
    """Best-effort reset email; never raises to the caller."""
    try:
        get_email_sender().send_password_reset_email(to=to, reset_url=reset_url)
        return True
    except Exception:
        logger.exception("Failed to send password reset email to %s", to)
        return False
