from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    # Les chemins anglais reprennent ceux de l'ancien site (/en/team/, /en/legal-notice/…).
    path(_("missions/"), views.missions, name="missions"),
    path(_("equipe/"), views.team, name="team"),
    path(_("ressources/"), views.resources, name="resources"),
    path(_("ressources/<slug:slug>/"), views.resource, name="resource"),
    path("contact/", views.contact, name="contact"),
    path(_("soutenir/"), views.support, name="support"),
    path(_("mentions-legales/"), views.legal, name="legal"),
    path(_("confidentialite/"), views.privacy, name="privacy"),
]
