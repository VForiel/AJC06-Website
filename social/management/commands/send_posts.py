from django.core.management.base import BaseCommand

from social.service import send_due


class Command(BaseCommand):
    help = "Envoie les diffusions programmées arrivées à échéance (Instagram, Facebook, courriel)."

    def handle(self, *args, **options):
        self.stdout.write(send_due())
