import shutil
import tempfile
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase as BaseTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from community.models import Attendance, Friendship, Notification, Profile, Report, friends_of, relation
from events.models import Event

MEDIA = tempfile.mkdtemp()


class TestCase(BaseTestCase):
    """La langue active persiste d'une requête de test à l'autre : chaque test repart du français."""

    def setUp(self):
        super().setUp()
        translation.activate("fr")


def member(name, email=None, **profile):
    email = email or f"{name.split()[0].lower()}@example.org"
    user = User.objects.create_user(username=email, email=email, password="motdepasse-solide")
    Profile.objects.filter(user=user).update(display_name=name, handle="", **profile)
    p = user.profile
    p.refresh_from_db()
    p.save()  # recalcule l'adresse du profil à partir du nom
    return user


def soon(days=7):
    return timezone.localdate() + timedelta(days=days)


@override_settings(MEDIA_ROOT=MEDIA)
class SignupTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        cache.clear()

    def data(self, **extra):
        data = {"display_name": "Camille Martin", "email": "Camille@Example.org", "password": "une-phrase-longue",
                "consent": "on"}
        data.update(extra)
        return data

    def test_signup_creates_member_and_logs_in(self):
        response = self.client.post(reverse("community:signup"), self.data())
        self.assertRedirects(response, reverse("community:settings"))
        user = User.objects.get(email="camille@example.org")
        self.assertFalse(user.is_staff)
        self.assertEqual(user.profile.handle, "camille-martin")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_login_with_email(self):
        member("Camille Martin", "camille@example.org")
        response = self.client.post(reverse("community:login"), {"username": "CAMILLE@example.org", "password": "motdepasse-solide"})
        self.assertEqual(response.status_code, 302)

    def test_duplicate_email_and_weak_password_rejected(self):
        member("Camille Martin", "camille@example.org")
        response = self.client.post(reverse("community:signup"), self.data(password="123"))
        self.assertContains(response, "Un compte existe déjà avec cette adresse.")
        self.assertEqual(User.objects.count(), 1)

    def test_honeypot_and_throttle(self):
        self.client.post(reverse("community:signup"), self.data(website="http://spam.example"))
        self.assertFalse(User.objects.exists())
        for i in range(6):
            self.client.logout()
            self.client.post(reverse("community:signup"), self.data(email=f"p{i}@example.org"))
        self.assertEqual(User.objects.count(), 5)

    def test_staff_accounts_get_a_profile(self):
        admin = User.objects.create_superuser("bureau", "b@example.org", "x")
        self.assertTrue(Profile.objects.filter(user=admin).exists())

    def test_delete_account(self):
        user = member("Camille Martin")
        event = Event.objects.create(title="Rando", start_date=soon(), is_community=True, organizer=user)
        self.client.force_login(user)
        self.client.post(reverse("community:delete_account"), {"password": "motdepasse-solide"})
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        event.refresh_from_db()
        self.assertIsNone(event.organizer)


@override_settings(MEDIA_ROOT=MEDIA)
class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand", discipline="Astrophysique", doctoral_school="sfa", interests="escalade, jeux")
        cls.bob = member("Bob Martin")

    def test_profile_hidden_from_anonymous_by_default(self):
        url = self.alice.profile.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.bob)
        response = self.client.get(url)
        self.assertContains(response, "Alice Durand")
        self.assertContains(response, "Astrophysique")
        self.assertNotContains(response, self.alice.email)

    def test_public_profile(self):
        Profile.objects.filter(user=self.alice).update(visibility="public")
        self.assertEqual(self.client.get(self.alice.profile.get_absolute_url()).status_code, 200)

    def test_settings_update_and_accent(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:settings"), {
            "save_profile": "1", "p-display_name": "Alice D.", "p-accent": "corail", "p-visibility": "membres",
            "p-headline": "En rédaction", "p-orcid": "0000-0002-1825-0097", "p-show_events": "on",
            "p-contact_visibility": "amis",
        })
        self.assertRedirects(response, reverse("community:settings"))
        profile = Profile.objects.get(user=self.alice)
        self.assertEqual(profile.accent, "corail")
        self.assertContains(self.client.get(profile.get_absolute_url()), "accent-corail")

    def test_bad_orcid(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:settings"), {
            "save_profile": "1", "p-display_name": "Alice", "p-accent": "azur", "p-visibility": "membres", "p-orcid": "123",
            "p-contact_visibility": "amis",
        }, follow=True)
        self.assertContains(response, "Format attendu")  # signalé, mais n'empêche pas d'enregistrer le reste
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.orcid, "")

    def test_directory_search(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("community:members"), {"q": "escalade"})
        self.assertContains(response, "Alice Durand")
        self.assertNotContains(response, "Bob Martin</strong>")
        self.assertEqual(self.client.get(reverse("community:members"), {"ed": "sfa"}).context["people"].count(), 1)

    def test_directory_requires_login(self):
        self.assertEqual(self.client.get(reverse("community:members")).status_code, 302)


class FriendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")
        cls.bob = member("Bob Martin")

    def friend(self, user, other, action):
        self.client.force_login(user)
        return self.client.post(reverse("community:friend", args=[other.profile.handle, action]))

    def test_request_accept_remove(self):
        self.friend(self.alice, self.bob, "add")
        self.assertEqual(relation(self.alice, self.bob), "sent")
        self.assertEqual(relation(self.bob, self.alice), "received")
        self.assertTrue(Notification.objects.filter(recipient=self.bob, verb="friend_request").exists())
        self.friend(self.bob, self.alice, "accept")
        self.assertEqual(list(friends_of(self.alice)), [self.bob])
        self.assertTrue(Notification.objects.filter(recipient=self.alice, verb="friend_accepted").exists())
        self.friend(self.alice, self.bob, "remove")
        self.assertFalse(Friendship.objects.exists())

    def test_cannot_accept_own_request(self):
        self.friend(self.alice, self.bob, "add")
        self.friend(self.alice, self.bob, "accept")
        self.assertFalse(Friendship.objects.get().accepted)

    def test_friend_button_states(self):
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(self.bob.profile.get_absolute_url()), "Ajouter en ami")
        self.friend(self.alice, self.bob, "add")
        self.assertContains(self.client.get(self.bob.profile.get_absolute_url()), "Demande envoyée")
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(self.alice.profile.get_absolute_url()), "Accepter la demande")
        self.assertContains(self.client.get(reverse("community:friends")), "Demandes reçues")

    def test_notification_badge_and_read(self):
        self.friend(self.alice, self.bob, "add")
        self.client.force_login(self.bob)
        self.assertContains(self.client.get("/"), 'class="badge"')
        self.client.get(reverse("community:notifications"))
        self.assertFalse(Notification.objects.filter(recipient=self.bob, read=False).exists())


