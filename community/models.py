"""Espace membres : profils, amitiés, participations aux événements, notifications et signalements."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core import markdown
from core.images import normalize_field, validate_image


AVATAR_SIDE = 600  # affichée au plus à 136 px, 600 suffit même sur écran haute densité


class Profile(models.Model):
    class School(models.TextChoices):
        SHAL = "shal", "ED SHAL"
        STIC = "stic", "ED STIC"
        SFA = "sfa", "ED SFA"
        DESPEG = "despeg", "ED DESPEG"
        SVS = "svs", "ED SVS"
        SMH = "smh", "ED SMH"
        OTHER = "autre", _("Autre / hors UniCA")

    class Stage(models.TextChoices):
        Y1 = "1", _("1re année de thèse")
        Y2 = "2", _("2e année de thèse")
        Y3 = "3", _("3e année de thèse")
        Y4 = "4", _("4e année ou plus")
        DOCTOR = "docteur", _("Docteur·e")
        POSTDOC = "postdoc", _("Post-doc")
        OTHER = "autre", _("Autre")

    # Couleurs proposées pour personnaliser son profil (classes CSS accent-*, pas de style en ligne : CSP).
    class Accent(models.TextChoices):
        AZUR = "azur", _("Azur")
        MIMOSA = "mimosa", _("Mimosa")
        CORAIL = "corail", _("Corail")
        OLIVE = "olive", _("Olivier")
        LAVANDE = "lavande", _("Lavande")
        NUIT = "nuit", _("Nuit")

    class Visibility(models.TextChoices):
        MEMBERS = "membres", _("Membres connectés uniquement")
        PUBLIC = "public", _("Tout le monde")

    class ContactVisibility(models.TextChoices):
        FRIENDS = "amis", _("Mes amis uniquement")
        MEMBERS = "membres", _("Tous les membres connectés")
        NOBODY = "personne", _("Personne")

    class PastVisibility(models.TextChoices):
        PROFILE = "profil", _("Tous ceux qui voient mon profil")
        FRIENDS = "amis", _("Mes amis uniquement")
        ME = "moi", _("Moi seul·e")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    handle = models.SlugField(_("adresse du profil"), unique=True, max_length=60)
    display_name = models.CharField(_("nom affiché"), max_length=80)
    pronouns = models.CharField(_("pronoms"), max_length=30, blank=True)
    avatar = models.ImageField(_("photo"), upload_to="membres/", blank=True, validators=[validate_image])
    headline = models.CharField(_("en ce moment"), max_length=120, blank=True,
                                help_text=_("Une ligne : « En pleine rédaction », « Cherche des partenaires d'escalade »…"))
    discipline = models.CharField(_("discipline"), max_length=100, blank=True)
    doctoral_school = models.CharField(_("école doctorale"), max_length=10, choices=School.choices, blank=True)
    lab = models.CharField(_("laboratoire"), max_length=100, blank=True)
    stage = models.CharField(_("où j'en suis"), max_length=10, choices=Stage.choices, blank=True)
    thesis_title = models.CharField(_("sujet de thèse"), max_length=300, blank=True)
    bio = models.TextField(_("présentation"), blank=True)
    interests = models.CharField(_("centres d'intérêt"), max_length=300, blank=True,
                                 help_text=_("Séparés par des virgules : randonnée, jeux de société, plongée…"))
    linkedin = models.URLField("LinkedIn", blank=True)
    website = models.URLField(_("site web"), blank=True)
    orcid = models.CharField("ORCID", max_length=19, blank=True, help_text="0000-0000-0000-0000")
    accent = models.CharField(_("couleur du profil"), max_length=10, choices=Accent.choices, default=Accent.AZUR)
    visibility = models.CharField(_("qui peut voir mon profil"), max_length=10, choices=Visibility.choices,
                                  default=Visibility.MEMBERS)
    show_events = models.BooleanField(_("afficher les événements à venir auxquels je participe"), default=True)
    past_events = models.CharField(_("qui voit les événements auxquels j'ai participé"), max_length=10,
                                   choices=PastVisibility.choices, default=PastVisibility.PROFILE)
    link_helloasso = models.BooleanField(
        _("relier mes inscriptions HelloAsso à mon compte"), default=True,
        help_text=_("Les événements où tu t'es inscrit·e sur HelloAsso, avec une de tes adresses confirmées, "
                    "apparaissent comme « J'y vais » et dans « Y est allé·e »."))
    # Faux tant que le lien de confirmation n'a pas été ouvert (le compte reste alors inactif).
    email_confirmed = models.BooleanField("adresse confirmée", default=True)
    # Coordonnées : jamais publiques, visibles selon contact_visibility.
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=30, blank=True, help_text=_("Numéro, si différent du téléphone"))
    discord = models.CharField("Discord", max_length=60, blank=True, help_text=_("Identifiant"))
    instagram = models.CharField("Instagram", max_length=60, blank=True, help_text=_("Identifiant, sans @"))
    facebook = models.CharField("Facebook", max_length=120, blank=True, help_text=_("Identifiant ou lien du profil"))
    x = models.CharField("X", max_length=60, blank=True, help_text=_("Identifiant, sans @"))
    other_contact = models.CharField(_("autre"), max_length=200, blank=True,
                                     help_text=_("Mastodon, Bluesky, Signal… avec le nom du réseau"))
    contact_visibility = models.CharField(_("qui peut voir mes coordonnées"), max_length=10,
                                          choices=ContactVisibility.choices, default=ContactVisibility.FRIENDS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name"]
        verbose_name = "profil"

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.handle:
            base = slugify(self.display_name)[:50] or "membre"
            handle, n = base, 2
            while Profile.objects.filter(handle=handle).exclude(pk=self.pk).exists():
                handle, n = f"{base}-{n}", n + 1
            self.handle = handle
        normalize_field(self, "avatar", max_side=AVATAR_SIDE)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("community:profile", args=[self.handle])

    @property
    def initials(self):
        return "".join(p[0] for p in self.display_name.replace("-", " ").split()[:2]).upper() or "?"

    @property
    def interest_list(self):
        return [i.strip() for i in self.interests.split(",") if i.strip()]

    @property
    def bio_html(self):
        return markdown.render(self.bio)

    def visible_to(self, user):
        return self.visibility == self.Visibility.PUBLIC or user.is_authenticated

    @property
    def has_contacts(self):
        return any((self.phone, self.whatsapp, self.discord, self.instagram, self.facebook, self.x, self.other_contact))

    def contacts_visible_to(self, user, rel):
        if rel == "self":
            return True
        if not user.is_authenticated or self.contact_visibility == self.ContactVisibility.NOBODY:
            return False
        return self.contact_visibility == self.ContactVisibility.MEMBERS or rel == "friends"

    def past_events_visible_to(self, rel):
        if rel == "self" or self.past_events == self.PastVisibility.PROFILE:
            return True
        return self.past_events == self.PastVisibility.FRIENDS and rel == "friends"

    @property
    def whatsapp_link(self):
        digits = "".join(c for c in (self.whatsapp or self.phone) if c.isdigit())
        if digits.startswith("0") and len(digits) == 10:  # numéro français sans indicatif
            digits = "33" + digits[1:]
        return f"https://wa.me/{digits}" if digits else ""


class FriendshipQuerySet(models.QuerySet):
    def between(self, a, b):
        return self.filter(Q(from_user=a, to_user=b) | Q(from_user=b, to_user=a))


class Friendship(models.Model):
    """Demande d'amitié de from_user vers to_user ; acceptée, elle vaut dans les deux sens."""

    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="friend_requests_sent")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="friend_requests_received")
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FriendshipQuerySet.as_manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["from_user", "to_user"], name="unique_friend_request")]
        verbose_name = "amitié"

    def __str__(self):
        return f"{self.from_user} → {self.to_user} ({'acceptée' if self.accepted else 'en attente'})"


