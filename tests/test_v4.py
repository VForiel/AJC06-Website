"""Types multiples, demandes de soutien, dossiers UniCA (PDF), photos, coordonnées, HelloAsso, effets, annonces."""

import io
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase as BaseTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image
from pypdf import PdfReader

from community.models import Attendance, Friendship, Notification, Photo, Profile
from core import effects
from core.models import Announcement
from events.models import Event
from projets import helloasso, pdf, services
from projets.models import Attachment, BudgetLine, HelloAssoTicket, SupportRequest

MEDIA = tempfile.mkdtemp()


class TestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("fr")
        cache.clear()


def member(name, staff=False):
    email = f"{name.split()[0].lower()}@example.org"
    user = User.objects.create_user(username=email, email=email, password="x", is_staff=staff)
    Profile.objects.filter(user=user).update(display_name=name, handle="")
    p = Profile.objects.get(user=user)
    p.save()
    user.profile.refresh_from_db()  # le profil créé par le signal est mis en cache sur l'utilisateur
    return user


def png(name="photo.png", size=(800, 600)):
    buf = io.BytesIO()
    Image.new("RGB", size, "#3894c0").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def in_days(n):
    return timezone.localdate() + timedelta(days=n)


class TypeTests(TestCase):
    def test_multiple_types_and_filter(self):
        e = Event.objects.create(title="Rando et apéro", start_date=in_days(5))
        e.set_types(["afterwork", "plein-air", "inconnu"])
        e.save()
        self.assertEqual(e.types, ",plein-air,afterwork,")
        self.assertEqual(list(Event.objects.with_type("afterwork")), [e])
        self.assertFalse(Event.objects.with_type("air").exists())
        response = self.client.get(reverse("events:list"), {"type": "afterwork"})
        self.assertContains(response, "Rando et apéro")

    def test_other_type_label(self):
        e = Event(title="Atelier", types=",autre,", other_type="Atelier poterie", start_date=in_days(3))
        self.assertEqual(e.type_labels, [("autre", "Atelier poterie")])

    def test_staff_only_types_hidden_from_members(self):
        alice = member("Alice Durand")
        self.client.force_login(alice)
        page = self.client.get(reverse("community:event_new")).content.decode()
        self.assertNotIn('value="camp"', page)
        self.assertIn('value="coworking"', page)
        self.client.post(reverse("community:event_new"), {
            "title": "Faux camp", "type_list": ["camp"], "start_date": in_days(5).isoformat()})
        self.assertFalse(Event.objects.exists())

    def test_other_requires_label(self):
        self.client.force_login(member("Alice Durand"))
        response = self.client.post(reverse("community:event_new"), {
            "title": "Truc", "type_list": ["autre"], "start_date": in_days(5).isoformat()})
        self.assertContains(response, "Précise le type.")


