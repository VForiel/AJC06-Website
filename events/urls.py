from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="list"),
    path("agenda.ics", views.agenda_ics, name="agenda"),
    path("nice-event.json", views.nice_event_feed, name="nice_event_feed"),
    path("<slug:slug>/", views.event_detail, name="detail"),
    path("<slug:slug>.ics", views.event_ics, name="ics"),
]
