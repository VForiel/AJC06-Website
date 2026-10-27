"""Textes proposés pour chaque canal, modifiables avant publication dans /gestion/."""

from django.conf import settings
from django.utils import translation

from core import markdown

from .models import LIMIT
from .visuals import emoji_free, labels


def shorten(text, limit):
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def default_text(event, network, signature=""):
    from events.models import TYPE_EMOJIS

    with translation.override("fr"):
        info = labels(event)
        emoji = TYPE_EMOJIS.get(event.main_type, "📍")
        url = settings.SITE_URL + event.get_absolute_url()
        teaser = event.summary or markdown.plain(event.body, 600)
    lines = [f"{emoji} {event.title}", f"📅 {info['date']} · {info['time']}"]
    if info["place"]:
        lines.append(f"📍 {info['place']}")
    if info["price"]:
        lines.append(f"🎟️ {info['price']}")
    head = "\n".join(lines)
    tail = signature.strip()
    register = "Inscription et infos : lien en bio · ajc06.com" if event.registration_url else "Infos : lien en bio · ajc06.com"
    if network == "instagram":
        return shorten(f"{head}\n\n{teaser}\n\n{register}\n\n{tail}".strip(), LIMIT[network])
    if network == "facebook":
        link = f"👉 Inscription : {event.registration_url}\n" if event.registration_url else ""
        return f"{head}\n\n{teaser}\n\n{link}👉 {url}\n\n{tail}".strip()
    # Courriel : texte brut, sans hashtags ; la version HTML reprend le visuel et un bouton.
    body = markdown.plain(event.body, 3000) if event.body else teaser
    link = f"\nInscription : {event.registration_url}" if event.registration_url else ""
    return (f"Bonjour,\n\n{head}\n\n{body}\n\nToutes les infos : {url}{link}\n\nÀ bientôt,\nL'équipe de l'AJC06").strip()


def default_subject(event):
    info = labels(event)
    return emoji_free(f"{event.title} — {info['date']}")[:200]


def alt_text(event):
    info = labels(event)
    return (f"Visuel de l'événement « {info['title']} » de l'AJC06, {info['date']}"
            + (f", {info['place']}" if info["place"] else "") + f". {event.teaser}")[:1000]