@override_settings(MEDIA_ROOT=MEDIA)
class SupportTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")
        cls.staff = member("Bureau AJC", staff=True)

    def propose(self, days=40, **extra):
        self.client.force_login(self.alice)
        data = {"title": "Paddle à Beaulieu", "type_list": ["sport"], "start_date": in_days(days).isoformat(),
                "venue": "Club nautique", "capacity": "10", "request_support": "on",
                "s-amount": "250", "s-access": "Train jusqu'à Beaulieu", "s-price_per_person": "25 €",
                "s-budget_details": "Location de paddles : 250 €\nParticipation des doctorant·es : 50 €",
                "s-booking": "asso"}
        data.update(extra)
        return self.client.post(reverse("community:event_new"), data)

    def test_request_needs_a_month(self):
        response = self.propose(days=10)
        self.assertContains(response, "au moins un mois avant")
        self.assertFalse(Event.objects.exists())

    def test_request_keeps_event_private_and_notifies_board(self):
        self.propose()
        event = Event.objects.get()
        self.assertFalse(event.is_published)
        self.assertEqual(event.support_request.amount, Decimal("250"))
        self.assertTrue(Notification.objects.filter(recipient=self.staff, verb="support").exists())
        self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 200)  # l'organisatrice la voit
        self.client.logout()
        self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 404)

    def test_approve_makes_it_an_association_event_on_hold(self):
        self.propose()
        support = SupportRequest.objects.get()
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:support_decide", args=[support.pk]), {"decision": "accept", "note": "OK"})
        event = Event.objects.get()
        self.assertTrue(event.supported and event.on_hold and event.is_association)
        self.assertIn(event, Event.objects.official())
        self.assertNotIn(event, Event.objects.community())
        self.assertFalse(Event.objects.published().filter(pk=event.pk).exists())  # en attente du dossier
        lines = {(l.label, l.side) for l in event.dossier.budget_lines.all()}
        self.assertIn(("Location de paddles", "depense"), lines)
        self.assertIn(("Participation des doctorant·es", "recette"), lines)
        self.assertIn(("Convention UniCA", "recette"), lines)
        self.assertTrue(Notification.objects.filter(recipient=self.alice, verb="support_answer").exists())

    def test_refuse_then_publish_anyway(self):
        self.propose()
        support = SupportRequest.objects.get()
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:support_decide", args=[support.pk]), {"decision": "refuse", "note": "Plus de fonds"})
        self.client.force_login(self.alice)
        event = Event.objects.get()
        self.assertContains(self.client.get(event.get_absolute_url()), "Plus de fonds")
        self.client.post(reverse("community:event_publish", args=[event.slug]))
        event.refresh_from_db()
        self.assertTrue(event.is_published and not event.supported)

    def test_parse_budget(self):
        rows = services.parse_budget("Billets : 20 x 10 = 200 €\nGoûter 45,50€\nsans montant\nSubvention mairie : 100")
        self.assertEqual(rows[0][1:], (Decimal("200"), "depense"))
        self.assertEqual(rows[1][1], Decimal("45.50"))
        self.assertEqual(rows[2][1:], (Decimal("100"), "recette"))
        self.assertEqual(len(rows), 3)


