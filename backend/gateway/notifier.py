import logging
import os
from typing import Optional

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
except ImportError:  # pragma: no cover - optional dependency guard
    SendGridAPIClient = None  # type: ignore
    Mail = None  # type: ignore

try:
    from twilio.rest import Client as TwilioClient
except ImportError:  # pragma: no cover
    TwilioClient = None  # type: ignore


class NotificationService:
    def __init__(self) -> None:
        self._sendgrid_key = os.getenv("SENDGRID_API_KEY")
        self._from_email = os.getenv("SENDGRID_FROM_EMAIL")
        self._twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self._twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
        self._twilio_from = os.getenv("TWILIO_FROM_NUMBER")

    def send_email_code(self, to_email: str, otp_code: str) -> None:
        if not to_email:
            logging.warning("Attempted to send OTP email without recipient")
            return
        if not self._sendgrid_key or not self._from_email or not SendGridAPIClient or not Mail:
            logging.warning("SendGrid not fully configured; OTP for %s = %s", to_email, otp_code)
            return
        message = Mail(
            from_email=self._from_email,
            to_emails=to_email,
            subject="Your Phineas Cloud verification code",
            plain_text_content=f"Use this code to finish signing in: {otp_code}. It expires in 5 minutes.",
        )
        try:
            client = SendGridAPIClient(self._sendgrid_key)
            client.send(message)
        except Exception as exc:  # pragma: no cover - network/env issues
            logging.error("SendGrid delivery failed for %s: %s", to_email, exc)
            raise

    def send_sms_code(self, to_number: Optional[str], otp_code: str) -> None:
        if not to_number:
            logging.warning("Attempted to send OTP SMS without phone number")
            return
        if not (self._twilio_sid and self._twilio_token and self._twilio_from and TwilioClient):
            logging.warning("Twilio not fully configured; OTP for %s = %s", to_number, otp_code)
            return
        try:
            client = TwilioClient(self._twilio_sid, self._twilio_token)
            client.messages.create(
                body=f"Phineas Cloud code: {otp_code} (valid 5 minutes)",
                from_=self._twilio_from,
                to=to_number,
            )
        except Exception as exc:  # pragma: no cover
            logging.error("Twilio delivery failed for %s: %s", to_number, exc)
            raise

    def notify(self, *, email: str, phone: Optional[str], otp_code: str, channels: list[str]) -> None:
        channels = channels or ["email"]
        if "email" in channels:
            self.send_email_code(email, otp_code)
        if "sms" in channels:
            self.send_sms_code(phone, otp_code)


notification_service = NotificationService()
