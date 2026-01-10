import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import bcrypt


def _now() -> float:
    return time.time()


@dataclass
class UserRecord:
    user_id: str
    email: str
    password_hash: Optional[str]
    phone_number: Optional[str]
    otp_channels: List[str]
    created_at: float
    role: str = "user"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OtpChallenge:
    pending_id: str
    user_id: str
    code_hash: str
    salt: str
    expires_at: float
    channels: List[str]
    attempts: int
    resend_available_at: float
    last_sent_at: float

    def to_dict(self) -> dict:
        return asdict(self)


class UserStore:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.getenv("DFS_USER_STORE", "data/user_store.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._users: Dict[str, UserRecord] = {}
        self._email_index: Dict[str, str] = {}
        self._load()
        if not self._users:
            self._seed_default_user()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            logging.error("Failed to parse user store: %s", exc)
            return
        for raw in payload.get("users", []):
            record = UserRecord(
                user_id=raw["user_id"],
                email=raw["email"],
                password_hash=raw.get("password_hash"),
                phone_number=raw.get("phone_number"),
                otp_channels=raw.get("otp_channels", ["email"]),
                created_at=raw.get("created_at", _now()),
                role=raw.get("role", "user"),
            )
            self._users[record.user_id] = record
            self._email_index[record.email.lower()] = record.user_id

    def _seed_default_user(self) -> None:
        email = os.getenv("DFS_DEFAULT_USER_EMAIL")
        password = os.getenv("DFS_DEFAULT_USER_PASSWORD")
        phone = os.getenv("DFS_DEFAULT_USER_PHONE")
        if not email or not password:
            logging.warning("User store empty and no default credentials provided; set DFS_DEFAULT_USER_EMAIL/PASSWORD")
            return
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        record = UserRecord(
            user_id=os.getenv("DFS_DEFAULT_USER_ID", uuid.uuid4().hex),
            email=email,
            password_hash=hashed,
            phone_number=phone,
            otp_channels=["email", "sms"] if phone else ["email"],
            created_at=_now(),
            role="user",
        )
        self.add_user(record)
        logging.info("Seeded default user %s", email)

    def _persist(self) -> None:
        payload = {"users": [record.to_dict() for record in self._users.values()]}
        self.path.write_text(json.dumps(payload, indent=2))

    def add_user(self, record: UserRecord) -> None:
        with self._lock:
            self._users[record.user_id] = record
            self._email_index[record.email.lower()] = record.user_id
            self._persist()

    def find_by_email(self, email: str) -> Optional[UserRecord]:
        with self._lock:
            user_id = self._email_index.get(email.lower())
            return self._users.get(user_id) if user_id else None

    def get(self, user_id: str) -> Optional[UserRecord]:
        with self._lock:
            return self._users.get(user_id)

    def verify_password(self, email: str, password: str) -> Optional[UserRecord]:
        record = self.find_by_email(email)
        if not record:
            return None
        try:
            if record.password_hash and bcrypt.checkpw(password.encode("utf-8"), record.password_hash.encode("utf-8")):
                return record
        except ValueError:
            logging.error("Corrupt password hash for %s", email)
        return None

    def create_user(self, *, email: str, password: str, phone_number: Optional[str], otp_channels: List[str], role: str = "user") -> UserRecord:
        with self._lock:
            if self.find_by_email(email):
                raise ValueError("email already exists")
            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            record = UserRecord(
                user_id=uuid.uuid4().hex,
                email=email,
                password_hash=hashed,
                phone_number=phone_number,
                otp_channels=otp_channels,
                created_at=_now(),
                role=role,
            )
            self._users[record.user_id] = record
            self._email_index[email.lower()] = record.user_id
            self._persist()
            return record


class OtpChallengeStore:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.getenv("DFS_OTP_STORE", "data/otp_store.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = int(os.getenv("DFS_OTP_TTL", "300"))
        self.cooldown = int(os.getenv("DFS_OTP_RESEND_COOLDOWN", "30"))
        self.max_attempts = int(os.getenv("DFS_OTP_MAX_ATTEMPTS", "5"))
        self._lock = threading.RLock()
        self._secret = os.getenv("DFS_AUTH_SECRET", "change-me")
        if self._secret == "change-me":
            logging.warning("DFS_AUTH_SECRET not set; using insecure default secret")
        self._entries: Dict[str, OtpChallenge] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            logging.error("Failed to parse OTP store; starting empty")
            return
        for raw in payload.get("challenges", []):
            entry = OtpChallenge(
                pending_id=raw["pending_id"],
                user_id=raw["user_id"],
                code_hash=raw["code_hash"],
                salt=raw["salt"],
                expires_at=raw["expires_at"],
                channels=raw.get("channels", ["email"]),
                attempts=raw.get("attempts", 0),
                resend_available_at=raw.get("resend_available_at", 0.0),
                last_sent_at=raw.get("last_sent_at", 0.0),
            )
            if entry.expires_at > _now():
                self._entries[entry.pending_id] = entry

    def _persist(self) -> None:
        payload = {"challenges": [entry.to_dict() for entry in self._entries.values()]}
        self.path.write_text(json.dumps(payload, indent=2))

    def _hash_code(self, code: str, salt: str) -> str:
        return hashlib.sha256(f"{code}:{salt}:{self._secret}".encode("utf-8")).hexdigest()

    def _cleanup(self) -> None:
        now = _now()
        expired = [pid for pid, entry in self._entries.items() if entry.expires_at <= now]
        for pid in expired:
            self._entries.pop(pid, None)
        if expired:
            self._persist()

    def create(self, user_id: str, channels: List[str]) -> Tuple[str, str]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = uuid.uuid4().hex[:12]
        pending_id = uuid.uuid4().hex
        challenge = OtpChallenge(
            pending_id=pending_id,
            user_id=user_id,
            code_hash=self._hash_code(code, salt),
            salt=salt,
            expires_at=_now() + self.ttl,
            channels=channels,
            attempts=0,
            resend_available_at=_now() + self.cooldown,
            last_sent_at=_now(),
        )
        with self._lock:
            self._cleanup()
            self._entries[pending_id] = challenge
            self._persist()
        return pending_id, code

    def verify(self, pending_id: str, code: str) -> Optional[str]:
        with self._lock:
            self._cleanup()
            challenge = self._entries.get(pending_id)
            if not challenge:
                return None
            if challenge.attempts >= self.max_attempts:
                self._entries.pop(pending_id, None)
                self._persist()
                return None
            challenge.attempts += 1
            expected = self._hash_code(code, challenge.salt)
            if expected != challenge.code_hash:
                self._persist()
                return None
            if challenge.expires_at <= _now():
                self._entries.pop(pending_id, None)
                self._persist()
                return None
            # Success path
            self._entries.pop(pending_id, None)
            self._persist()
            return challenge.user_id

    def resend(self, pending_id: str) -> Optional[Tuple[str, str, List[str]]]:
        with self._lock:
            self._cleanup()
            challenge = self._entries.get(pending_id)
            if not challenge:
                return None
            now = _now()
            if now < challenge.resend_available_at:
                raise ValueError("Resend requested too soon")
            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge.salt = uuid.uuid4().hex[:12]
            challenge.code_hash = self._hash_code(code, challenge.salt)
            challenge.expires_at = now + self.ttl
            challenge.resend_available_at = now + self.cooldown
            challenge.last_sent_at = now
            challenge.attempts = 0
            self._persist()
            return code, challenge.user_id, list(challenge.channels)

    def get_challenge(self, pending_id: str) -> Optional[OtpChallenge]:
        with self._lock:
            self._cleanup()
            challenge = self._entries.get(pending_id)
            return deepcopy(challenge) if challenge else None

