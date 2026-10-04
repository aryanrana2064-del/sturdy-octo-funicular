"""WhatsApp helpers: phone cleaning, click-to-chat links and ready-made messages.

WhatsApp cannot be given a file from outside (that needs the paid WhatsApp Business API), so the app
opens the customer's chat with the message already typed and shows the saved PDF for you to attach.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from . import dates, money

DEFAULT_COUNTRY = "91"  # India


def normalize_phone(mobile: str, default_country: str = DEFAULT_COUNTRY) -> Optional[str]:
    """Digits-only international number for wa.me (e.g. '9876543210' -> '919876543210'); None if unusable."""
    text = (mobile or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif not text.startswith("+"):
        if len(digits) == 10:
            digits = default_country + digits
        elif len(digits) == 11 and digits.startswith("0"):
            digits = default_country + digits[1:]
    return digits if 8 <= len(digits) <= 15 else None


def chat_url(phone: Optional[str], text: str) -> str:
    """Link that opens WhatsApp with the message typed. Without a phone, WhatsApp asks whom to send it to."""
    base = f"https://wa.me/{phone}" if phone else "https://wa.me/"
    return f"{base}?text={quote(text)}"


def _money_line(balance_paise: int) -> str:
    if balance_paise > 0:
        return f"Abhi tak ka baaki: {money.format_inr(balance_paise)}"
    if balance_paise < 0:
        return f"Aapka {money.format_inr(-balance_paise)} advance jama hai."
    return "Aapka khata barabar hai (kuch baaki nahi)."


def statement_message(name: str, brand: str, balance_paise: int, period: str) -> str:
    return (f"Namaste {name} ji,\n{brand} ki taraf se aapka khata statement ({period}) bhej rahe hain. "
            f"PDF is chat me attach hai.\n{_money_line(balance_paise)}\nDhanyavaad.")


def reminder_message(name: str, brand: str, balance_paise: int, days: int, since_iso: str) -> str:
    return (f"Namaste {name} ji,\n{brand} me aapka {money.format_inr(balance_paise)} baaki hai "
            f"({dates.format_date(since_iso)} se, {days} din se). Kripya jaldi jama kar dein.\nDhanyavaad.")
