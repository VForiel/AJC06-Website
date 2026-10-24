from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core import markdown
from core.i18n import Translated
from core.images import normalize_field, validate_image


class PostQuerySet(models.QuerySet):
    def live(self):
        return self.filter(status=Post.Status.PUBLISHED, published_at__lte=timezone.now())


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        PUBLISHED = "published", "Publié"

    title = models.CharField("titre", max_length=200)
    slug = models.SlugField(unique=True, max_length=200, blank=True)
    status = models.CharField("statut", max_length=12, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField("date de publication", default=timezone.now,
                                        help_text="Une date future programme la publication")
    cover = models.ImageField("image de couverture", upload_to="actu/", blank=True, validators=[validate_image])
    excerpt = models.CharField("chapeau", max_length=300, blank=True, help_text="Vide = début du texte")
    body = models.TextField("texte")
    title_en = models.CharField("titre (anglais)", max_length=200, blank=True)
    excerpt_en = models.CharField("chapeau (anglais)", max_length=300, blank=True)
    body_en = models.TextField("texte (anglais)", blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                               verbose_name="auteur·rice")
    legacy_slug = models.CharField(max_length=200, blank=True, editable=False,
                                   help_text="Adresse sur l'ancien site, pour la redirection")
    legacy_slug_en = models.CharField(max_length=200, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    title_tr = Translated("title")
    excerpt_tr = Translated("excerpt")
    body_tr = Translated("body")

    class Meta:
        ordering = ["-published_at"]
        verbose_name = "article"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:180] or "article"
            slug, n = base, 2
            while Post.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        normalize_field(self, "cover")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("blog:detail", args=[self.slug])

    @property
    def is_live(self):
        return self.status == self.Status.PUBLISHED and self.published_at <= timezone.now()

    @property
    def body_html(self):
        return markdown.render(self.body_tr)

    @property
    def teaser(self):
        return self.excerpt_tr or markdown.plain(self.body_tr, 200)

    @property
    def reading_minutes(self):
        return max(1, round(len(markdown.plain(self.body_tr).split()) / 220))
