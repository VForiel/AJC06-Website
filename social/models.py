from django.conf import settings
from django.db import models
from django.utils import timezone


class Network(models.TextChoices):
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    EMAIL = "email", "Courriel"


# Visuel utilisé par canal (social.visuals.FORMATS) et longueur maximale du texte.
LANGUAGES = [("fr", "Français"), ("en", "Anglais"), ("both", "Les deux")]
FORMAT = {"instagram": "portrait", "facebook": "portrait", "email": "og"}
LIMIT = {"instagram": 2200, "facebook": 5000, "email": 20000}


class PostQuerySet(models.QuerySet):
    def due(self):
        return self.filter(status=Post.Status.SCHEDULED, scheduled_at__lte=timezone.now())


class Post(models.Model):
    """Diffusion d'un événement sur Instagram, Facebook ou par courriel, immédiate ou programmée
    (envoyée par `manage.py send_posts`, lancé par le cron et par le passage régulier sur robots.txt)."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programmée"
        SENDING = "sending", "En cours d'envoi"
        PUBLISHED = "published", "Publiée"
        FAILED = "failed", "Échec"
        CANCELLED = "cancelled", "Annulée"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="posts")
    network = models.CharField("canal", max_length=10, choices=Network.choices)
    text = models.TextField("texte")
    language = models.CharField("langue", max_length=4, choices=LANGUAGES, default="fr")
    subject = models.CharField("objet du courriel", max_length=200, blank=True)
    recipients = models.TextField("destinataires", blank=True, help_text="Une adresse par ligne (courriel seulement)")
    scheduled_at = models.DateTimeField("prévue le", default=timezone.now, db_index=True)
    status = models.CharField("état", max_length=10, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    attempts = models.PositiveSmallIntegerField("tentatives", default=0)
    external_id = models.CharField("identifiant sur le réseau", max_length=200, blank=True)
    external_url = models.URLField("lien de la publication", blank=True, max_length=500)
    error = models.TextField("erreur", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField("publiée le", null=True, blank=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-scheduled_at"]
        verbose_name = "diffusion"

    def __str__(self):
        return f"{self.get_network_display()} — {self.event}"

    @property
    def visual_format(self):
        return FORMAT[self.network]

    @property
    def visual_language(self):
        """Visuel en anglais seulement pour une diffusion tout en anglais (bilingue : visuel français)."""
        return "en" if self.language == "en" else "fr"

    @property
    def recipient_list(self):
        return [line.strip() for line in self.recipients.replace(",", "\n").replace(";", "\n").splitlines() if line.strip()]
