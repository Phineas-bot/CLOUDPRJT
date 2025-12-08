"""Helper script to create or update a gateway user for local development."""

import argparse
import getpass
import sys
import time
import uuid
from pathlib import Path
from typing import List

import bcrypt

from backend.gateway.auth_store import UserRecord, UserStore


def _load_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    return getpass.getpass("Password: ")


def _parse_channels(raw: str) -> List[str]:
    channels = [token.strip().lower() for token in raw.split(",") if token.strip()]
    return channels or ["email"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a gateway login user")
    parser.add_argument("email", help="User email address")
    parser.add_argument("--password", help="Password to store (insecure to pass via CLI)")
    parser.add_argument("--password-file", help="Read the password from this file instead of prompting")
    parser.add_argument("--phone", help="Optional E.164 formatted phone number for SMS OTP delivery")
    parser.add_argument(
        "--channels",
        default="email",
        help="Comma separated OTP channels (email,sms). Defaults to email only",
    )
    parser.add_argument(
        "--store",
        help="Path to user store JSON file (defaults to DFS_USER_STORE or data/user_store.json)",
    )
    parser.add_argument("--user-id", help="Optional user id to use instead of a generated value")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing user that has the same email",
    )
    args = parser.parse_args()

    password = _load_password(args)
    if not password:
        print("Password cannot be empty", file=sys.stderr)
        return 1

    store = UserStore(path=args.store) if args.store else UserStore()
    existing = store.find_by_email(args.email)
    if existing and not args.force:
        print(
            "User already exists. Re-run with --force to replace the password or choose a different email",
            file=sys.stderr,
        )
        return 1

    user_id = existing.user_id if existing else (args.user_id or uuid.uuid4().hex)
    created_at = existing.created_at if existing else time.time()
    phone = args.phone if args.phone is not None else (existing.phone_number if existing else None)
    channels = _parse_channels(args.channels)

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    record = UserRecord(
        user_id=user_id,
        email=args.email,
        password_hash=password_hash,
        phone_number=phone,
        otp_channels=channels,
        created_at=created_at,
    )

    store.add_user(record)
    print(f"User {args.email} stored at {store.path}")
    if "sms" in channels and not phone:
        print("Warning: sms channel enabled but no phone number set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
