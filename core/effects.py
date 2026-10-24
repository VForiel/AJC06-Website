"""Effets saisonniers du site, cumulables, déclenchés automatiquement selon la date (heure de Paris).

Chaque effet a une fenêtre d'affichage ; le bureau peut en forcer l'aperçu depuis /gestion/effets/.
"""

from datetime import date, timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

FOUNDED = date(1996, 4, 24)


def easter(year):
    """Dimanche de Pâques (calendrier grégorien, algorithme de Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def windows(year):
    """{code: (début, fin incluse)} pour l'année donnée."""
    sunday = easter(year)
    return {
        "trente": (date(2026, 1, 1), date(2026, 12, 31)),  # 30 ans de l'asso : disparaît le 1er janvier 2027
        "anniversaire": (date(year, 4, 17), date(year, 4, 30)),
        "paques": (sunday - timedelta(days=7), sunday + timedelta(days=1)),
        "pride": (date(year, 6, 1), date(year, 6, 30)),
        "halloween": (date(year, 10, 24), date(year, 11, 1)),
        "noel": (date(year, 12, 1), date(year, 12, 26)),
        "nouvel-an": (date(year, 12, 29), date(year + 1, 1, 3)),
    }


EFFECTS = {
    "trente": _("30 ans de l'AJC06"),
    "anniversaire": _("Anniversaire de l'AJC06"),
    "paques": _("Pâques"),
    "pride": _("Mois des fiertés"),
    "halloween": _("Halloween"),
    "noel": _("Noël"),
    "nouvel-an": _("Nouvel an"),
}


def active(today=None):
    today = today or timezone.localdate()
    codes = []
    for year in (today.year - 1, today.year):  # la fenêtre du nouvel an chevauche deux années
        for code, (start, end) in windows(year).items():
            if start <= today <= end and code not in codes:
                codes.append(code)
    return [c for c in EFFECTS if c in codes]


def age(today=None):
    today = today or timezone.localdate()
    return today.year - FOUNDED.year - ((today.month, today.day) < (FOUNDED.month, FOUNDED.day))


def calendar(year):
    """Pour l'espace bureau : [(code, libellé, début, fin)] triés par date."""
    rows = [(code, EFFECTS[code], start, end) for code, (start, end) in windows(year).items()
            if code != "trente" or year == 2026]
    return sorted(rows, key=lambda r: r[2])
