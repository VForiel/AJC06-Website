"""Dossiers auprès de l'université : demandes de soutien, projets prévisionnels, bilans, billets HelloAsso.

La convention d'objectifs et de moyens UniCA – AJC06 (2026-2028) finance trois lignes de projets ; chaque projet
est déposé auprès de la Direction de la vie universitaire (descriptif, budget, justificatifs) avant l'événement,
puis justifié par un bilan après.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from events.models import Event


class SupportRequest(models.Model):
    """Demande de soutien de l'asso pour une sortie proposée par un·e membre."""

    class Status(models.TextChoices):
        PENDING = "attente", "En attente"
        APPROVED = "acceptee", "Acceptée"
        REFUSED = "refusee", "Refusée"

    class Booking(models.TextChoices):
        ASSO = "asso", _("L'AJC06 se charge des réservations")
        REFUND = "remboursement", _("J'avance les frais, remboursés sur factures")

    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="support_request")
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    amount = models.DecimalField(_("somme demandée à l'asso (€)"), max_digits=8, decimal_places=2)
    access = models.TextField(_("comment y aller"), help_text=_("Transport, point de rendez-vous, covoiturage…"))
    price_per_person = models.CharField(_("prix par personne"), max_length=200,
                                        help_text=_("Ex. 35 € (jeu + pizza + boisson)"))
    fixed_costs = models.CharField(_("coûts fixes"), max_length=200, blank=True,
                                   help_text=_("Ex. location de salle 150 €, guide 200 €"))
    budget_details = models.TextField(_("détail du budget"),
                                      help_text=_("Une ligne par poste : intitulé, montant. Recettes prévues (participation…)."))
    booking = models.CharField(_("réservations"), max_length=20, choices=Booking.choices, default=Booking.ASSO)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    decision_note = models.TextField("réponse du bureau", blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "demande de soutien"
        verbose_name_plural = "demandes de soutien"

    def __str__(self):
        return f"{self.event.title} — {self.amount} € ({self.get_status_display()})"


class Dossier(models.Model):
    """Projet prévisionnel (avant) et bilan (après) d'un événement de l'asso, pour l'université."""

    class Line(models.TextChoices):
        ACCUEIL = "accueil", "Journée d'accueil des doctorants (5 000 € max.)"
        MEETUP = "meetup", "PhD meet-up (4 000 € max.)"
        CAMP = "camp", "PhD seasonal camps (9 000 € max.)"
        FONCTIONNEMENT = "fonctionnement", "Fonctionnement"
        AUTRE = "autre", "Hors convention"

    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="dossier")
    convention_line = models.CharField("ligne de la convention", max_length=20, choices=Line.choices, default=Line.MEETUP)
    # Projet prévisionnel
    resume = models.TextField("résumé", blank=True)
    objectives = models.TextField("objectifs", blank=True,
                                  help_text="Un par ligne, « Titre : explication » pour mettre le titre en gras")
    audience = models.TextField("public visé", blank=True)
    transport = models.CharField("transport", max_length=300, blank=True)
    services = models.TextField("prestations", blank=True, help_text="Prestataire, formule, prix par personne")
    equipment = models.CharField("matériel", max_length=300, blank=True)
    programme = models.TextField("programme prévisionnel", blank=True, help_text="Une étape par ligne : « 19h00 : arrivée »")
    impact = models.TextField("impact attendu", blank=True, help_text="Un par ligne")
    quotes = models.TextField("devis", blank=True, help_text="Liens ou précisions sur les devis (les fichiers vont dans les pièces jointes)")
    submitted_at = models.DateField("projet transmis le", null=True, blank=True)
    # Bilan
    report_story = models.TextField("déroulement", blank=True)
    report_assessment = models.TextField("bilan", blank=True)
    objectives_met = models.TextField("objectifs atteints", blank=True, help_text="Un par ligne")
    registered_count = models.PositiveIntegerField("inscrit·es", null=True, blank=True)
    present_count = models.PositiveIntegerField("présent·es", null=True, blank=True)
    report_submitted_at = models.DateField("bilan transmis le", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "dossier université"

    def __str__(self):
        return f"Dossier — {self.event.title}"

    def lines(self, phase):
        return self.budget_lines.filter(phase=phase)

    def totals(self, phase):
        lines = self.lines(phase)
        spend = sum((l.amount for l in lines if l.side == BudgetLine.Side.EXPENSE), Decimal(0))
        income = sum((l.amount for l in lines if l.side == BudgetLine.Side.INCOME), Decimal(0))
        return spend, income


class BudgetLine(models.Model):
    class Phase(models.TextChoices):
        FORECAST = "prev", "Prévisionnel"
        ACTUAL = "reel", "Réalisé"

    class Side(models.TextChoices):
        EXPENSE = "depense", "Dépense"
        INCOME = "recette", "Recette"

    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="budget_lines")
    phase = models.CharField(max_length=4, choices=Phase.choices, default=Phase.FORECAST)
    side = models.CharField(max_length=8, choices=Side.choices, default=Side.EXPENSE)
    label = models.CharField("intitulé", max_length=200)
    amount = models.DecimalField("montant (€)", max_digits=9, decimal_places=2)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["phase", "order", "id"]


class Attachment(models.Model):
    class Kind(models.TextChoices):
        INVOICE = "facture", "Facture"
        QUOTE = "devis", "Devis"
        PHOTO = "photo", "Photo"
        OTHER = "autre", "Autre"

    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="attachments")
    kind = models.CharField("type", max_length=10, choices=Kind.choices, default=Kind.INVOICE)
    file = models.FileField("fichier", upload_to="dossiers/%Y/")
    label = models.CharField("légende", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "created_at"]
        verbose_name = "pièce jointe"

    def __str__(self):
        return self.label or self.file.name.rsplit("/", 1)[-1]

    @property
    def is_image(self):
        return self.file.name.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp")

    @property
    def is_pdf(self):
        return self.file.name.lower().endswith(".pdf")


class HelloAssoTicket(models.Model):
    """Billet HelloAsso d'un événement (synchronisé) : sert au comptage public et aux listes des bilans."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="helloasso_tickets")
    ticket_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    tier = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # Adresse du participant, sinon celle du payeur : sert à relier le billet à un compte du site
    email = models.EmailField(blank=True, db_index=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class HelloAssoUnlink(models.Model):
    """Participation reliée depuis HelloAsso puis retirée par la personne : la synchro ne la recrée pas."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "event"], name="unique_helloasso_unlink")]
