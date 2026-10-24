"""Génération iCalendar (RFC 5545) sans dépendance."""

from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from core import markdown


def _escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line):
    """Coupe les lignes à 75 octets comme l'exige la norme."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > (75 if not out else 74):
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def _utc(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def vevent(event):
    url = settings.SITE_URL + event.get_absolute_url()
    lines = ["BEGIN:VEVENT", f"UID:event-{event.pk}@ajc06.com", f"DTSTAMP:{_utc(event.updated_at or timezone.now())}"]
    if event.all_day:
        lines.append(f"DTSTART;VALUE=DATE:{event.start_date:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{event.last_date + timedelta(days=1):%Y%m%d}")
    else:
        lines.append(f"DTSTART:{_utc(event.starts_at)}")
        lines.append(f"DTEND:{_utc(event.ends_at)}")
    lines.append(f"SUMMARY:{_escape(event.title_tr)}")
    description = markdown.plain(event.body_tr, 1500)
    if event.registration_url:
        description += "\n\n" + _("Inscription : %(url)s") % {"url": event.registration_url}
    lines.append(f"DESCRIPTION:{_escape(description + chr(10) + chr(10) + url)}")
    location = ", ".join(p for p in (event.venue, event.address) if p)
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if event.latitude is not None and event.longitude is not None:
        lines.append(f"GEO:{event.latitude};{event.longitude}")
    lines += [f"URL:{url}", "END:VEVENT"]
    return lines


def calendar(events, name="AJC06"):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AJC06//Site//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "X-WR-TIMEZONE:Europe/Paris",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    for event in events:
        lines += vevent(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
