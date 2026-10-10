"""Alert channels: Telegram, email (SMTP) and the console. Configure with environment variables;
a channel without settings is skipped. A failed send is logged, never fatal."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

log = logging.getLogger("monitor.alerts")


class Alerter:
    def __init__(self, env: dict | None = None):
        e = env if env is not None else os.environ
        self.tg_token, self.tg_chat = e.get("TELEGRAM_BOT_TOKEN", ""), e.get("TELEGRAM_CHAT_ID", "")
        self.smtp_host, self.smtp_port = e.get("SMTP_HOST", ""), int(e.get("SMTP_PORT", "587") or 587)
        self.smtp_user, self.smtp_pass = e.get("SMTP_USER", ""), e.get("SMTP_PASSWORD", "")
        self.email_to = e.get("ALERT_EMAIL_TO", "")
        self.sent: list[str] = []

    @property
    def channels(self) -> list[str]:
        out = ["console"]
        if self.tg_token and self.tg_chat:
            out.append("telegram")
        if self.smtp_host and self.email_to:
            out.append("email")
        return out

    def send(self, subject: str, body: str) -> None:
        text = f"{subject}\n{body}"
        self.sent.append(text)
        print(f"\n🔔 {text}\n", flush=True)
        if "telegram" in self.channels:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                    json={"chat_id": self.tg_chat, "text": text, "disable_web_page_preview": False},
                    timeout=10,
                )
            except Exception as ex:
                log.warning("Telegram failed: %s", ex)
        if "email" in self.channels:
            try:
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = subject, self.smtp_user or self.email_to, self.email_to
                msg.set_content(body)
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as s:
                    s.starttls()
                    if self.smtp_user:
                        s.login(self.smtp_user, self.smtp_pass)
                    s.send_message(msg)
            except Exception as ex:
                log.warning("Email failed: %s", ex)
