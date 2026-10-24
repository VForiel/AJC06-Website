from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.sitemaps import GenericSitemap, Sitemap
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, reverse
from django.utils.translation import gettext_lazy as _
from blog.models import Post
from core import media as core_media
from core import views as core_views
from core.models import Resource
from events.models import Event


class StaticSitemap(Sitemap):
    i18n = True
    alternates = True

    def items(self):
        return ["core:home", "events:list", "blog:list", "core:missions", "core:team", "core:resources",
                "core:support", "core:contact"]

    def location(self, item):
        return reverse(item)


def localized(info):
    sitemap = GenericSitemap(info)
    sitemap.i18n = True
    sitemap.alternates = True
    return sitemap


sitemaps = {
    "pages": StaticSitemap,
    "evenements": localized({"queryset": Event.objects.published(), "date_field": "updated_at"}),
    "actu": localized({"queryset": Post.objects.live(), "date_field": "updated_at"}),
    "ressources": localized({"queryset": Resource.objects.all(), "date_field": "updated_at"}),
}

admin.site.site_header = "AJC06 — administration"
admin.site.site_title = "AJC06"

# Pages publiques : en français à la racine, en anglais sous /en/.
urlpatterns = i18n_patterns(
    path("", include("core.urls")),
    path("", include("community.urls")),  # avant events : « evenements/proposer/ » ne doit pas être pris pour un slug
    path(_("evenements/"), include("events.urls")),
    path(_("actu/"), include("blog.urls")),
    prefix_default_language=False,
)

# Espace bureau et administration : en français uniquement.
urlpatterns += [
    path("gestion/", include("gestion.urls")),
    path("admin/", admin.site.urls),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", core_views.robots),
]

# Fichiers téléversés : servis par Django, qui réserve les pièces des dossiers au bureau (core/media.py).
urlpatterns += [path("media/<path:path>", core_media.media)]

handler404 = "core.views.not_found"
