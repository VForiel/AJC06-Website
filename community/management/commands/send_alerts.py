"""Alertes des membres : nouvel événement qui correspond à leur filtre -> notification sur le site (+ courriel).

Lancé par cron toutes les 15 minutes en production (voir le README).
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import translation

from community.models import AlertPreference, AlertSent, Notification
from events.models import Event

log = logging.getLogger(__name__)


def new_events(pref):
    """Événements visibles, à venir, publiés ou modifiés depuis l'activation de l'alerte, pas encore signalés."""
    events = Event.objects.published().upcoming().exclude(organizer=pref.user)
    events = events.filter(Q(created_at__gte=pref.active_since) | Q(updated_at__gte=pref.active_since))
    events = pref.matching(events).exclude(pk__in=AlertSent.objects.filter(user=pref.user).values("event_id"))
    return list(events.order_by("start_date", "start_time")[:20])


class Command(BaseCommand):
    help = "Envoie les alertes « nouvel événement » des membres."

    def handle(self, *args, **options):
        sent = 0
        for pref in AlertPreference.objects.filter(active=True, user__is_active=True).select_related("user__profile"):
            events = new_events(pref)
            if not events:
                continue
            for event in events:
                AlertSent.objects.get_or_create(user=pref.user, event=event)
                Notification.objects.create(recipient=pref.user, actor=None, verb=Notification.Verb.ALERT, event=event)
            if pref.by_email and pref.user.email:
                self.email(pref, events)
            sent += 1
        self.stdout.write(f"{sent} alerte(s) envoyée(s)")

    def email(self, pref, events):
        name = getattr(getattr(pref.user, "profile", None), "display_name", "") or pref.user.get_full_name()
        context = {"name": name, "events": events, "site": settings.SITE_URL}
        with translation.override("fr"):
            subject = (f"AJC06 : {events[0].title}" if len(events) == 1
                       else f"AJC06 : {len(events)} nouveaux événements")
            body = render_to_string("community/alert_email.txt", context)
        try:
            send_mail(subject, body, None, [pref.user.email], fail_silently=False)
        except Exception:
            log.exception("Courriel d'alerte non envoyé à l'utilisateur %s", pref.user.pk)
