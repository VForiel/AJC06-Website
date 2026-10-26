from django.conf import settings
from django.db import models

from .crypto import EncryptedTextField

ACCOUNT_MODES = [
    ("aucune", "Aucune : compte actif dès l'inscription"),
    ("bureau", "Par le bureau, dans /gestion/comptes/ (sans serveur mail)"),
    ("courriel", "Par lien envoyé par courriel (SMTP indispensable)"),
]


def initial_values():
    """Valeurs de départ tirées des anciennes variables d'environnement (.env), pour que la bascule vers les réglages
    en base ne change rien au fonctionnement du site."""
    smtp = settings.ENV_EMAIL_BACKEND.endswith("smtp.EmailBackend") and settings.EMAIL_HOST not in ("", "localhost")
    mode = getattr(settings, "ACCOUNT_VALIDATION", "")
    if mode not in dict(ACCOUNT_MODES):
        mode = "courriel" if getattr(settings, "ACCOUNT_EMAIL_CONFIRMATION", False) else "aucune"
    return {
        "smtp_host": settings.EMAIL_HOST if smtp else "",
        "smtp_port": settings.EMAIL_PORT,
        "smtp_security": "ssl" if settings.EMAIL_USE_SSL else "starttls" if settings.EMAIL_USE_TLS else "none",
        "smtp_user": settings.EMAIL_HOST_USER,
        "smtp_password": settings.EMAIL_HOST_PASSWORD,
        "from_email": settings.DEFAULT_FROM_EMAIL,
        "contact_email": settings.CONTACT_EMAIL,
        "account_validation": mode,
        "helloasso_client_id": settings.HELLOASSO_CLIENT_ID,
        "helloasso_client_secret": settings.HELLOASSO_CLIENT_SECRET,
        "helloasso_organization": settings.HELLOASSO_ORGANIZATION,
        "legal_host": settings.LEGAL_HOST,
    }


class SiteConfig(models.Model):
    """Réglages du site modifiables depuis /gestion/reglages/ (une seule ligne, pk = 1), à la place du .env."""

    class Security(models.TextChoices):
        SSL = "ssl", "SSL/TLS (port 465)"
        STARTTLS = "starttls", "STARTTLS (port 587)"
        NONE = "none", "Aucune (déconseillé)"

    # Courriel
    smtp_host = models.CharField("serveur SMTP", max_length=200, blank=True,
                                 help_text="Ex. mail.ajc06.com. Vide : les courriels s'affichent dans les journaux au lieu de partir.")
    smtp_port = models.PositiveIntegerField("port", default=465)
    smtp_security = models.CharField("sécurité", max_length=10, choices=Security.choices, default=Security.SSL)
    smtp_user = models.CharField("identifiant", max_length=200, blank=True, help_text="En général l'adresse complète.")
    smtp_password = EncryptedTextField("mot de passe", blank=True)
    from_email = models.CharField("expéditeur", max_length=200, default="AJC06 <no-reply@ajc06.com>",
                                  help_text="Nom et adresse affichés aux destinataires. L'adresse doit être celle du compte SMTP.")
    contact_email = models.EmailField("adresse de contact", default="contact@ajc06.com",
                                      help_text="Reçoit les messages du formulaire de contact ; affichée sur le site.")

    # Comptes membres
    account_validation = models.CharField("validation des nouveaux comptes", max_length=10, choices=ACCOUNT_MODES, default="bureau",
                                          help_text="« Par lien » seulement une fois le courriel de test reçu.")

    # HelloAsso (API v5) : nombre d'inscrit·es aux événements
    helloasso_client_id = models.CharField("HelloAsso : client_id", max_length=200, blank=True)
    helloasso_client_secret = EncryptedTextField("HelloAsso : client_secret", blank=True)
    helloasso_organization = models.CharField("HelloAsso : organisation", max_length=200,
                                              default="association-des-jeunes-chercheurs-des-alpes-mariti",
                                              help_text="Identifiant de l'asso dans les adresses helloasso.com/associations/…")

    legal_host = models.TextField("hébergeur (mentions légales)", blank=True,
                                  help_text="Nom, adresse et téléphone de l'hébergeur actuel du site.")

    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "réglages du site"
        verbose_name_plural = "réglages du site"

    def __str__(self):
        return "Réglages du site"

    @classmethod
    def get(cls):
        config = cls.objects.filter(pk=1).first()
        if config is None:
            config, _ = cls.objects.get_or_create(pk=1, defaults=initial_values())
        return config

    @property
    def smtp_ready(self):
        return bool(self.smtp_host)

    @property
    def helloasso_ready(self):
        return bool(self.helloasso_client_id and self.helloasso_client_secret)


class ConfigChange(models.Model):
    """Journal des modifications des réglages : qui, quand, quels champs (jamais les valeurs des secrets)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, verbose_name="par")
    changed_at = models.DateTimeField("le", auto_now_add=True)
    fields = models.CharField("réglages modifiés", max_length=500)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name = "modification des réglages"
        verbose_name_plural = "modifications des réglages"

    def __str__(self):
        return f"{self.changed_at:%d/%m/%Y %H:%M} — {self.fields}"
