"""Print VAPID env values derived from private_key.pem / public_key.pem.

Usage:
  cd backend && uv run python -m scripts.print_vapid_env
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    priv_path = ROOT / "private_key.pem"
    if not priv_path.exists():
        print(f"Missing {priv_path}", file=sys.stderr)
        return 1

    pem_bytes = priv_path.read_bytes()
    priv = serialization.load_pem_private_key(pem_bytes, password=None)
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public = base64.urlsafe_b64encode(pub).decode().rstrip("=")
    b64url = base64.urlsafe_b64encode(pem_bytes).decode().rstrip("=")

    print("# Copy these into Sevalla (use base64url private key — survives + → space corruption)")
    print(f"VAPID_PRIVATE_KEY=base64url:{b64url}")
    print(f"VAPID_PUBLIC_KEY={public}")
    print("VAPID_CONTACT_EMAIL=mailto:you@example.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
