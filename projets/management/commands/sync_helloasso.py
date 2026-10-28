"""Synchronise les inscriptions HelloAsso des événements à venir (et récents).

À lancer régulièrement (tâche cron), par exemple toutes les heures :
    python manage.py sync_helloasso

Les événements passés sans lien d'inscription sont rapprochés des formulaires HelloAsso de l'asso (même jour,
titre le plus proche), clôturés compris ; `--all` le fait pour tout l'historique.
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
        events = Event.objects.all()
        if not options["all"]:
            events = events.filter(start_date__gte=timezone.localdate() - timedelta(days=30))
        try:
            for event in helloasso.discover_links(events.official().filter(registration_url="")):
                self.stdout.write(f"{event.slug} : formulaire trouvé, {event.registration_url}")
        except helloasso.HelloAssoError as error:
            self.stderr.write(f"Liste des formulaires : {error}")
        for event in events.filter(registration_url__contains="helloasso.com"):
            try:
                count = helloasso.sync_event(event)
            except helloasso.HelloAssoError as error:
                self.stderr.write(f"{event.slug} : {error}")
                continue
            if count is not None:
                self.stdout.write(f"{event.slug} : {count} inscription(s)")
