"""Synchronise les inscriptions HelloAsso des événements à venir (et récents).

À lancer régulièrement (tâche cron), par exemple toutes les heures :
    python manage.py sync_helloasso
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event
from projets import helloasso


class Command(BaseCommand):
    help = "Récupère le nombre d'inscrit·es HelloAsso des événements qui ont un lien d'inscription HelloAsso."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Tous les événements, pas seulement les récents")

    def handle(self, *args, **options):
        if not helloasso.configured():
            self.stderr.write("Identifiants HelloAsso absents (/gestion/reglages/) : rien à faire.")
            return
        events = Event.objects.filter(registration_url__contains="helloasso.com")
        if not options["all"]:
            events = events.filter(start_date__gte=timezone.localdate() - timedelta(days=30))
        for event in events:
            try:
                count = helloasso.sync_event(event)
            except helloasso.HelloAssoError as error:
                self.stderr.write(f"{event.slug} : {error}")
                continue
            if count is not None:
                self.stdout.write(f"{event.slug} : {count} inscription(s)")
