from django import forms
from django.forms import inlineformset_factory

from .models import Attachment, BudgetLine, Dossier


class DossierForm(forms.ModelForm):
    class Meta:
        model = Dossier
        exclude = ["event"]
        widgets = {
            "resume": forms.Textarea(attrs={"rows": 4}),
            "objectives": forms.Textarea(attrs={"rows": 4}),
            "audience": forms.Textarea(attrs={"rows": 2}),
            "services": forms.Textarea(attrs={"rows": 2}),
            "programme": forms.Textarea(attrs={"rows": 4}),
            "impact": forms.Textarea(attrs={"rows": 3}),
            "quotes": forms.Textarea(attrs={"rows": 2}),
            "report_story": forms.Textarea(attrs={"rows": 6}),
            "report_assessment": forms.Textarea(attrs={"rows": 5}),
            "objectives_met": forms.Textarea(attrs={"rows": 3}),
            "submitted_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "report_submitted_at": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }


def budget_formset(phase):
    return inlineformset_factory(
        Dossier, BudgetLine, fields=["side", "label", "amount"], extra=3, can_delete=True,
        widgets={"label": forms.TextInput(attrs={"placeholder": "Intitulé"}),
                 "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"})},
    )


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["kind", "file", "label"]
        widgets = {"file": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"})}

    def clean_file(self):
        f = self.cleaned_data["file"]
        name = f.name.lower()
        if not name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")):
            raise forms.ValidationError("Formats acceptés : PDF, JPG, PNG, WebP.")
        if f.size > 12 * 1024 * 1024:
            raise forms.ValidationError("Fichier trop lourd (12 Mo maximum).")
        return f
