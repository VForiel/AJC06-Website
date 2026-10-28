"""Synchronise les inscriptions HelloAsso des événements à venir (et récents).

À lancer régulièrement (tâche cron), par exemple toutes les heures :
    python manage.py sync_helloasso

Les événements passés sans lien d'inscription sont rapprochés des formulaires HelloAsso de l'asso (même jour,
titre le plus proche), clôturés compris. Les campagnes passées sont lues une fois après la fin de l'événement
(nombre d'inscrit·es et liste des bilans) ; `--all` relit tout l'historique.
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
        try:
            for event in helloasso.discover_links(Event.objects.official().past().filter(registration_url="")):
                self.stdout.write(f"{event.slug} : formulaire trouvé, {event.registration_url}")
        except helloasso.HelloAssoError as error:
            self.stderr.write(f"Liste des formulaires : {error}")
        events = Event.objects.filter(registration_url__contains="helloasso.com")
        if not options["all"]:
            recent = timezone.localdate() - timedelta(days=30)
            events = [e for e in events if e.start_date >= recent or helloasso.needs_sync(e)]
        for event in events:
            try:
                count = helloasso.sync_event(event)
            except helloasso.HelloAssoError as error:
                self.stderr.write(f"{event.slug} : {error}")
                continue
            if count is not None:
                self.stdout.write(f"{event.slug} : {count} inscription(s)")
