"""Alert workflow: nearest authority -> draft -> (operator confirms event) -> send -> ack/escalate.

Safety rules enforced HERE (not just in the routes):
  * nothing is drafted or sent unless a human operator confirmed the event;
  * SEND_MODE defaults to dry_run (writes .eml files, sends nothing);
  * TEST_RECIPIENT redirects every email to one test inbox.
"""
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from . import security
from .config import settings
from .db import now_iso
from .geo import maps_link, rank_authorities

LABEL_TEXT = {
    "accident": "Possible road accident",
    "sudden_stop": "Sudden stop / stalled vehicle",
    "congestion": "Heavy congestion",
}


class AlertError(Exception):
    pass


def evidence_urls(event_id):
    base = settings.public_base_url
    return (f"{base}/public/events/{event_id}/clip?t={security.sign(event_id, 'clip')}",
            f"{base}/public/events/{event_id}/snapshot?t={security.sign(event_id, 'snapshot')}")


def compose(event, camera, authority, distance_km, ack_token, note=None):
    title = LABEL_TEXT.get(event["label"], event["label"])
    clip_url, snap_url = evidence_urls(event["id"])
    subject = f"[Traffic Alert] {title} - {camera['name']} - {event['started_at']} UTC"
    lines = [
        "TRAFFIC INCIDENT ALERT", "",
        f"Type:        {title} (detector confidence {100 * (event.get('peak_prob') or 0):.0f}%)",
        f"Time (UTC):  {event['started_at']}",
        f"Location:    camera '{camera['name']}' ({camera.get('road_type') or 'road'})",
    ]
    if camera.get("lat") is not None and camera.get("lng") is not None:
        lines += [f"Coordinates: {camera['lat']:.6f}, {camera['lng']:.6f}",
                  f"Map:         {maps_link(camera['lat'], camera['lng'])}"]
    lines += ["", "Evidence (links valid for 7 days):", f"  Video:     {clip_url}", f"  Snapshot:  {snap_url}", "",
              f"Sent to:     {authority['name']} ({authority['type']}), about {distance_km} km from the camera",
              f"Verified by: operator '{event.get('reviewer') or 'operator'}' at {event.get('reviewed_at')} UTC"]
    if note:
        lines += ["", note]
    lines += ["", "Please confirm you received this by opening:",
              f"  {settings.public_base_url}/public/ack/{ack_token}", "",
              "This message was produced by an automated detection system and verified by a human",
              "operator. Please verify on the ground before dispatching resources."]
    return subject, "\n".join(lines)