@override_settings(MEDIA_ROOT=MEDIA)
class CommunityEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")
        cls.bob = member("Bob Martin")
        cls.carol = member("Carol Petit")
        Friendship.objects.create(from_user=cls.alice, to_user=cls.bob, accepted=True)

    def setUp(self):
        super().setUp()
        cache.clear()

    def propose(self, user=None, **extra):
        self.client.force_login(user or self.alice)
        data = {"title": "Rando au mont Chauve", "type_list": ["plein-air"], "start_date": soon().isoformat(),
                "start_time": "09:00", "venue": "Parking de l'Aire Saint-Michel", "price": "Gratuit", "capacity": "2"}
        data.update(extra)
        return self.client.post(reverse("community:event_new"), data)

    def test_member_can_propose(self):
        response = self.propose()
        event = Event.objects.get()
        self.assertRedirects(response, event.get_absolute_url())
        self.assertTrue(event.is_community and event.is_published)
        self.assertEqual(event.organizer, self.alice)
        self.assertTrue(Attendance.objects.filter(event=event, user=self.alice).exists())
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, "Proposé par")
        self.assertContains(page, "Alice Durand")
        self.assertContains(self.client.get(reverse("events:list"), {"par": "communaute"}), "Rando au mont Chauve")
        self.assertNotContains(self.client.get(reverse("events:list"), {"par": "asso"}), "Rando au mont Chauve")

    def test_anonymous_cannot_propose(self):
        response = self.client.get(reverse("community:event_new"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("community:login"), response["Location"])

    def test_past_date_rejected(self):
        self.propose(start_date=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertFalse(Event.objects.exists())

    def test_only_organizer_edits(self):
        self.propose()
        event = Event.objects.get()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("community:event_edit", args=[event.slug])).status_code, 403)
        self.assertEqual(self.client.post(reverse("community:event_delete", args=[event.slug])).status_code, 403)
        self.client.force_login(self.alice)
        self.client.post(reverse("community:event_delete", args=[event.slug]))
        self.assertFalse(Event.objects.exists())

    def test_members_cannot_edit_official_events(self):
        official = Event.objects.create(title="Winter camp", start_date=soon())
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("community:event_edit", args=[official.slug])).status_code, 404)

    def test_attend_capacity_and_notification(self):
        self.propose()
        event = Event.objects.get()
        self.client.force_login(self.bob)
        self.client.post(reverse("community:attend", args=[event.slug]))
        self.assertEqual(event.attendee_count, 2)
        self.assertTrue(Notification.objects.filter(recipient=self.alice, verb="attending", event=event).exists())
        self.client.force_login(self.carol)
        self.client.post(reverse("community:attend", args=[event.slug]))
        self.assertEqual(event.attendee_count, 2)  # complet : 2 places
        self.client.force_login(self.bob)
        self.client.post(reverse("community:attend", args=[event.slug]))  # se désinscrit
        self.assertEqual(event.attendee_count, 1)

    def test_attend_official_event_and_friends_going(self):
        official = Event.objects.create(title="Winter camp", start_date=soon(), start_time=time(9))
        Attendance.objects.create(event=official, user=self.bob)
        self.client.force_login(self.alice)
        response = self.client.get(official.get_absolute_url())
        self.assertContains(response, "1 de tes amis y va")
        self.assertContains(response, "Bob Martin")
        self.client.logout()
        response = self.client.get(official.get_absolute_url())
        self.assertNotContains(response, "Bob Martin")
        self.assertContains(response, "Connecte-toi pour voir qui y va.")

    def test_invite_only_friends(self):
        self.propose()
        event = Event.objects.get()
        self.client.post(reverse("community:invite", args=[event.slug]), {"friends": [self.bob.pk, self.carol.pk]})
        self.assertTrue(Notification.objects.filter(recipient=self.bob, verb="invite").exists())
        self.assertFalse(Notification.objects.filter(recipient=self.carol, verb="invite").exists())

    def test_report_and_hide(self):
        self.propose()
        event = Event.objects.get()
        self.client.force_login(self.bob)
        self.client.post(reverse("community:report", args=["evenement", event.slug]), {"reason": "Pub déguisée"})
        report = Report.objects.get()
        staff = User.objects.create_user("bureau", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("gestion:reports")), "Pub déguisée")
        self.client.post(reverse("gestion:event_hide", args=[event.pk]))
        event.refresh_from_db()
        self.assertFalse(event.is_published)
        self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 200)  # le bureau la voit encore
        self.client.force_login(self.carol)
        self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 404)
        self.client.force_login(staff)
        self.client.post(reverse("gestion:report_toggle", args=[report.pk]))
        report.refresh_from_db()
        self.assertTrue(report.handled)

    def test_daily_limit(self):
        for i in range(6):
            self.propose(title=f"Sortie {i}")
        self.assertEqual(Event.objects.count(), 5)

    def test_english_pages(self):
        self.client.force_login(self.alice)
        self.assertContains(self.client.get("/en/events/propose/"), "Propose an outing")
        self.assertContains(self.client.get("/en/members/"), "Members")
        self.assertContains(self.client.get(f"/en/members/{self.alice.profile.handle}/"), "Edit my profile")


class SignalTests(TestCase):
    def test_profile_signal_survives_garbage_collection(self):
        import gc

        gc.collect()
        user = User.objects.create_user("x@example.org", "x@example.org", "x")
        self.assertTrue(Profile.objects.filter(user=user).exists())
