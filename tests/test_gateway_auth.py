import time

import httpx
import pytest
from httpx import ASGITransport

from backend.gateway import api
from backend.gateway.auth_store import OtpChallengeStore, UserRecord, UserStore


@pytest.mark.asyncio
async def test_login_and_verify_flow(tmp_path, monkeypatch):
    user_store_path = tmp_path / "users.json"
    otp_store_path = tmp_path / "otp.json"
    monkeypatch.setenv("DFS_USER_STORE", str(user_store_path))
    monkeypatch.setenv("DFS_OTP_STORE", str(otp_store_path))
    monkeypatch.setenv("DFS_AUTH_SECRET", "unit-test-secret")

    user_store = UserStore(path=str(user_store_path))
    otp_store = OtpChallengeStore(path=str(otp_store_path))
    api.user_store = user_store
    api.otp_store = otp_store

    password = "SuperSecret123!"
    record = UserRecord(
        user_id="user-1",
        email="admin@example.com",
        password_hash="unused",
        phone_number="+15551234567",
        otp_channels=["email", "sms"],
        created_at=time.time(),
    )
    user_store.add_user(record)

    captured_code: dict[str, str] = {}

    def fake_verify(email: str, provided_password: str):
        if email == record.email and provided_password == password:
            return record
        return None

    async def fake_dispatch(user, code: str, channels):  # type: ignore[override]
        captured_code["value"] = code
        return None

    monkeypatch.setattr(api, "_dispatch_otp", fake_dispatch)
    monkeypatch.setattr(user_store, "verify_password", fake_verify)

    async with httpx.AsyncClient(transport=ASGITransport(app=api.app), base_url="http://test") as client:
        login_resp = await client.post(
            "/auth/login",
            json={"email": record.email, "password": password, "channel": "email"},
        )
        login_resp.raise_for_status()
        payload = login_resp.json()
        assert payload["pending_token"]
        assert captured_code.get("value") is not None

        verify_resp = await client.post(
            "/auth/otp/verify",
            json={"pending_token": payload["pending_token"], "code": captured_code["value"]},
        )
        verify_resp.raise_for_status()
        token_payload = verify_resp.json()
        assert token_payload["access_token"]
        assert token_payload["user"]["email"] == record.email

        me_resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token_payload['access_token']}"},
        )
        me_resp.raise_for_status()
        assert me_resp.json()["email"] == record.email