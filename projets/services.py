"""Règles métier des dossiers : pré-remplissage, acceptation des demandes de soutien, échéances."""

import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core import markdown

from .models import BudgetLine, Dossier, SupportRequest

# Délais imposés par la convention UniCA – AJC06 et l'usage avec la DVU.
FORECAST_DAYS_BEFORE = 14  # projet prévisionnel transmis au plus tard deux semaines avant
SUPPORT_DAYS_BEFORE = 30   # demande de soutien d'un·e membre au moins un mois avant

DEFAULT_OBJECTIVES = (
    "Favoriser le bien-être : offrir un moment de déconnexion et de détente.\n"
    "Renforcer les liens : encourager les échanges entre doctorant·e·s de toutes disciplines.\n"
    "Rendre l'activité accessible : permettre la participation grâce au soutien de l'AJC06."
)
DEFAULT_IMPACT = (
    "Améliorer la qualité de vie des doctorant·e·s.\n"
    "Favoriser la création d'un réseau interdisciplinaire.\n"
    "Développer le sentiment d'appartenance à Université Côte d'Azur."
)
AMOUNT = re.compile(r"(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:€|eur|euros?)?\s*$", re.I)
INCOME_WORDS = ("recette", "participation", "subvention", "billetterie", "inscription")


def convention_line(event):
    codes = set(event.type_codes)
    if "camp" in codes:
        return Dossier.Line.CAMP
    if "rentree" in codes:
        return Dossier.Line.ACCUEIL
    return Dossier.Line.MEETUP


def parse_budget(text):
    """« Location : 250 € » -> [(« Location », Decimal("250"), « depense »)] ; les recettes sont reconnues aux mots-clés."""
    rows = []
    for raw in (text or "").splitlines():
        line = raw.strip(" -•\t")
        match = AMOUNT.search(line)
        if not line or not match:
            continue
        try:
            amount = Decimal(match.group(1).replace(" ", "").replace(",", "."))
        except InvalidOperation:
            continue
        label = line[: match.start()].rstrip(" :=–-") or line
        side = BudgetLine.Side.INCOME if any(w in label.lower() for w in INCOME_WORDS) else BudgetLine.Side.EXPENSE
        rows.append((label[:200], amount, side))
    return rows


def dossier_for(event):
    """Dossier de l'événement, créé et pré-rempli au premier accès."""
    dossier = Dossier.objects.filter(event=event).first()
    if dossier:
        return dossier
    support = SupportRequest.objects.filter(event=event).first()
    programme = ""
    if event.start_time:
        programme = f"{event.start_time:%Hh%M} : accueil des participant·e·s"
        if event.end_time:
            programme += f"\n{event.end_time:%Hh%M} : fin de l'événement"
    dossier = Dossier.objects.create(
        event=event,
        convention_line=convention_line(event),
        resume=event.summary or markdown.plain(event.body, 600),
        objectives=DEFAULT_OBJECTIVES,
        audience=(f"L'événement est ouvert à {event.capacity} doctorant·e·s maximum." if event.capacity
                  else "L'événement est ouvert à tous les doctorant·e·s d'Université Côte d'Azur."),
        transport=(support.access[:300] if support else ""),
        services=(support.price_per_person if support else event.price),
        programme=programme,
        impact=DEFAULT_IMPACT,
    )
    if support:
        rows = parse_budget(support.budget_details)
        for n, (label, amount, side) in enumerate(rows):
            BudgetLine.objects.create(dossier=dossier, label=label, amount=amount, side=side, order=n)
        BudgetLine.objects.create(dossier=dossier, label="Convention UniCA", amount=support.amount,
                                  side=BudgetLine.Side.INCOME, order=len(rows))
    return dossier


def approve(support, user, note=""):
    event = support.event
    support.status = SupportRequest.Status.APPROVED
    support.decision_note, support.decided_by, support.decided_at = note, user, timezone.now()
    support.save()
    # Événement de l'asso désormais : en attente le temps du dossier auprès de l'université.
    event.supported = True
    event.is_published = True
    event.on_hold = True
    event.save(update_fields=["supported", "is_published", "on_hold"])
    dossier_for(event)


def refuse(support, user, note=""):
    support.status = SupportRequest.Status.REFUSED
    support.decision_note, support.decided_by, support.decided_at = note, user, timezone.now()
    support.save()


def forecast_deadline(event):
    return event.start_date - timedelta(days=FORECAST_DAYS_BEFORE)


def deadlines(events):
    """Échéances des dossiers : projet prévisionnel (J-14) et bilan (après l'événement)."""
    today = timezone.localdate()
    out = []
    for event in events:
        dossier = getattr(event, "dossier", None)
        if event.is_upcoming:
            if not (dossier and dossier.submitted_at):
                due = event.start_date - timedelta(days=FORECAST_DAYS_BEFORE)
                out.append({"event": event, "what": "Projet prévisionnel", "due": due, "late": due < today})
        elif event.last_date >= today - timedelta(days=120) and not (dossier and dossier.report_submitted_at):
            out.append({"event": event, "what": "Bilan", "due": None, "late": False})
    return sorted(out, key=lambda d: (d["due"] is None, d["due"] or today))
