"""Billets HelloAsso reliés aux comptes du site par adresse confirmée, adresses supplémentaires, « +1 »."""

from datetime import timedelta
from urllib.parse import urlparse
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from community import addresses
from community.models import Attendance, EmailAddress, Notification, Profile
from events.models import Event
from projets import helloasso
from projets.models import HelloAssoTicket

LINK = "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/rando"


def account(name, email):
    user = User.objects.create_user(username=email, email=email, password="x")
    Profile.objects.filter(user=user).update(display_name=name)
    return user


def item(n, email, payer="payeur@example.org"):
    return {"id": n, "type": "Registration", "user": {"firstName": "P", "lastName": str(n)},
            "payer": {"email": payer}, "customFields": [{"name": "Email", "type": "TextInput", "answer": email}]}


@override_settings(HELLOASSO_CLIENT_ID="id", HELLOASSO_CLIENT_SECRET="secret")
class LinkTests(TestCase):
    def setUp(self):
        translation.activate("fr")
        cache.clear()
        self.lea = account("Léa Martin", "lea@unice.fr")
        addresses.confirm(EmailAddress.objects.get(user=self.lea))
        self.event = Event.objects.create(title="Rando", start_date=timezone.localdate() - timedelta(days=20),
                                          registration_url=LINK)

    def sync(self, items):
        with mock.patch.object(helloasso, "form_items", return_value=items):
            helloasso.sync_event(self.event)

    def test_same_address_twice_means_plus_one(self):
        self.sync([item(1, "LEA@unice.fr"), item(2, "lea@unice.fr"), item(3, "autre@example.org")])
        attendance = Attendance.objects.get(event=self.event, user=self.lea)
        self.assertTrue(attendance.via_helloasso)
        self.assertEqual(attendance.guests, 1)
        self.event.refresh_from_db()
        self.assertEqual(self.event.helloasso_count, 3)  # le +1 compte parmi les participant·es
        self.assertEqual(Notification.objects.filter(recipient=self.lea, verb="helloasso").count(), 1)
        self.client.force_login(self.lea)
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, "3 personnes y ont participé")
        self.assertContains(page, "Léa Martin +1")
        self.assertContains(page, "avec 1 accompagnant·e")

    def test_payer_address_when_no_participant_address(self):
        self.sync([{"id": 1, "type": "Registration", "user": {}, "payer": {"email": "lea@unice.fr"}}])
        self.assertTrue(Attendance.objects.filter(event=self.event, user=self.lea, guests=0).exists())

    def test_refund_removes_only_the_helloasso_participation(self):
        self.sync([item(1, "lea@unice.fr")])
        self.sync([])
        self.assertFalse(Attendance.objects.filter(event=self.event, user=self.lea).exists())

    def test_removed_by_the_person_stays_removed(self):
        self.sync([item(1, "lea@unice.fr")])
        self.client.force_login(self.lea)
        self.client.post(reverse("community:attend", args=[self.event.slug]))
        self.sync([item(1, "lea@unice.fr")])
        self.assertFalse(Attendance.objects.filter(event=self.event, user=self.lea).exists())

    def test_setting_off_unlinks(self):
        self.sync([item(1, "lea@unice.fr")])
        Profile.objects.filter(user=self.lea).update(link_helloasso=False)
        from projets import linking

        linking.link_user(self.lea)
        self.assertFalse(Attendance.objects.filter(event=self.event, user=self.lea).exists())

    def test_other_address_links_once_confirmed(self):
        self.sync([item(1, "lea.perso@gmail.com")])
        self.assertFalse(Attendance.objects.exists())
        self.client.force_login(self.lea)
        self.client.post(reverse("community:address_add"), {"a-email": "Lea.Perso@gmail.com"})
        address = EmailAddress.objects.get(email="lea.perso@gmail.com")
        self.assertFalse(address.confirmed)
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(Attendance.objects.exists())  # pas avant la confirmation
        link = addresses.link(address)
        self.assertIn(link, mail.outbox[0].body)
        self.client.get(urlparse(link).path)
        address.refresh_from_db()
        self.assertTrue(address.confirmed)
        self.assertTrue(Attendance.objects.filter(event=self.event, user=self.lea, via_helloasso=True).exists())

    def test_unconfirmed_or_foreign_address_never_links(self):
        karim = account("Karim B", "karim@example.org")  # adresse principale non confirmée
        self.sync([item(1, "karim@example.org")])
        self.assertFalse(Attendance.objects.filter(user=karim).exists())
        self.client.force_login(karim)
        self.client.post(reverse("community:address_add"), {"a-email": "lea@unice.fr"})
        self.assertFalse(EmailAddress.objects.filter(user=karim, email="lea@unice.fr").exists())

    def test_ticket_email_prefers_participant(self):
        self.assertEqual(helloasso.ticket_email(item(1, " Part@Ex.org ")), "part@ex.org")
        self.assertEqual(helloasso.ticket_email({"user": {"email": "u@ex.org"}, "payer": {"email": "p@ex.org"}}), "u@ex.org")
        self.assertEqual(helloasso.ticket_email({"payer": {"email": "p@ex.org"}}), "p@ex.org")
        self.assertEqual(helloasso.ticket_email({}), "")
