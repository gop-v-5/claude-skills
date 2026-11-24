"""Safe user-facing error formatting.

Vendor SDK exceptions sometimes include the full request URL. Meta puts the
access token in that URL, so printing a raw exception or traceback can disclose
credentials in terminals, CI logs, and agent transcripts.
"""
from __future__ import annotations

import re


_QUERY_SECRET = re.compile(
    r"(?i)(access_token|client_secret|api_key|apikey|token)=([^&\s'\"]+)"
)
_BEARER_SECRET = re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s'\"]+)")
_META_TOKEN = re.compile(r"\bEA[A-Za-z0-9_-]{20,}\b")


def redact_secrets(value: object) -> str:
    """Return an exception/message with common credential shapes removed."""
    text = str(value)
    text = _QUERY_SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _BEARER_SECRET.sub(lambda m: f"{m.group(1)}[REDACTED]", text)
    return _META_TOKEN.sub("[REDACTED]", text)


def safe_error(prefix: str, exc: BaseException) -> str:
    """Format one concise, redacted CLI error line."""
    return f"{prefix}: {redact_secrets(exc)}"