def friends_of(user):
    """Utilisateurs liés à `user` par une amitié acceptée."""
    from django.contrib.auth import get_user_model

    links = Friendship.objects.filter(accepted=True).filter(Q(from_user=user) | Q(to_user=user))
    ids = {f.to_user_id if f.from_user_id == user.pk else f.from_user_id for f in links}
    return get_user_model().objects.filter(pk__in=ids).select_related("profile")


def relation(user, other):
    """« self », « friends », « sent » (demande envoyée), « received » (à accepter) ou « none »."""
    if not user.is_authenticated:
        return "anonymous"
    if user.pk == other.pk:
        return "self"
    link = Friendship.objects.between(user, other).first()
    if not link:
        return "none"
    if link.accepted:
        return "friends"
    return "sent" if link.from_user_id == user.pk else "received"


class Attendance(models.Model):
    """« J'y vais » d'un membre pour un événement (officiel ou communautaire)."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="attendances")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendances")
    created_at = models.DateTimeField(auto_now_add=True)
    # Créée d'après un billet HelloAsso (retirée si le billet est remboursé), et nombre de billets en plus pris
    # avec la même adresse : la personne vient accompagnée (« +1 »).
    via_helloasso = models.BooleanField(default=False)
    guests = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="unique_attendance")]
        ordering = ["created_at"]
        verbose_name = "participation"


class Notification(models.Model):
    class Verb(models.TextChoices):
        FRIEND_REQUEST = "friend_request", "demande d'ami"
        FRIEND_ACCEPTED = "friend_accepted", "amitié acceptée"
        INVITE = "invite", "invitation"
        ATTENDING = "attending", "participation à mon événement"
        PHOTO_TAG = "photo_tag", "identification sur une photo"
        SUPPORT = "support", "demande de soutien reçue (bureau)"
        SUPPORT_ANSWER = "support_answer", "réponse à une demande de soutien"
        ALERT = "alert", "nouvel événement (alerte)"
        HELLOASSO = "helloasso", "inscription HelloAsso reliée au compte"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    verb = models.CharField(max_length=20, choices=Verb.choices)
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    photo = models.ForeignKey("Photo", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class Report(models.Model):
    """Signalement d'un événement communautaire ou d'un profil, traité par le bureau dans /gestion/."""

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    photo = models.ForeignKey("Photo", null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    profile = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    comment = models.ForeignKey("Comment", null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reason = models.TextField("motif")
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField("traité", default=False)

    class Meta:
        ordering = ["handled", "-created_at"]
        verbose_name = "signalement"

    @property
    def target(self):
        return self.comment or self.event or self.photo or self.profile


class Photo(models.Model):
    """Photo, vidéo ou lien vers un média hébergé ailleurs (YouTube, Google Photos…), partagé par un membre, lié ou
    non à un événement, avec les membres présents identifiés."""

    class Kind(models.TextChoices):
        PHOTO = "photo", _("Photo")
        VIDEO = "video", _("Vidéo")
        LINK = "lien", _("Lien")

    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="photos")
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.PHOTO)
    image = models.ImageField(_("photo"), upload_to="photos/%Y/", blank=True, validators=[validate_image])
    video = models.FileField(_("vidéo"), upload_to="photos/%Y/", blank=True)
    url = models.URLField(_("lien"), max_length=500, blank=True)
    caption = models.CharField(_("légende"), max_length=200, blank=True)
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.SET_NULL, related_name="photos",
                              verbose_name=_("événement"))
    tagged = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="tagged_photos",
                                    verbose_name=_("personnes identifiées"))
    consent = models.BooleanField(_("autorisation des personnes photographiées"), default=False)
    is_hidden = models.BooleanField("masquée", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "photo"

    def __str__(self):
        return self.caption or self.url or (self.image or self.video).name.rsplit("/", 1)[-1]

    def save(self, *args, **kwargs):
        normalize_field(self, "image")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        for field in (self.image, self.video):
            if field:
                field.delete(save=False)
        return super().delete(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("community:photo", args=[self.pk])

    @property
    def embed(self):
        from core.embeds import parse

        return parse(self.url) if self.url else None


class Comment(models.Model):
    """Commentaire d'un membre sur un événement."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField(_("commentaire"), max_length=2000)
    is_hidden = models.BooleanField("masqué", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "commentaire"

    def __str__(self):
        return self.body if len(self.body) <= 60 else self.body[:59] + "…"

    def get_absolute_url(self):
        return f"{self.event.get_absolute_url()}#commentaire-{self.pk}"


class AlertPreference(models.Model):
    """Filtre et alerte d'un membre (un seul par compte) : types d'événements et origine, comme les filtres de l'agenda."""

    class Origin(models.TextChoices):
        ALL = "", _("Tous")
        ASSO = "asso", _("Par l'AJC06")
        COMMUNITY = "communaute", _("Par les membres")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_preference")
    types = models.CharField(_("types"), max_length=300, blank=True, default="", help_text="« ,code1,code2, » ; vide = tous")
    origin = models.CharField(_("proposés"), max_length=12, choices=Origin.choices, blank=True, default="")
    active = models.BooleanField(_("m'alerter des nouveaux événements"), default=False)
    by_email = models.BooleanField(_("aussi par courriel"), default=True)
    # Seuls les événements publiés ou modifiés après la mise en route sont signalés (pas d'avalanche).
    active_since = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "alerte"

    @property
    def type_codes(self):
        return [c for c in self.types.strip(",").split(",") if c]

    def matching(self, events):
        if self.type_codes:
            q = Q()
            for code in self.type_codes:
                q |= Q(types__contains=f",{code},")
            events = events.filter(q)
        if self.origin == self.Origin.ASSO:
            events = events.official()
        elif self.origin == self.Origin.COMMUNITY:
            events = events.community()
        return events


class AlertSent(models.Model):
    """Événement déjà signalé à un membre : jamais deux fois."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "event"], name="unique_alert_sent")]


class EmailAddress(models.Model):
    """Adresses d'un membre : la principale (celle du compte) et d'autres, pour reconnaître ses billets HelloAsso.

    Seules les adresses confirmées (lien reçu par courriel) servent ; une adresse confirmée n'appartient qu'à un compte.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_addresses")
    email = models.EmailField(_("adresse"))
    confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "adresse e-mail"
        constraints = [
            models.UniqueConstraint(fields=["user", "email"], name="unique_address_per_user"),
            models.UniqueConstraint(fields=["email"], condition=Q(confirmed=True), name="unique_confirmed_address"),
        ]

    def __str__(self):
        return self.email

    @property
    def is_primary(self):
        return self.email == (self.user.email or "").lower()
