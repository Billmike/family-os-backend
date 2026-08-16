"""Print VAPID env values derived from private_key.pem.

Usage:
  cd backend && uv run python -m scripts.print_vapid_env

pywebpush does not accept PEM strings via its string API — use the raw key.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    priv_path = ROOT / "private_key.pem"
    if not priv_path.exists():
        print(f"Missing {priv_path}", file=sys.stderr)
        return 1

    pem_bytes = priv_path.read_bytes()
    priv = serialization.load_pem_private_key(pem_bytes, password=None)
    raw = priv.private_numbers().private_value.to_bytes(32, "big")
    raw_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")

    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public = base64.urlsafe_b64encode(pub).decode().rstrip("=")

    # Sanity: py_vapid must accept this exact string.
    Vapid.from_string(private_key=raw_b64)

    print("# Set these on Sevalla (raw key — short, no PEM, no + corruption)")
    print(f"VAPID_PRIVATE_KEY={raw_b64}")
    print(f"VAPID_PUBLIC_KEY={public}")
    print("VAPID_CONTACT_EMAIL=mailto:you@example.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
