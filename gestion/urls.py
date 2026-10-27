from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "gestion"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("connexion/", auth_views.LoginView.as_view(template_name="gestion/login.html", next_page="gestion:dashboard"),
         name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("evenements/", views.event_list, name="events"),
    path("evenements/nouveau/", views.event_edit, name="event_new"),
    path("evenements/<int:pk>/", views.event_edit, name="event_edit"),
    path("evenements/<int:pk>/dupliquer/", views.event_duplicate, name="event_duplicate"),
    path("evenements/<int:pk>/supprimer/", views.event_delete, name="event_delete"),
    path("articles/", views.post_list, name="posts"),
    path("articles/nouveau/", views.post_edit, name="post_new"),
    path("articles/<int:pk>/", views.post_edit, name="post_edit"),
    path("articles/<int:pk>/supprimer/", views.post_delete, name="post_delete"),
    path("messages/", views.inbox, name="inbox"),
    path("signalements/", views.reports, name="reports"),
    path("comptes/", views.accounts, name="accounts"),
    path("comptes/<int:pk>/", views.account_decide, name="account_decide"),
    path("soutiens/", views.supports, name="supports"),
    path("soutiens/<int:pk>/decision/", views.support_decide, name="support_decide"),
    path("evenements/<int:pk>/dossier/", views.dossier, name="dossier"),
    path("evenements/<int:pk>/dossier/pieces/", views.dossier_attach, name="dossier_attach"),
    path("evenements/<int:pk>/dossier/pieces/<int:attachment>/supprimer/", views.dossier_detach, name="dossier_detach"),
    path("evenements/<int:pk>/dossier/<str:kind>.pdf", views.dossier_pdf, name="dossier_pdf"),
    path("evenements/<int:pk>/attente/", views.event_hold, name="event_hold"),
    path("evenements/<int:pk>/helloasso/", views.helloasso_sync, name="helloasso_sync"),
    path("annonces/", views.announcements, name="announcements"),
    path("annonces/<int:pk>/", views.announcements, name="announcement_edit"),
    path("effets/", views.effects_page, name="effects"),
    path("reglages/", views.site_settings, name="settings"),
    path("reglages/test-courriel/", views.test_email, name="test_email"),
    path("signalements/<int:pk>/traite/", views.report_toggle, name="report_toggle"),
    path("evenements/<int:pk>/masquer/", views.event_hide, name="event_hide"),
    path("messages/<int:pk>/traite/", views.inbox_toggle, name="inbox_toggle"),
    path("evenements/<int:pk>/diffuser/", views.diffuse, name="diffuse"),
    path("diffusions/", views.diffusion_list, name="diffusions"),
    path("diffusions/<int:pk>/", views.diffusion_action, name="diffusion_action"),
    path("reglages/test-reseau/<str:network>/", views.test_network, name="test_network"),
    path("apercu/", views.preview, name="preview"),
    path("televerser/", views.upload, name="upload"),
]
