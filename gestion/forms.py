from django import forms

from blog.models import Post
from community.forms import EventTypesMixin
from core.images import validate_image
from events.models import Event


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kwargs):
        super().__init__(format="%H:%M", **kwargs)


class MarkdownArea(forms.Textarea):
    template_name = "gestion/widgets/markdown.html"

    def __init__(self, rows=16):
        super().__init__(attrs={"rows": rows, "class": "md-input", "data-markdown": ""})


class EventForm(EventTypesMixin, forms.ModelForm):
    staff = True

    class Meta:
        model = Event
        fields = [
            "title", "other_type", "start_date", "start_time", "end_date", "end_time", "venue", "address", "price",
            "registration_url", "capacity", "poster", "summary", "body", "is_published", "on_hold",
            "title_en", "price_en", "summary_en", "body_en",
        ]
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "start_time": TimeInput(),
            "end_time": TimeInput(),
            "poster": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "body": MarkdownArea(),
            "body_en": MarkdownArea(rows=10),
            "registration_url": forms.URLInput(attrs={"placeholder": "https://www.helloasso.com/…"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_types()

    def save(self, commit=True):
        event = super().save(commit=False)
        event.set_types(self.cleaned_codes)
        if commit:
            event.save()
        return event

    def clean(self):
        data = super().clean()
        self.cleaned_codes = self.clean_types(data)
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "La date de fin est avant la date de début.")
        if data.get("end_time") and not data.get("start_time"):
            self.add_error("start_time", "Indique aussi l'heure de début (ou laisse les deux vides pour toute la journée).")
        if (start and not end and data.get("start_time") and data.get("end_time")
                and data["end_time"] <= data["start_time"]):
            self.add_error("end_time", "L'heure de fin est avant l'heure de début.")
        return data


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["title", "status", "published_at", "cover", "excerpt", "body", "title_en", "excerpt_en", "body_en"]
        widgets = {
            "published_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "cover": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "excerpt": forms.Textarea(attrs={"rows": 2}),
            "body": MarkdownArea(rows=22),
            "excerpt_en": forms.Textarea(attrs={"rows": 2}),
            "body_en": MarkdownArea(rows=14),
        }


class UploadForm(forms.Form):
    file = forms.ImageField(validators=[validate_image])
