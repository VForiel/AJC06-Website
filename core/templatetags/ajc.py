from django import template
from django.urls import translate_url
from django.utils.dateformat import format as dformat
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from core.i18n import is_english
from core.images import thumbnail_url

register = template.Library()

# Tracés 24×24, trait 2 px, dessinés pour le site.
ICONS = {
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "external": '<path d="M14 5h5v5M19 5l-8 8M18 14v5H5V6h5"/>',
    "calendar": '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    "pin": '<path d="M12 21s-6-5.6-6-11a6 6 0 0 1 12 0c0 5.4-6 11-6 11z"/><circle cx="12" cy="10" r="2.2"/>',
    "ticket": '<path d="M4 8a2 2 0 0 0 2-2h12a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H6a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z"/><path d="M14 6v12" stroke-dasharray="2 2"/>',
    "euro": '<path d="M17 6.5A6 6 0 0 0 8 12a6 6 0 0 0 9 5.5M5 10.5h8M5 13.5h8"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "rss": '<path d="M5 5a14 14 0 0 1 14 14M5 11a8 8 0 0 1 8 8"/><circle cx="6" cy="18" r="1.2"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "heart": '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    "instagram": '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.2" cy="6.8" r=".6" fill="currentColor"/>',
    "whatsapp": '<path d="M4.5 19.5l1.2-3.6A8 8 0 1 1 8.4 18.6z"/><path d="M9.2 8.6c.2-.5.6-.5.9-.5h.5c.2 0 .4.1.5.4l.7 1.6c.1.2 0 .5-.1.6l-.5.6c-.1.2-.1.4 0 .5a6 6 0 0 0 2.8 2.6c.2.1.4 0 .5-.1l.6-.7c.2-.2.4-.2.6-.1l1.6.8c.2.1.3.3.3.5 0 .7-.4 1.4-1.1 1.6-.7.3-1.6.3-3-.3a8.6 8.6 0 0 1-4.1-4c-.6-1.2-.4-2.3-.2-2.9z" fill="currentColor" stroke="none"/>',
    "discord": '<path d="M8.5 7.5C7 7.8 5.8 8.3 4.8 9 3.4 11.4 3 14 3.2 16.6c1.3 1 2.8 1.7 4.3 2.1l1-1.6M15.5 7.5c1.5.3 2.7.8 3.7 1.5 1.4 2.4 1.8 5 1.6 7.6-1.3 1-2.8 1.7-4.3 2.1l-1-1.6M7.5 16.5c2.8 1.3 6.2 1.3 9 0M9 7.2a12 12 0 0 1 6 0"/><circle cx="9.3" cy="13" r="1.1"/><circle cx="14.7" cy="13" r="1.1"/>',
    "facebook": '<path d="M14 21v-7.5h2.6l.4-3H14V8.7c0-.9.3-1.5 1.6-1.5H17V4.5a19 19 0 0 0-2.3-.1C12.4 4.4 11 5.8 11 8.3v2.2H8.5v3H11V21"/>',
    "linkedin": '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M8 10.5V17M8 7.3v.2M12 17v-3.8a2.2 2.2 0 0 1 4.4 0V17M12 10.5V17"/>',
}


@register.simple_tag
def icon(name, size=20, label=""):
    paths = ICONS[name]
    aria = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg class="icon icon-{}" width="{}" height="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" {}>{}</svg>',
        name, size, size, aria, mark_safe(paths),
    )


@register.filter
def when(event):
    """« samedi 17 – dimanche 18 janvier 2026 », « Saturday 17 – Sunday 18 January 2026 »."""
    start, end = event.start_date, event.end_date
    if not event.multi_day:
        return dformat(start, "l j F Y")
    if start.year != end.year:
        return f"{dformat(start, 'j F Y')} – {dformat(end, 'j F Y')}"
    if start.month != end.month:
        return f"{dformat(start, 'l j F')} – {dformat(end, 'l j F Y')}"
    return f"{dformat(start, 'l j')} – {dformat(end, 'l j F Y')}"


def _clock(t):
    if is_english():
        return f"{t.hour}:{t.minute:02d}"
    return f"{t.hour} h {t.minute:02d}" if t.minute else f"{t.hour} h"


@register.filter
def hours(event):
    """« 19 h 30 – 23 h » / « 19:30 – 23:00 », « dès 19 h 30 » ou « toute la journée »."""
    if event.all_day:
        return _("Toute la journée") if not event.multi_day else _("Plusieurs jours")
    if event.end_time:
        return f"{_clock(event.start_time)} – {_clock(event.end_time)}"
    return _("Dès %(heure)s") % {"heure": _clock(event.start_time)}


@register.filter
def countdown(event):
    days = event.days_until
    if days < 0:
        return _("En ce moment")
    if days == 0:
        return _("Aujourd'hui")
    if days == 1:
        return _("Demain")
    return ngettext("Dans %(n)s jour", "Dans %(n)s jours", days) % {"n": days}


MONTHS_SHORT = {
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
DAYS_SHORT = {
    "fr": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


def _lang():
    return "en" if is_english() else "fr"


@register.filter
def month_short(value):
    """Abréviation sans ambiguïté (« juin » / « juil. », « Jun » / « Jul »)."""
    return MONTHS_SHORT[_lang()][value.month - 1]


@register.filter
def day_short(value):
    return f"{DAYS_SHORT[_lang()][value.weekday()]} {value.day} {MONTHS_SHORT[_lang()][value.month - 1]}"


@register.simple_tag(takes_context=True)
def lang_url(context, lang):
    """Adresse de la page courante dans l'autre langue (/equipe/ <-> /en/team/)."""
    request = context["request"]
    return translate_url(request.get_full_path(), lang)


@register.simple_tag
def pending_accounts_count():
    """Nombre de comptes en attente de validation, pour le menu de l'espace bureau."""
    from community.confirmation import pending

    return pending().count()


@register.filter
def thumb(image, size=480):
    """{{ event.poster|thumb:192 }} : URL d'une copie réduite pour les listes et vignettes."""
    return thumbnail_url(image, int(size))