@override_settings(MEDIA_ROOT=MEDIA)
class DossierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = member("Bureau AJC", staff=True)
        cls.event = Event.objects.create(title="Winter camp", types=",camp,", start_date=in_days(20), capacity=30,
                                         venue="Gréolières", on_hold=True)

    def test_prefill_and_deadlines(self):
        dossier = services.dossier_for(self.event)
        self.assertEqual(dossier.convention_line, "camp")
        self.assertIn("Favoriser le bien-être", dossier.objectives)
        due = services.deadlines([self.event])[0]
        self.assertEqual(due["what"], "Projet prévisionnel")
        self.assertEqual(due["due"], self.event.start_date - timedelta(days=14))

    def test_on_hold_hidden_from_public(self):
        self.assertFalse(Event.objects.published().exists())
        self.assertEqual(self.client.get(self.event.get_absolute_url()).status_code, 404)

    def test_pdfs_contain_budget_participants_and_annexes(self):
        dossier = services.dossier_for(self.event)
        BudgetLine.objects.create(dossier=dossier, label="Hébergement", amount=Decimal("900"), side="depense")
        BudgetLine.objects.create(dossier=dossier, label="Convention UniCA", amount=Decimal("900"), side="recette")
        HelloAssoTicket.objects.create(event=self.event, ticket_id=1, first_name="KENZA", last_name="BENMOUSSA")
        invoice = io.BytesIO()
        from fpdf import FPDF
        f = FPDF(); f.add_page(); f.set_font("helvetica", size=12); f.cell(0, 10, "Facture 42"); invoice.write(bytes(f.output()))
        Attachment.objects.create(dossier=dossier, kind="facture",
                                  file=SimpleUploadedFile("facture.pdf", invoice.getvalue()), label="Facture hébergement")
        forecast = PdfReader(io.BytesIO(pdf.forecast(dossier)))
        text = "".join(p.extract_text() for p in forecast.pages)
        self.assertIn("Projet prévisionnel", text)
        self.assertIn("PhD seasonal camps", text)
        self.assertIn("Hébergement", text)
        self.assertIn("Kenza Benmoussa", text)
        report = PdfReader(io.BytesIO(pdf.report(dossier)))
        report_text = "".join(p.extract_text() for p in report.pages)
        self.assertIn("Compte-rendu", report_text)
        self.assertIn("Facture 42", report_text)  # facture PDF annexée en fin de bilan

    def test_dossier_page_and_pdf_view(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("gestion:dossier", args=[self.event.pk]))
        self.assertContains(page, "Projet prévisionnel")
        self.assertContains(page, "avant le")
        response = self.client.get(reverse("gestion:dossier_pdf", args=[self.event.pk, "previsionnel"]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_members_cannot_access_dossiers(self):
        self.client.force_login(member("Alice Durand"))
        self.assertEqual(self.client.get(reverse("gestion:dossier", args=[self.event.pk])).status_code, 403)


@override_settings(MEDIA_ROOT=MEDIA)
class PhotoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")
        cls.bob = member("Bob Martin")
        Friendship.objects.create(from_user=cls.alice, to_user=cls.bob, accepted=True)
        cls.event = Event.objects.create(title="Soirée jeux", types=",meetup,", start_date=in_days(-3))

    def test_upload_requires_consent(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:photo_new"), {"files": png(), "caption": "Partie"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Photo.objects.exists())

    def test_upload_tag_notify_untag(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("community:photo_new"), {
            "files": png(), "caption": "Partie endiablée", "event": self.event.pk, "consent": "on",
            "friends": [self.bob.pk]})
        photo = Photo.objects.get()
        self.assertTrue(photo.image.name.endswith(".webp"))
        self.assertEqual(list(photo.tagged.all()), [self.bob])
        self.assertTrue(Notification.objects.filter(recipient=self.bob, verb="photo_tag").exists())
        # La page de l'événement affiche une miniature, créée au premier affichage, et non l'image d'origine.
        thumb = f"/media/thumbs/320/{photo.image.name}"
        self.assertContains(self.client.get(self.event.get_absolute_url()), thumb)
        self.assertEqual(self.client.get(thumb).status_code, 200)
        self.client.logout()
        public = self.client.get(photo.get_absolute_url())
        self.assertNotContains(public, "Bob Martin")  # les noms ne sont visibles que des membres
        self.client.force_login(self.bob)
        self.client.post(reverse("community:photo_untag", args=[photo.pk]))
        self.assertFalse(photo.tagged.exists())

    def test_unknown_handle_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:photo_new"), {
            "files": png(), "consent": "on", "tagged_handles": "personne-inconnue"})
        self.assertContains(response, "Profil inconnu")


class ContactTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = member("Alice Durand")
        cls.bob = member("Bob Martin")
        cls.carol = member("Carol Petit")
        Profile.objects.filter(user=cls.alice).update(phone="06 12 34 56 78", instagram="alice.d")
        Friendship.objects.create(from_user=cls.alice, to_user=cls.bob, accepted=True)

    def test_contacts_visible_to_friends_only_by_default(self):
        url = self.alice.profile.get_absolute_url()
        self.client.force_login(self.bob)
        page = self.client.get(url)
        self.assertContains(page, "06 12 34 56 78")
        self.assertContains(page, "https://wa.me/33612345678")
        self.client.force_login(self.carol)
        self.assertNotContains(self.client.get(url), "06 12 34 56 78")

    def test_members_visibility(self):
        Profile.objects.filter(user=self.alice).update(contact_visibility="membres")
        self.client.force_login(self.carol)
        self.assertContains(self.client.get(self.alice.profile.get_absolute_url()), "@alice.d")


class HelloAssoTests(TestCase):
    def test_parse_link(self):
        self.assertEqual(helloasso.parse_link(
            "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/great-game"),
            ("association-des-jeunes-chercheurs-des-alpes-mariti", "Event", "great-game"))
        self.assertIsNone(helloasso.parse_link("https://forms.gle/abc"))

    @override_settings(HELLOASSO_CLIENT_ID="id", HELLOASSO_CLIENT_SECRET="secret")
    def test_sync_counts_and_removes_refunded(self):
        event = Event.objects.create(title="Great Game", start_date=in_days(10), registration_url=(
            "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/great-game"))
        HelloAssoTicket.objects.create(event=event, ticket_id=99, first_name="Ancien", last_name="Rembourse")
        items = [{"id": 1, "type": "Registration", "amount": 500, "user": {"firstName": "Léa", "lastName": "M"}},
                 {"id": 2, "type": "Registration", "amount": 500, "user": {"firstName": "Karim", "lastName": "B"}},
                 {"id": 3, "type": "Donation", "amount": 100}]
        with mock.patch.object(helloasso, "form_items", return_value=items):
            self.assertEqual(helloasso.sync_event(event), 2)
        event.refresh_from_db()
        self.assertEqual(event.helloasso_count, 2)
        self.assertEqual(set(HelloAssoTicket.objects.values_list("ticket_id", flat=True)), {1, 2})
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, "2 inscrit·es")  # le compteur suit la campagne, pas seulement « J'y vais »

    @override_settings(HELLOASSO_CLIENT_ID="id", HELLOASSO_CLIENT_SECRET="secret")
    def test_past_campaign_read_once_for_counter_and_report(self):
        link = "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/rando"
        old = Event.objects.create(title="Rando", start_date=in_days(-300), registration_url=link)
        items = [{"id": i, "type": "Registration", "user": {"firstName": f"P{i}", "lastName": "X"}} for i in range(1, 13)]
        with mock.patch.object(helloasso, "form_items", return_value=items) as fetch:
            call_command("sync_helloasso", stdout=io.StringIO())  # sans --all : jamais lue, donc lue
            call_command("sync_helloasso", stdout=io.StringIO())  # déjà lue après la fin : plus rien
        self.assertEqual(fetch.call_count, 1)
        old.refresh_from_db()
        self.assertEqual(old.helloasso_count, 12)
        self.assertFalse(helloasso.needs_sync(old))
        Attendance.objects.create(event=old, user=member("Léa Martin"))
        page = self.client.get(old.get_absolute_url())
        self.assertContains(page, "12 personnes y ont participé")
        self.assertContains(page, "dont 1 membre du site")
        self.assertEqual(len(pdf.participants(old)), 13)  # 12 billets + la membre du site

    @override_settings(HELLOASSO_CLIENT_ID="id", HELLOASSO_CLIENT_SECRET="secret")
    def test_first_visit_of_a_past_event_reads_its_campaign(self):
        link = "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/summer-camp-2026/widget"
        event = Event.objects.create(title="Summer Camp 2026", start_date=in_days(-90), end_date=in_days(-85),
                                     registration_url=link)
        items = [{"id": i, "type": "Registration", "user": {"firstName": "A", "lastName": str(i)}} for i in range(30)]
        with mock.patch.object(helloasso, "form_items", return_value=items) as fetch:
            self.assertContains(self.client.get(event.get_absolute_url()), "30 personnes y ont participé")
            self.client.get(event.get_absolute_url())
        self.assertEqual(fetch.call_count, 1)

    def test_dossier_says_why_helloasso_is_not_read(self):
        from siteconfig.models import SiteConfig

        SiteConfig.objects.update(helloasso_client_id="", helloasso_client_secret="")
        cache.clear()
        event = Event.objects.create(title="Camp", start_date=in_days(-90), registration_url=(
            "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/camp"))
        self.client.force_login(member("Bureau AJC", staff=True))
        self.assertContains(self.client.get(reverse("gestion:dossier", args=[event.pk])), "Identifiants HelloAsso absents")

    @override_settings(HELLOASSO_CLIENT_ID="id", HELLOASSO_CLIENT_SECRET="secret")
    def test_report_syncs_a_campaign_never_read(self):
        link = "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti/evenements/ski"
        event = Event.objects.create(title="Ski", start_date=in_days(-60), registration_url=link)
        self.client.force_login(member("Bureau AJC", staff=True))
        items = [{"id": 5, "type": "Registration", "user": {"firstName": "KARIM", "lastName": "BENALI"}}]
        with mock.patch.object(helloasso, "form_items", return_value=items):
            page = self.client.get(reverse("gestion:dossier", args=[event.pk]))
        self.assertContains(page, "Karim Benali")

    @override_settings(HELLOASSO_CLIENT_ID="id", HELLOASSO_CLIENT_SECRET="secret")
    def test_past_event_finds_its_closed_form(self):
        org = "association-des-jeunes-chercheurs-des-alpes-mariti"
        day = in_days(-200)
        event = Event.objects.create(title="PhD Meet Up : soirée au théâtre", start_date=day)
        community = Event.objects.create(title="Soirée au théâtre", start_date=day, is_community=True)
        upcoming = Event.objects.create(title="Laser game", start_date=in_days(5))
        forms = [{"formType": "Event", "formSlug": "laser-game", "title": "Laser game", "startDate": f"{day}T19:00:00+02:00"},
                 {"formType": "Event", "formSlug": "theatre", "title": "Soirée théâtre", "startDate": f"{day}T20:00:00+02:00"},
                 {"formType": "Event", "formSlug": "laser-game-2", "title": "Laser game",
                  "startDate": f"{in_days(5)}T19:00:00+02:00"}]
        with mock.patch.object(helloasso, "org_forms", return_value=forms), \
                mock.patch.object(helloasso, "form_items", return_value=[{"id": 7, "type": "Registration"}]):
            call_command("sync_helloasso", "--all", stdout=io.StringIO())
        event.refresh_from_db(), community.refresh_from_db(), upcoming.refresh_from_db()
        self.assertEqual(event.registration_url, f"https://www.helloasso.com/associations/{org}/evenements/theatre")
        self.assertEqual(event.helloasso_count, 1)
        self.assertEqual(community.registration_url, "")  # sortie de membre : pas de rapprochement
        self.assertEqual(upcoming.registration_url, "")  # à venir : le lien reste choisi à la main

    def test_past_event_without_members_hides_the_counter(self):
        event = Event.objects.create(title="Rando", start_date=in_days(-30))
        page = self.client.get(event.get_absolute_url())
        self.assertNotContains(page, "membres y vont")
        self.assertNotContains(page, 'id="participants"')
        Attendance.objects.create(event=event, user=member("Léa Martin"))
        self.assertContains(self.client.get(event.get_absolute_url()), "1 membre y est allé·e")


