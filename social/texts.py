"""Textes proposés pour chaque canal, en français, en anglais ou les deux, modifiables avant publication dans /gestion/."""

from django.conf import settings
from django.utils import translation

from core import markdown

from .models import LIMIT
from .visuals import emoji_free, labels

# Formules des textes, par langue
WORDS = {
    "fr": {"register": "Inscription et infos : lien en bio · ajc06.com", "info": "Infos : lien en bio · ajc06.com",
           "signup": "Inscription", "all": "Toutes les infos", "hello": "Bonjour,", "bye": "À bientôt,\nL'équipe de l'AJC06"},
    "en": {"register": "Registration and info: link in bio · ajc06.com", "info": "Info: link in bio · ajc06.com",
           "signup": "Registration", "all": "All the details", "hello": "Hello,", "bye": "See you soon,\nThe AJC06 team"},
}
SEPARATOR = "\n\n— English below —\n\n"


def shorten(text, limit):
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def parts(event, lang):
    """Morceaux du texte dans une langue : en-tête (titre, date, lieu, prix), accroche, description, adresse."""
    from events.models import TYPE_EMOJIS

    with translation.override(lang):
        info = labels(event, lang)
        url = settings.SITE_URL + event.get_absolute_url()
        teaser = event.summary_tr or markdown.plain(event.body_tr, 600)
        body = markdown.plain(event.body_tr, 3000) if event.body_tr else teaser
    lines = [f"{TYPE_EMOJIS.get(event.main_type, '📍')} {info['title']}", f"📅 {info['date']} · {info['time']}"]
    if info["place"]:
        lines.append(f"📍 {info['place']}")
    if info["price"]:
        lines.append(f"🎟️ {info['price']}")
    return {"head": "\n".join(lines), "teaser": teaser, "body": body, "url": url, "w": WORDS[lang]}


def one_language(event, network, lang):
    p, w = parts(event, lang), WORDS[lang]
    sep = ": " if lang == "en" else " : "  # typographie anglaise / française
    if network == "instagram":
        return f"{p['head']}\n\n{p['teaser']}\n\n{w['register'] if event.registration_url else w['info']}"
    if network == "facebook":
        link = f"👉 {w['signup']}{sep}{event.registration_url}\n" if event.registration_url else ""
        return f"{p['head']}\n\n{p['teaser']}\n\n{link}👉 {p['url']}"
    # Courriel : texte brut, sans hashtags ; la version HTML reprend le visuel et un bouton.
    link = f"\n{w['signup']}{sep}{event.registration_url}" if event.registration_url else ""
    return f"{w['hello']}\n\n{p['head']}\n\n{p['body']}\n\n{w['all']}{sep}{p['url']}{link}\n\n{w['bye']}"


def default_text(event, network, signature="", language="fr"):
    """language : « fr », « en » ou « both » (français puis anglais)."""
    langs = ["fr", "en"] if language == "both" else [language]
    texts = [one_language(event, network, lang) for lang in langs]
    tail = signature.strip() if network != "email" else ""
    if network == "instagram" and len(texts) == 2:  # 2 200 caractères : chaque langue se partage la place
        room = (LIMIT[network] - len(tail) - len(SEPARATOR) - 4) // 2
        texts = [shorten(t, room) for t in texts]
    text = SEPARATOR.join(texts)
    return shorten(f"{text}\n\n{tail}".strip(), LIMIT[network])


def default_subject(event, language="fr"):
    subjects = []
    for lang in (["fr", "en"] if language == "both" else [language]):
        with translation.override(lang):
            info = labels(event, lang)
        subjects.append(f"{info['title']} — {info['date']}")
    return emoji_free(" / ".join(subjects))[:200]


def alt_text(event, language="fr"):
    lang = "en" if language == "en" else "fr"
    info = labels(event, lang)
    if lang == "en":
        start = f"Image for the AJC06 event “{info['title']}”, {info['date']}"
    else:
        start = f"Visuel de l'événement « {info['title']} » de l'AJC06, {info['date']}"
    with translation.override(lang):
        teaser = event.teaser
    return (start + (f", {info['place']}" if info["place"] else "") + f". {teaser}")[:1000]
