from datetime import timedelta

from django import forms
from django.core.validators import validate_email
from django.utils import timezone

from .models import LANGUAGES, LIMIT, Network
from .texts import default_subject, default_text


class DiffusionForm(forms.Form):
    """Langue, un bloc par canal (case à cocher + texte), puis « maintenant » ou une date de publication."""

    language = forms.ChoiceField(label="Langue", choices=LANGUAGES, widget=forms.RadioSelect,
                                 help_text="Change les textes proposés (et le visuel, en anglais pour une diffusion tout en "
                                           "anglais). Les textes déjà modifiés sont remplacés.")
    when = forms.ChoiceField(label="Quand ?", choices=[("now", "Tout de suite"), ("later", "Programmer")],
                             widget=forms.RadioSelect, initial="now")
    scheduled_at = forms.DateTimeField(label="Le", required=False,
                                       widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    subject = forms.CharField(label="Objet du courriel", max_length=200, required=False)
    recipients = forms.CharField(label="Destinataires", required=False, widget=forms.Textarea(attrs={"rows": 3}),
                                 help_text="Une adresse par ligne (ou une liste de diffusion). Envoi en copie cachée.")

    def __init__(self, *args, event, config, **kwargs):
        super().__init__(*args, **kwargs)
        self.event, self.config = event, config
        # Bilingue par défaut si l'événement a une version anglaise
        language = "both" if event.title_en or event.summary_en or event.body_en else "fr"
        self.fields["language"].initial = language
        self.networks = []
        for value, label in Network.choices:
            ready = config.network_ready(value)
            self.fields[f"on_{value}"] = forms.BooleanField(label=label, required=False, initial=ready, disabled=not ready)
            self.fields[f"text_{value}"] = forms.CharField(
                label=f"Texte {label}", required=False,
                initial=default_text(event, value, config.social_signature, language),
                widget=forms.Textarea(attrs={"rows": 12 if value == "email" else 9, "data-limit": LIMIT[value]}))
            self.networks.append((value, label, ready))
        self.fields["subject"].initial = default_subject(event, language)
        self.fields["recipients"].initial = config.diffusion_emails

    def prefills(self):
        """Textes proposés pour chaque langue, que la page échange quand on change de langue."""
        out = {}
        for lang, _label in LANGUAGES:
            texts = {f"text_{n}": default_text(self.event, n, self.config.social_signature, lang) for n, _l in Network.choices}
            out[lang] = {**texts, "subject": default_subject(self.event, lang)}
        return out

    def blocks(self):
        return [(value, label, ready, self[f"on_{value}"], self[f"text_{value}"], LIMIT[value])
                for value, label, ready in self.networks]

    def clean(self):
        data = super().clean()
        chosen = [v for v, _l, ready in self.networks if ready and data.get(f"on_{v}")]
        if not chosen:
            raise forms.ValidationError("Choisis au moins un canal (configuré et activé dans les réglages).")
        for value in chosen:
            text = (data.get(f"text_{value}") or "").strip()
            if not text:
                self.add_error(f"text_{value}", "Texte vide.")
            elif len(text) > LIMIT[value]:
                self.add_error(f"text_{value}", f"Trop long : {len(text)} caractères pour {LIMIT[value]}.")
        if "email" in chosen:
            addresses = [a.strip() for a in (data.get("recipients") or "").replace(",", "\n").replace(";", "\n").splitlines()
                         if a.strip()]
            bad = []
            for address in addresses:
                try:
                    validate_email(address)
                except forms.ValidationError:
                    bad.append(address)
            if not addresses:
                self.add_error("recipients", "Indique au moins une adresse.")
            elif bad:
                self.add_error("recipients", f"Adresse invalide : {', '.join(bad)}")
            data["recipients"] = "\n".join(addresses)
            if not (data.get("subject") or "").strip():
                self.add_error("subject", "Objet vide.")
        if data.get("when") == "later":
            at = data.get("scheduled_at")
            if not at:
                self.add_error("scheduled_at", "Indique la date et l'heure de publication.")
            elif at < timezone.now() - timedelta(minutes=1):
                self.add_error("scheduled_at", "Cette date est passée.")
        data["chosen"] = chosen
        return data
