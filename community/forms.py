import re
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from events.models import Event, type_choices
from projets.models import SupportRequest

from .models import AlertPreference, Photo, Profile

User = get_user_model()


class SignupForm(forms.Form):
    display_name = forms.CharField(label=_("Prénom et nom"), max_length=80,
                                   widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label=_("Courriel"), widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(label=_("Mot de passe"), strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text=_("Au moins 8 caractères, pas uniquement des chiffres."))
    # Piège à robots : champ masqué que les humains laissent vide.
    website = forms.CharField(required=False, label=_("Laisser vide"),
                              widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    consent = forms.BooleanField(label=_("J'accepte que mes informations de profil soient visibles par les membres, "
                                         "selon les réglages que je choisis."))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Un compte existe déjà avec cette adresse."))
        return email

    def clean(self):
        data = super().clean()
        if data.get("password"):
            probe = User(username=data.get("email", ""), email=data.get("email", ""), first_name=data.get("display_name", ""))
            try:
                password_validation.validate_password(data["password"], probe)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return data

    def is_spam(self):
        return bool(self.cleaned_data.get("website"))

    def save(self, confirm=False):
        data = self.cleaned_data
        user = User.objects.create_user(username=data["email"], email=data["email"], password=data["password"],
                                        first_name=data["display_name"].split(" ")[0], is_active=not confirm)
        profile, _ = Profile.objects.get_or_create(user=user)  # normalement déjà créé par le signal post_save
        profile.display_name = data["display_name"].strip()
        profile.handle = ""  # recalculé à partir du nom complet
        profile.email_confirmed = not confirm
        profile.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.CharField(label=_("Courriel"), widget=forms.TextInput(attrs={"autocomplete": "email", "autofocus": True}))

    error_messages = {
        "invalid_login": _("Courriel ou mot de passe incorrect."),
        "inactive": _("Ce compte est désactivé."),
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            # Bon mot de passe mais compte pas encore validé : le dire, plutôt que « mot de passe incorrect ».
            email, password = self.cleaned_data.get("username", ""), self.cleaned_data.get("password", "")
            user = User.objects.filter(email__iexact=email.strip(), is_active=False,
                                       profile__email_confirmed=False).first()
            if user and password and user.check_password(password):
                raise forms.ValidationError(
                    _("Ton compte n'est pas encore validé : ouvre le lien reçu par courriel, ou attends la validation "
                      "par le bureau."), code="pending")
            raise


class PartialSaveMixin:
    """Formulaire qui s'enregistre toujours : un champ refusé (vide alors qu'obligatoire, mal formé…) est écarté et garde
    sa valeur précédente, les autres sont enregistrés. Les champs écartés et leurs erreurs sont dans `skipped`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skipped = {}
        self._before = {name: getattr(self.instance, name) for name in self.fields if hasattr(self.instance, name)}

    def _drop_invalid(self):
        for name in [n for n in self._errors if n in self.fields]:
            self.skipped[name] = self._errors.pop(name)
            self.cleaned_data.pop(name, None)
            if name in self._before:
                setattr(self.instance, name, self._before[name])

    def _clean_fields(self):
        super()._clean_fields()
        self._drop_invalid()  # avant construct_instance : l'instance garde l'ancienne valeur de ces champs

    def _post_clean(self):
        super()._post_clean()
        self._drop_invalid()  # erreurs de validation du modèle (longueur…), plus rares

    def skipped_summary(self):
        return "; ".join(f"{self.fields[name].label} ({' '.join(errors)})" for name, errors in self.skipped.items())


class ProfileForm(PartialSaveMixin, forms.ModelForm):
    # Plus long que la base (19) : on accepte le lien complet https://orcid.org/…, ramené au seul identifiant.
    orcid = forms.CharField(label="ORCID", required=False, max_length=80, help_text=_("Identifiant ou lien ORCID"))

    class Meta:
        model = Profile
        fields = [
            "display_name", "pronouns", "avatar", "headline", "discipline", "doctoral_school", "lab", "stage",
            "thesis_title", "bio", "interests", "linkedin", "website", "orcid", "accent", "visibility", "show_events", "past_events",
            "phone", "whatsapp", "discord", "instagram", "facebook", "x", "other_contact", "contact_visibility",
        ]
        widgets = {
            "avatar": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "bio": forms.Textarea(attrs={"rows": 6}),
            "accent": forms.RadioSelect,
            "visibility": forms.RadioSelect,
            "contact_visibility": forms.RadioSelect,
            "past_events": forms.RadioSelect,
            "thesis_title": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
            "whatsapp": forms.TextInput(attrs={"type": "tel"}),
        }
        help_texts = {"bio": _("Quelques lignes sur toi, ta recherche, ce que tu aimes. Mise en forme Markdown possible.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("linkedin", "website"):
            self.fields[name].assume_scheme = "https"  # « linkedin.com/in/… » saisi sans protocole

    def clean_instagram(self):
        return handle_from(self.cleaned_data["instagram"])

    def clean_x(self):
        return handle_from(self.cleaned_data["x"])

    def clean_orcid(self):
        # On accepte aussi le lien complet (https://orcid.org/…) et les espaces à la place des tirets.
        value = self.cleaned_data["orcid"].strip().rstrip("/").rsplit("/", 1)[-1].upper()
        digits = re.sub(r"[\s-]", "", value)
        if not digits:
            return ""
        if not re.fullmatch(r"\d{15}[\dX]", digits):
            raise forms.ValidationError(_("Format attendu : 0000-0000-0000-0000."))
        return "-".join(digits[i:i + 4] for i in range(0, 16, 4))


def handle_from(value):
    """« @nom », « nom » ou « https://instagram.com/nom/ » donnent « nom »."""
    value = value.strip()
    if "/" in value:
        value = value.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return value.lstrip("@")


class EmailForm(forms.Form):
    email = forms.EmailField(label=_("Courriel"))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError(_("Un compte existe déjà avec cette adresse."))
        return email


class AlertForm(forms.ModelForm):
    """Filtre unique du membre : types (plusieurs) et origine, comme sur l'agenda ; alerte et courriel."""

    type_list = forms.MultipleChoiceField(label=_("Types d'événements"), required=False, widget=forms.CheckboxSelectMultiple,
                                          help_text=_("Aucun coché = tous les types."))

    class Meta:
        model = AlertPreference
        fields = ["origin", "active", "by_email"]
        widgets = {"origin": forms.RadioSelect}
        labels = {"origin": _("Proposés par")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type_list"].choices = type_choices(staff=True)
        self.fields["type_list"].initial = self.instance.type_codes
        self.fields["origin"].choices = AlertPreference.Origin.choices

    def save(self, commit=True):
        pref = super().save(commit=False)
        codes = self.cleaned_data.get("type_list") or []
        pref.types = f",{','.join(codes)}," if codes else ""
        if pref.active and not pref.active_since:
            pref.active_since = timezone.now()
        if not pref.active:
            pref.active_since = None
        if commit:
            pref.save()
        return pref


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label=_("Ton mot de passe, pour confirmer"), strip=False, widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError(_("Mot de passe incorrect."))
        return self.cleaned_data["password"]


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kwargs):
        super().__init__(format="%H:%M", **kwargs)


class TypesField(forms.MultipleChoiceField):
    widget = forms.CheckboxSelectMultiple


class EventTypesMixin:
    """Types multiples (« ,code1,code2, ») : les rendez-vous phares du bureau ne sont proposés qu'au bureau."""

    staff = False

    def init_types(self):
        self.fields["type_list"] = TypesField(label=_("Type"), choices=type_choices(staff=self.staff),
                                              help_text=_("Plusieurs choix possibles"))
        self.fields["type_list"].initial = self.instance.type_codes if self.instance.pk else []
        self.order_fields(["title", "type_list", "other_type"])

    def clean_types(self, data):
        codes = data.get("type_list") or []
        if not codes:
            self.add_error("type_list", _("Choisis au moins un type."))
        if "autre" in codes and not data.get("other_type"):
            self.add_error("other_type", _("Précise le type."))
        return codes


class CommunityEventForm(EventTypesMixin, forms.ModelForm):
    """Formulaire court pour proposer une sortie entre doctorant·es."""

    request_support = forms.BooleanField(
        label=_("Je demande le soutien de l'AJC06 (financement ou réservations)"), required=False)

    class Meta:
        model = Event
        fields = ["title", "other_type", "start_date", "start_time", "end_date", "end_time", "venue", "address",
                  "price", "capacity", "registration_url", "poster", "summary", "body", "on_nice_event"]
        labels = {
            "title": _("Titre"),
            "start_date": _("Date"),
            "start_time": _("Heure de début"),
            "end_date": _("Date de fin"),
            "end_time": _("Heure de fin"),
            "venue": _("Lieu"),
            "address": _("Adresse"),
            "price": _("Prix"),
            "registration_url": _("Lien utile"),
            "poster": _("Image"),
            "summary": _("Accroche"),
            "body": _("Description"),
        }
        help_texts = {
            "start_time": _("Vide = toute la journée"),
            "end_date": _("Seulement si ça dure plusieurs jours"),
            "venue": _("Ex. Parking du col de Braus, bar Le Movida…"),
            "price": _("Ex. Gratuit, chacun paie sa conso…"),
            "registration_url": _("Facultatif : billetterie, groupe WhatsApp, itinéraire…"),
            "summary": _("Une phrase qui donne envie."),
            "body": _("Programme, niveau, matériel à prévoir, point de rendez-vous… Mise en forme Markdown possible."),
            "on_nice_event": _("Ta sortie apparaît aussi sur nice-event.fr, l'agenda participatif de la région niçoise, avec un "
                               "lien vers cette page : plus de monde ! Décoche pour la garder entre doctorant·es."),
        }
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "start_time": TimeInput(),
            "end_time": TimeInput(),
            "poster": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "body": forms.Textarea(attrs={"rows": 8}),
        }

    SUPPORT_DELAY_DAYS = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_types()
        if self.instance.pk:
            # Une demande déjà faite ne se retire pas d'ici ; une sortie soutenue reste soutenue.
            self.fields.pop("request_support")

    def clean_start_date(self):
        start = self.cleaned_data["start_date"]
        if start < timezone.localdate() and not self.instance.pk:
            raise forms.ValidationError(_("La date est déjà passée."))
        return start

    def clean(self):
        data = super().clean()
        self.cleaned_codes = self.clean_types(data)
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("La date de fin est avant la date de début."))
        if data.get("end_time") and not data.get("start_time"):
            self.add_error("start_time", _("Indique aussi l'heure de début (ou laisse les deux vides pour toute la journée)."))
        if data.get("request_support") and start and start < timezone.localdate() + timedelta(days=self.SUPPORT_DELAY_DAYS):
            self.add_error("start_date", _("Une demande de soutien doit être faite au moins un mois avant l'événement."))
        return data

    def save(self, commit=True):
        event = super().save(commit=False)
        event.set_types(self.cleaned_codes)
        if commit:
            event.save()
        return event


class SupportRequestForm(forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ["amount", "access", "price_per_person", "fixed_costs", "budget_details", "booking"]
        widgets = {
            "access": forms.Textarea(attrs={"rows": 3}),
            "budget_details": forms.Textarea(attrs={"rows": 5, "placeholder": _("Location de paddles : 10 × 25 € = 250 €\nGoûter : 40 €\nParticipation des doctorant·es : 5 € × 10 = 50 € (recette)")}),
            "booking": forms.RadioSelect,
            "amount": forms.NumberInput(attrs={"min": "0", "step": "1"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError(_("Indique la somme demandée."))
        return amount


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/*,video/mp4,video/webm,video/quicktime"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, (list, tuple)):
            return [super(MultipleFileField, self).clean(d, initial) for d in data if d]
        return [super().clean(data, initial)] if data else []


class PhotoForm(forms.Form):
    """Plusieurs photos et vidéos d'un coup, et/ou des liens vers des médias hébergés ailleurs (un par ligne)."""

    MAX_ITEMS = 20

    files = MultipleFileField(label=_("Photos et vidéos"), required=False,
                              help_text=_("Plusieurs fichiers à la fois. Photos jusqu'à 12 Mo (converties en WebP), "
                                          "vidéos MP4, MOV ou WebM jusqu'à 50 Mo."))
    links = forms.CharField(label=_("Ou des liens"), required=False, widget=forms.Textarea(attrs={"rows": 3}),
                            help_text=_("Un par ligne : YouTube, Vimeo, Dailymotion (lus sur place), Pinterest, "
                                        "Google Photos, Drive, Flickr… Pratique pour les vidéos lourdes ou les albums."))
    caption = forms.CharField(label=_("Légende"), max_length=200, required=False)
    event = forms.ModelChoiceField(label=_("Événement"), queryset=Event.objects.none(), required=False)
    consent = forms.BooleanField(label=_("Les personnes reconnaissables sur ces photos et vidéos m'ont donné leur accord "
                                         "pour qu'elles soient publiées sur le site."))
    tagged_handles = forms.CharField(required=False, label=_("Autres membres présents"),
                                     help_text=_("Leurs adresses de profil, séparées par des virgules (ex. lea-moreau, karim-benali). Ils seront prévenus."))

    def __init__(self, user, *args, **kwargs):
        from .models import friends_of

        super().__init__(*args, **kwargs)
        self.fields["friends"] = forms.ModelMultipleChoiceField(
            label=_("Tes amis présents"), required=False, widget=forms.CheckboxSelectMultiple,
            queryset=friends_of(user).order_by("profile__display_name"))
        self.fields["friends"].label_from_instance = lambda u: u.profile.display_name
        self.fields["event"].queryset = Event.objects.published().order_by("-start_date")
        self.fields["event"].empty_label = _("Aucun (photo libre)")

    def clean_files(self):
        from django.core.exceptions import ValidationError

        from core.images import is_video_name, validate_image, validate_video

        items, errors = [], []
        for f in self.cleaned_data["files"]:
            try:
                if is_video_name(f.name):
                    validate_video(f)
                    items.append(("video", f))
                else:
                    validate_image(f)
                    items.append(("photo", f))
            except ValidationError as exc:
                hint = _("ou partage-la par un lien (Google Photos, Flickr…)") if not is_video_name(f.name) else ""
                errors.append(f"{f.name} : {' '.join(exc.messages)} {hint}".strip())
        if errors:
            raise forms.ValidationError(errors)
        return items

    def clean_links(self):
        from core.embeds import parse

        links, bad = [], []
        for line in self.cleaned_data["links"].split():
            if not line.startswith(("http://", "https://")):
                line = "https://" + line
            line = line.replace("http://", "https://", 1)
            (links if parse(line) and len(line) <= 500 else bad).append(line)
        if bad:
            raise forms.ValidationError(_("Lien non valable : %(list)s") % {"list": ", ".join(bad)})
        return links

    def clean_tagged_handles(self):
        handles = [h.strip().lower() for h in self.cleaned_data["tagged_handles"].replace(";", ",").split(",") if h.strip()]
        profiles = list(Profile.objects.filter(handle__in=handles, user__is_active=True).select_related("user"))
        unknown = sorted(set(handles) - {p.handle for p in profiles})
        if unknown:
            raise forms.ValidationError(_("Profil inconnu : %(list)s") % {"list": ", ".join(unknown)})
        return [p.user for p in profiles]

    def clean(self):
        data = super().clean()
        count = len(data.get("files") or []) + len(data.get("links") or [])
        if not count and not self.errors:
            raise forms.ValidationError(_("Ajoute au moins une photo, une vidéo ou un lien."))
        if count > self.MAX_ITEMS:
            raise forms.ValidationError(_("%(n)s éléments au plus à la fois.") % {"n": self.MAX_ITEMS})
        return data

    def tagged_users(self):
        users = {u.pk: u for u in self.cleaned_data.get("friends") or []}
        users.update({u.pk: u for u in self.cleaned_data.get("tagged_handles") or []})
        return list(users.values())


class CommentForm(forms.Form):
    body = forms.CharField(label=_("Ton commentaire"), max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))


class ReportForm(forms.Form):
    reason = forms.CharField(label=_("Qu'est-ce qui ne va pas ?"), max_length=1000, widget=forms.Textarea(attrs={"rows": 4}))
