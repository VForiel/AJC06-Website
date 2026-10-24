from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from . import markdown
from .i18n import Translated
from .images import normalize_field, validate_image


class Board(models.Model):
    """Bureau élu pour une année."""

    year = models.PositiveSmallIntegerField("année", unique=True)

    class Meta:
        ordering = ["-year"]
        verbose_name = "bureau"

    def __str__(self):
        return f"Bureau {self.year}"


class Member(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="members", verbose_name="bureau")
    name = models.CharField("nom", max_length=120)
    role = models.CharField("rôle", max_length=80, help_text="Présidente, Trésorier…")
    about = models.CharField("parcours", max_length=200, blank=True, help_text="Ex. Doctorante en astrophysique, ED SFA")
    role_en = models.CharField("rôle (anglais)", max_length=80, blank=True)
    about_en = models.CharField("parcours (anglais)", max_length=200, blank=True)
    photo = models.ImageField(upload_to="equipe/", blank=True, validators=[validate_image])
    linkedin = models.URLField(blank=True)
    order = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        ordering = ["board", "order", "id"]
        verbose_name = "membre du bureau"
        verbose_name_plural = "membres du bureau"

    role_tr = Translated("role")
    about_tr = Translated("about")

    def __str__(self):
        return f"{self.name} ({self.role}, {self.board.year})"

    @property
    def initials(self):
        return "".join(p[0] for p in self.name.replace("-", " ").split()[:2]).upper()

    def save(self, *args, **kwargs):
        normalize_field(self, "photo")
        super().save(*args, **kwargs)


class Resource(models.Model):
    class Category(models.TextChoices):
        DOCTORAT = "doctorat", _("Pendant la thèse")
        UCA = "uca", _("À Université Côte d'Azur")
        APRES = "apres-these", _("Après la thèse")

    title = models.CharField("titre", max_length=160)
    slug = models.SlugField(unique=True, max_length=160)
    category = models.CharField("rubrique", max_length=20, choices=Category.choices)
    summary = models.CharField("résumé", max_length=300)
    body = models.TextField("contenu", help_text="Markdown")
    title_en = models.CharField("titre (anglais)", max_length=160, blank=True)
    summary_en = models.CharField("résumé (anglais)", max_length=300, blank=True)
    body_en = models.TextField("contenu (anglais)", blank=True)
    order = models.PositiveSmallIntegerField("ordre", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "ressource"

    title_tr = Translated("title")
    summary_tr = Translated("summary")
    body_tr = Translated("body")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("core:resource", args=[self.slug])

    @property
    def body_html(self):
        return markdown.render(self.body_tr)


class ContactMessage(models.Model):
    name = models.CharField("nom", max_length=120)
    email = models.EmailField("courriel")
    subject = models.CharField("objet", max_length=40)
    message = models.TextField()
    created_at = models.DateTimeField("reçu le", auto_now_add=True)
    handled = models.BooleanField("traité", default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "message de contact"
        verbose_name_plural = "messages de contact"

    def __str__(self):
        return f"{self.name} — {self.get_subject_display()}"

    def get_subject_display(self):
        return dict(SUBJECTS).get(self.subject, self.subject)


SUBJECTS = [
    ("question", _("Une question")),
    ("rejoindre", _("Rejoindre l'équipe")),
    ("partenariat", _("Proposer un partenariat ou un événement")),
    ("autre", _("Autre chose")),
]


class Upload(models.Model):
    """Image insérée dans le corps d'un article ou d'un événement depuis l'éditeur."""

    file = models.ImageField(upload_to="televersements/%Y/", validators=[validate_image])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "image téléversée"
        verbose_name_plural = "images téléversées"

    def __str__(self):
        return self.file.name

    def save(self, *args, **kwargs):
        normalize_field(self, "file")
        super().save(*args, **kwargs)


class Announcement(models.Model):
    """Bandeau d'annonce en haut de toutes les pages, géré par le bureau dans /gestion/."""

    class Tone(models.TextChoices):
        MIMOSA = "mimosa", "Jaune (mise en avant)"
        AZUR = "azur", "Bleu (information)"
        ALERTE = "alerte", "Rouge (urgent)"

    message = models.CharField("message", max_length=240)
    message_en = models.CharField("message (anglais)", max_length=240, blank=True)
    link_url = models.CharField("lien", max_length=300, blank=True, help_text="Adresse complète ou chemin du site (/evenements/…)")
    link_label = models.CharField("texte du lien", max_length=60, blank=True)
    link_label_en = models.CharField("texte du lien (anglais)", max_length=60, blank=True)
    tone = models.CharField("couleur", max_length=10, choices=Tone.choices, default=Tone.MIMOSA)
    starts_at = models.DateTimeField("début", null=True, blank=True, help_text="Vide = tout de suite")
    ends_at = models.DateTimeField("fin", null=True, blank=True, help_text="Vide = jusqu'à désactivation")
    is_active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    message_tr = Translated("message")
    link_label_tr = Translated("link_label")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "annonce"

    def __str__(self):
        return self.message

    @classmethod
    def current(cls):
        from django.db.models import Q
        from django.utils import timezone

        now = timezone.now()
        return (cls.objects.filter(is_active=True)
                .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
                .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now)).first())


class Ban(models.Model):
    """Adresse IP bloquée après des échecs de connexion (voir core.security)."""

    ip = models.GenericIPAddressField("adresse IP", unique=True)
    until = models.DateTimeField("bloquée jusqu'au")
    reason = models.CharField("motif", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-until"]
        verbose_name = "adresse bloquée"
        verbose_name_plural = "adresses bloquées"

    def __str__(self):
        return f"{self.ip} jusqu'au {self.until:%d/%m %H:%M}"


class LoginFailure(models.Model):
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "échec de connexion"
        verbose_name_plural = "échecs de connexion"
