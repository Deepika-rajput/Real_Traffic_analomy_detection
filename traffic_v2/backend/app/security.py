"""Signed, expiring links so authorities can open evidence without an API key."""
import base64
import hashlib
import hmac
import json
import time

from .config import settings


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(event_id, kind, ttl_s=7 * 24 * 3600):
    payload = _b64(json.dumps({"e": int(event_id), "k": kind, "x": int(time.time() + ttl_s)}).encode())
    mac = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{mac}"


def verify(token, event_id, kind):
    try:
        payload, mac = token.split(".", 1)
        good = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac, good):
            return False
        data = json.loads(_unb64(payload))
        return data["e"] == int(event_id) and data["k"] == kind and data["x"] >= time.time()
    except Exception:
        return False