class EffectsTests(TestCase):
    def test_calendar(self):
        self.assertEqual(effects.active(date(2026, 10, 24)), ["trente", "halloween"])
        self.assertEqual(effects.active(date(2027, 1, 1)), ["nouvel-an"])  # les 30 ans sont finis
        self.assertEqual(effects.active(date(2027, 4, 24)), ["anniversaire"])
        self.assertEqual(effects.easter(2027), date(2027, 3, 28))
        self.assertIn("paques", effects.active(date(2027, 3, 29)))
        self.assertEqual(effects.active(date(2027, 2, 10)), [])

    def test_page_carries_effects(self):
        with mock.patch.object(effects, "active", return_value=["noel", "trente"]):
            page = self.client.get("/")
        self.assertContains(page, 'data-effects="noel trente"')
        self.assertContains(page, "effect-trente")

    def test_staff_preview(self):
        staff = member("Bureau AJC", staff=True)
        self.client.force_login(staff)
        with mock.patch.object(effects, "active", return_value=[]):
            self.assertContains(self.client.get("/?effets=halloween,pride"), 'data-effects="halloween pride"')
            self.assertContains(self.client.get("/evenements/"), 'data-effects="halloween pride"')  # garde l'aperçu
            self.assertContains(self.client.get("/?effets=reset"), 'data-effects=""')
        self.client.logout()
        with mock.patch.object(effects, "active", return_value=[]):
            self.assertContains(self.client.get("/?effets=noel"), 'data-effects=""')  # pas pour le public


class AnnouncementTests(TestCase):
    def test_banner_shows_current_announcement(self):
        Announcement.objects.create(message="Inscriptions au Winter Camp ouvertes", link_url="/evenements/",
                                    message_en="Winter Camp registration is open")
        Announcement.objects.create(message="Ancienne", ends_at=timezone.now() - timedelta(days=1))
        page = self.client.get("/")
        self.assertContains(page, "Inscriptions au Winter Camp ouvertes")
        self.assertNotContains(page, "Ancienne")
        self.assertContains(self.client.get("/en/"), "Winter Camp registration is open")

    def test_staff_manage_announcements(self):
        self.client.force_login(member("Bureau AJC", staff=True))
        self.client.post(reverse("gestion:announcements"), {"message": "AG le 28 janvier", "tone": "azur", "is_active": "on"})
        self.assertEqual(Announcement.current().message, "AG le 28 janvier")
