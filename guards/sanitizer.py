"""The Sanitizer (Stage 6): the first and cheapest check. Plain code, no model call (S-1).

Julia's decision: an allow-list. Only the kinds of characters a real customer types get
through; anything else stops the message. Attack shapes written in ordinary characters are
the Judge's job, not this one's. Apostrophes and ordinary punctuation, including # $ : ; @,
always pass (S-2).
"""

import unicodedata

MAX_CHARS = 2000  # a support question is a few sentences; this is room, not a target

# Allowed, by Unicode character type: letters in any language, accents, numbers, punctuation,
# symbols and emoji, and spaces. Plus line breaks and tabs.
ALLOWED_TYPES = ("L", "M", "N", "P", "S", "Zs")
ALLOWED_EXTRA = {"\n", "\t", "‍"}  # ‍ joins emoji like 👩‍💻


def check(message: str) -> tuple[bool, str]:
    """Returns (passed, detail)."""
    if len(message) > MAX_CHARS:
        return False, f"too long: {len(message)} characters (limit {MAX_CHARS})"
    for ch in message:
        kind = unicodedata.category(ch)
        if ch not in ALLOWED_EXTRA and not kind.startswith(ALLOWED_TYPES):
            return False, f"character not allowed: U+{ord(ch):04X} ({unicodedata.name(ch, kind)})"
    return True, f"{len(message)} characters, all allowed"
