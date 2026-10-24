from datetime import datetime, time, timedelta
from urllib.parse import quote_plus

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core import markdown
from core.i18n import Translated
from core.images import normalize_field, validate_image


# Types d'événement : codes stockés dans Event.types sous la forme « ,code1,code2, ».
# Les trois premiers sont les rendez-vous phares du bureau, réservés à l'espace bureau.
TYPES = [
    ("meetup", _("PhD meet-up"), True),
    ("camp", _("Camp"), True),
    ("rentree", _("Rentrée doctorale"), True),
    ("plein-air", _("Plein air"), False),
    ("culture", _("Culture & découverte"), False),
    ("visite", _("Visite"), False),
    ("asso", _("Vie de l'asso"), False),
    ("afterwork", _("Afterwork"), False),
    ("coworking", _("Coworking"), False),
    ("carriere", _("Carrière & formation"), False),
    ("conference", _("Conférence, workshop, séminaire"), False),
    ("soutenance", _("Soutenance de thèse"), False),
    ("sport", _("Sport"), False),
    ("autre", _("Autre"), False),
]
TYPE_LABELS = {code: label for code, label, _staff in TYPES}
STAFF_TYPES = {code for code, _label, staff in TYPES if staff}
# Émojis affichés devant le libellé sur le site (pas dans les PDF : la police n'en a pas). « Autre » n'en a pas.
TYPE_EMOJIS = {
    "meetup": "🤝", "camp": "⛺", "rentree": "🎒", "plein-air": "🥾", "culture": "🎭", "visite": "🏛️",
    "asso": "📣", "afterwork": "🍻", "coworking": "💻", "carriere": "💼", "conference": "🎤", "soutenance": "🎓",
    "sport": "🏃",
}


def with_emoji(code, label):
    emoji = TYPE_EMOJIS.get(code)
    return f"{emoji} {label}" if emoji else str(label)


def type_choices(staff=False):
    return [(code, with_emoji(code, label)) for code, label, only_staff in TYPES if staff or not only_staff]


class EventQuerySet(models.QuerySet):
    def published(self):
        """Visible sur le site : publié et pas en attente de validation."""
        return self.filter(is_published=True, on_hold=False)

    def with_type(self, code):
        return self.filter(types__contains=f",{code},")

    def official(self):
        """Événements de l'asso : ceux du bureau et les sorties de membres soutenues par l'asso."""
        return self.filter(Q(is_community=False) | Q(supported=True))

    def community(self):
        return self.filter(is_community=True, supported=False)

    def upcoming(self):
        today = timezone.localdate()
        return self.filter(Q(end_date__gte=today) | Q(end_date__isnull=True, start_date__gte=today)).order_by(
            "start_date", "start_time"
        )

    def past(self):
        today = timezone.localdate()
        return self.filter(Q(end_date__lt=today) | Q(end_date__isnull=True, start_date__lt=today)).order_by(
            "-start_date", "-start_time"
        )


