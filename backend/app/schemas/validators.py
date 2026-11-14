"""South Africa–specific input validation shared by the API schemas."""

import re


def normalise_sa_phone(value: str) -> str:
    """Accepts 082 123 4567, 0821234567, 27821234567 or +27821234567 → +27821234567."""
    digits = re.sub(r"[\s\-()]", "", value)
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "27" + digits[1:]
    if not re.fullmatch(r"27\d{9}", digits):
        raise ValueError("Enter a valid South African phone number, e.g. 082 123 4567")
    return "+" + digits


def luhn_valid(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def normalise_id_number(value: str) -> str:
    """13-digit SA ID numbers are checksum-validated; anything else is treated
    as a passport number (6–20 letters/digits) for foreign nationals."""
    v = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{6,20}", v):
        raise ValueError("Enter a valid SA ID number or passport number")
    if v.isdigit() and len(v) == 13 and not luhn_valid(v):
        raise ValueError("This South African ID number is not valid")
    return v
