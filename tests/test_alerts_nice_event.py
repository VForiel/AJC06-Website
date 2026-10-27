from io import StringIO

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from community.models import AlertPreference, Notification
from events.models import Event

from .test_community import TestCase, member, soon


class NiceEventTests(TestCase):
    """Sorties de membres reprises par nice-event.fr (case cochée par défaut)."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")

    def setUp(self):
        super().setUp()
        cache.clear()

    def propose(self, **extra):
        self.client.force_login(self.alice)
        data = {"title": "Soirée Halloween", "type_list": ["soiree"], "start_date": soon().isoformat(),
                "start_time": "20:00", "venue": "Le Comptoir", "address": "12 rue Bonaparte, 06300 Nice",
                "price": "Gratuit", "summary": "Costumes bienvenus", "body": "Quiz et soupe au potiron."}
        data.update(extra)
        self.client.post(reverse("community:event_new"), data)
        return Event.objects.get(title=data["title"])

    def test_checked_by_default_and_feed(self):
        self.client.force_login(self.alice)
        form = self.client.get(reverse("community:event_new"))
        self.assertContains(form, 'name="on_nice_event"')
        self.assertContains(form, "checked", html=False)
        shared = self.propose(on_nice_event="on")
        self.propose(title="Entre nous")  # case décochée
        Event.objects.create(title="Meet-up du bureau", types=",meetup,", start_date=soon())  # officiel : jamais repris
        data = self.client.get(reverse("events:nice_event_feed")).json()
        self.assertEqual([e["title"] for e in data["events"]], ["Soirée Halloween"])
        item = data["events"][0]
        self.assertEqual((item["id"], item["description"], item["types"], item["price"]),
                         (shared.pk, "Quiz et soupe au potiron.", ["soiree"], "Gratuit"))
        self.assertTrue(item["start"].endswith("+01:00") or item["start"].endswith("+02:00"))
        self.assertNotIn("Alice", str(data))  # pas le nom du membre
        page = self.client.get(shared.get_absolute_url())
        self.assertContains(page, f"https://nice-event.fr/evenements/source/ajc06/{shared.pk}/")
        page = self.client.get(Event.objects.get(title="Entre nous").get_absolute_url())
        self.assertNotContains(page, "Voir sur Nice-Event")


class AlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")
        cls.bob = member("Bob Martin")

    def test_page_filters_and_alerts(self):
        self.client.force_login(self.bob)
        menu = self.client.get(reverse("community:me"), follow=True)
        self.assertContains(menu, reverse("community:alerts"))
        response = self.client.post(reverse("community:alerts"), {
            "type_list": ["plein-air", "sport"], "origin": "communaute", "active": "on", "by_email": "on"})
        self.assertRedirects(response, reverse("community:alerts"))
        pref = AlertPreference.objects.get(user=self.bob)
        self.assertEqual((pref.type_codes, pref.origin, pref.active), (["plein-air", "sport"], "communaute", True))
        self.assertIsNotNone(pref.active_since)
        page = self.client.get(reverse("community:alerts"))
        self.assertContains(page, "type=plein-air&amp;type=sport&amp;par=communaute")

        # Nouvelle sortie de membre qui correspond, une autre qui ne correspond pas, un événement officiel
        Event.objects.create(title="Rando", types=",plein-air,", start_date=soon(), is_community=True, organizer=self.alice)
        Event.objects.create(title="Afterwork", types=",afterwork,", start_date=soon(), is_community=True, organizer=self.alice)
        Event.objects.create(title="Tournoi du bureau", types=",sport,", start_date=soon())
        call_command("send_alerts", stdout=StringIO())
        call_command("send_alerts", stdout=StringIO())  # rien en double
        alerts = Notification.objects.filter(recipient=self.bob, verb="alert")
        self.assertEqual([n.event.title for n in alerts], ["Rando"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rando", mail.outbox[0].body)
        self.assertContains(self.client.get(reverse("community:notifications")), "Nouvel événement pour ton alerte")

        # Agenda : plusieurs types à la fois
        agenda = self.client.get(reverse("events:list"), {"type": ["plein-air", "afterwork"]})
        self.assertEqual(sorted(e.title for e in agenda.context["upcoming"]), ["Afterwork", "Rando"])

    def test_inactive_alert_sends_nothing(self):
        AlertPreference.objects.create(user=self.bob, active=False, active_since=timezone.now())
        Event.objects.create(title="Rando", types=",plein-air,", start_date=soon(), is_community=True, organizer=self.alice)
        call_command("send_alerts", stdout=StringIO())
        self.assertFalse(Notification.objects.filter(verb="alert").exists())

    def test_evening_ending_at_midnight(self):
        from datetime import time

        event = Event.objects.create(title="Halloween", types=",soiree,", start_date=soon(), start_time=time(19),
                                     end_time=time(0), is_community=True, organizer=self.alice)
        self.assertEqual(event.ends_at - event.starts_at, timezone.timedelta(hours=5))
        item = self.client.get(reverse("events:nice_event_feed")).json()["events"][0]
        self.assertGreater(item["end"], item["start"])