def _create(db, event, camera, authority, distance_km, note=None):
    token = secrets.token_urlsafe(16)
    subject, body = compose(event, camera, authority, distance_km, token, note)
    aid = db.run(
        "INSERT INTO alerts(event_id, authority_id, to_email, subject, body, status, ack_token, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (event["id"], authority["id"], authority["email"], subject, body, "drafted", token, now_iso()))
    return db.one("SELECT * FROM alerts WHERE id=?", (aid,))


def draft_alerts(db, event_id):
    """Create drafts for the nearest authority of each relevant type. Idempotent."""
    event = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not event:
        raise AlertError("event not found")
    if event["status"] != "confirmed":
        raise AlertError("event must be confirmed by an operator before alerts can be drafted")
    camera = db.one("SELECT * FROM cameras WHERE id=?", (event["camera_id"],))
    if camera["lat"] is None or camera["lng"] is None:
        raise AlertError(f"camera '{camera['name']}' has no coordinates; set lat/lng so the nearest "
                         f"authority can be found")
    types = settings.authority_types.get(event["label"], ["traffic_control"])
    ranked = rank_authorities(db.all("SELECT * FROM authorities WHERE active=1"),
                              camera["lat"], camera["lng"], types, settings.max_radius_km)
    created, problems = [], []
    for t in types:
        already = db.one("SELECT a.id FROM alerts a JOIN authorities au ON au.id=a.authority_id "
                         "WHERE a.event_id=? AND au.type=?", (event_id, t))
        if already:
            continue
        if not ranked[t]:
            problems.append(f"no active '{t}' authority within {settings.max_radius_km:g} km of the camera")
            continue
        best = ranked[t][0]
        created.append(_create(db, event, camera, best, best["distance_km"]))
    return {"created": created, "problems": problems,
            "duplicate_warning": bool(event.get("duplicate_of"))}


def _deliver(alert):
    """Returns (status, error). dry_run writes an .eml file; smtp really sends."""
    to = settings.test_recipient or alert["to_email"]
    subject, body = alert["subject"], alert["body"]
    if settings.test_recipient:
        subject = f"[TEST -> {alert['to_email']}] {subject}"
        body = f"*** TEST MODE: this would have gone to {alert['to_email']} ***\n\n{body}"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.mail_from, to, subject
    msg.set_content(body)
    if settings.send_mode != "smtp":
        settings.ensure_dirs()
        (settings.outbox_dir / f"alert_{alert['id']}.eml").write_text(msg.as_string(), encoding="utf-8")
        return "dry_run", None
    if not settings.smtp_host:
        return "failed", "SMTP_HOST is not set"
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_tls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_pass or "")
            s.send_message(msg)
        return "sent", None
    except Exception as e:                      # noqa: BLE001
        return "failed", f"{type(e).__name__}: {e}"


def send_alert(db, alert_id):
    alert = db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))
    if not alert:
        raise AlertError("alert not found")
    event = db.one("SELECT * FROM events WHERE id=?", (alert["event_id"],))
    if event["status"] != "confirmed":
        raise AlertError("event is not confirmed; refusing to send")
    if alert["status"] in ("sent", "dry_run"):
        return alert                            # never send twice
    status, err = _deliver(alert)
    db.update_fields("alerts", alert_id, status=status, error=err,
                     sent_at=now_iso() if status in ("sent", "dry_run") else None)
    return db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))


def ack(db, token):
    a = db.one("SELECT * FROM alerts WHERE ack_token=?", (token,))
    if not a:
        return None
    if not a["acked_at"]:
        db.update_fields("alerts", a["id"], acked_at=now_iso())
    return db.one("SELECT * FROM alerts WHERE id=?", (a["id"],))


def escalate_overdue(db):
    """Alerts nobody acknowledged in ACK_TIMEOUT_MIN go to the next-nearest authority of the same type."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=settings.ack_timeout_min)).isoformat(
        timespec="seconds")
    overdue = db.all("SELECT * FROM alerts WHERE status IN ('sent','dry_run') AND acked_at IS NULL "
                     "AND escalated=0 AND sent_at <= ?", (cutoff,))
    done = []
    for a in overdue:
        event = db.one("SELECT * FROM events WHERE id=?", (a["event_id"],))
        camera = db.one("SELECT * FROM cameras WHERE id=?", (event["camera_id"],))
        prev = db.one("SELECT * FROM authorities WHERE id=?", (a["authority_id"],))
        db.update_fields("alerts", a["id"], escalated=1)
        if event["status"] != "confirmed" or camera["lat"] is None:
            continue
        ranked = rank_authorities(db.all("SELECT * FROM authorities WHERE active=1"), camera["lat"],
                                  camera["lng"], [prev["type"]], settings.max_radius_km, per_type=10)[prev["type"]]
        used = {r["authority_id"] for r in db.all("SELECT authority_id FROM alerts WHERE event_id=?",
                                                  (event["id"],))}
        nxt = next((r for r in ranked if r["id"] not in used), None)
        if not nxt:
            continue
        note = (f"ESCALATION: '{prev['name']}' did not acknowledge within {settings.ack_timeout_min:g} "
                f"minutes, so this alert was forwarded to you.")
        new = _create(db, event, camera, nxt, nxt["distance_km"], note)
        done.append(send_alert(db, new["id"]))
    return done