class Event(models.Model):
    title = models.CharField("titre", max_length=160)
    slug = models.SlugField(unique=True, max_length=160, blank=True)
    types = models.CharField("types", max_length=200, blank=True, default="")
    other_type = models.CharField(_("autre type"), max_length=60, blank=True, help_text=_("Si « Autre » est coché"))
    start_date = models.DateField("date")
    start_time = models.TimeField("heure de début", null=True, blank=True, help_text="Vide = toute la journée")
    end_date = models.DateField("date de fin", null=True, blank=True, help_text="Seulement si l'événement dure plusieurs jours")
    end_time = models.TimeField("heure de fin", null=True, blank=True)
    venue = models.CharField("lieu", max_length=160, blank=True, help_text="Ex. Observatoire de la Côte d'Azur")
    address = models.CharField("adresse", max_length=255, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    price = models.CharField("prix", max_length=120, blank=True, help_text="Ex. Gratuit, 5 €, 15 € tout compris")
    registration_url = models.URLField("lien d'inscription", blank=True, help_text="HelloAsso, formulaire…")
    poster = models.ImageField("affiche", upload_to="evenements/", blank=True, validators=[validate_image])
    summary = models.CharField("accroche", max_length=240, blank=True, help_text="Une phrase. Vide = début de la description")
    body = models.TextField("description", blank=True)
    # Version anglaise, facultative : vide = on affiche le français.
    title_en = models.CharField("titre (anglais)", max_length=160, blank=True)
    price_en = models.CharField("prix (anglais)", max_length=120, blank=True)
    summary_en = models.CharField("accroche (anglais)", max_length=240, blank=True)
    body_en = models.TextField("description (anglais)", blank=True)
    is_published = models.BooleanField("publié", default=True)
    # Événements proposés par les membres (afterworks, randonnées…), distincts des événements officiels du bureau.
    is_community = models.BooleanField("proposé par un membre", default=False)
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="organized_events", verbose_name="organisateur·rice")
    capacity = models.PositiveSmallIntegerField(_("nombre de places"), null=True, blank=True,
                                                help_text=_("Vide = sans limite"))
    # En attente : préparé mais pas encore visible, le temps du dossier auprès de l'université.
    on_hold = models.BooleanField("en attente", default=False,
                                  help_text="Caché du site tant que le dossier n'est pas validé par l'université")
    # Sortie de membre dont la demande de soutien a été acceptée : présentée comme un événement de l'asso.
    supported = models.BooleanField("soutenu par l'asso", default=False)
    helloasso_count = models.PositiveIntegerField("inscrit·es HelloAsso", null=True, blank=True)
    helloasso_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    title_tr = Translated("title")
    price_tr = Translated("price")
    summary_tr = Translated("summary")
    body_tr = Translated("body")

    class Meta:
        ordering = ["-start_date", "-start_time"]
        verbose_name = "événement"

    def __str__(self):
        return f"{self.title} ({self.start_date:%d/%m/%Y})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.unique_slug()
        if self.end_date == self.start_date:
            self.end_date = None
        normalize_field(self, "poster")
        super().save(*args, **kwargs)

    def unique_slug(self):
        base = slugify(self.title)[:140] or "evenement"
        slug, n = base, 2
        while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug

    def get_absolute_url(self):
        return reverse("events:detail", args=[self.slug])

    # Dates -----------------------------------------------------------------

    @property
    def all_day(self):
        return self.start_time is None

    @property
    def last_date(self):
        return self.end_date or self.start_date

    @property
    def multi_day(self):
        return self.end_date is not None and self.end_date > self.start_date

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.start_date, self.start_time or time(0)))

    @property
    def ends_at(self):
        if self.all_day:
            return timezone.make_aware(datetime.combine(self.last_date + timedelta(days=1), time(0)))
        if self.end_time:
            return timezone.make_aware(datetime.combine(self.last_date, self.end_time))
        return self.starts_at + timedelta(hours=2)

    @property
    def is_upcoming(self):
        return self.last_date >= timezone.localdate()

    @property
    def days_until(self):
        return (self.start_date - timezone.localdate()).days

    # Types ----------------------------------------------------------------

    @property
    def type_codes(self):
        return [c for c in self.types.strip(",").split(",") if c]

    def set_types(self, codes):
        known = [c for c, _l, _s in TYPES if c in codes]
        self.types = f",{','.join(known)}," if known else ""

    @property
    def type_labels(self):
        """[(code, libellé)] dans l'ordre de TYPES ; « Autre » prend le libellé libre s'il est renseigné."""
        out = []
        for code in self.type_codes:
            label = self.other_type if code == "autre" and self.other_type else TYPE_LABELS.get(code, code)
            out.append((code, label))
        return out

    @property
    def type_tags(self):
        """[(code, émoji, libellé)] pour les étiquettes du site."""
        return [(code, TYPE_EMOJIS.get(code, ""), label) for code, label in self.type_labels]

    @property
    def main_type(self):
        codes = self.type_codes
        return codes[0] if codes else "autre"

    # Affichage --------------------------------------------------------------

    @property
    def attendee_count(self):
        return self.attendances.count()

    @property
    def is_association(self):
        """Événement de l'asso : organisé par le bureau, ou sortie de membre soutenue par l'asso."""
        return not self.is_community or self.supported

    @property
    def is_full(self):
        return self.capacity is not None and self.attendee_count >= self.capacity

    @property
    def body_html(self):
        return markdown.render(self.body_tr)

    @property
    def teaser(self):
        return self.summary_tr or markdown.plain(self.body_tr, 180)

    @property
    def maps_url(self):
        """Lien Google Maps (adresses d'URL publiques, sans clé) : le nom du lieu et l'adresse donnent une fiche
        plus parlante que des coordonnées, qui servent de repli."""
        query = ", ".join(p for p in (self.venue, self.address) if p)
        if not query and self.latitude is not None and self.longitude is not None:
            query = f"{self.latitude},{self.longitude}"
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}" if query else ""
