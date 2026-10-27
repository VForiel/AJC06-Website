import io
import shutil
import tempfile
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from blog.models import Post
from core.markdown import render
from core.models import Board, ContactMessage, Member, Resource
from events.ical import calendar
from events.models import Event

MEDIA = tempfile.mkdtemp()


def png(name="affiche.png", size=(1200, 1200)):
    buf = io.BytesIO()
    Image.new("RGB", size, "#1460a6").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def make_event(**kwargs):
    defaults = {"title": "Randonnée à Èze", "start_date": timezone.localdate() + timedelta(days=10),
                "start_time": time(9, 30), "end_time": time(14), "venue": "Gare d'Èze"}
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


@override_settings(MEDIA_ROOT=MEDIA)
class EventModelTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_slug_is_unique(self):
        a, b = make_event(), make_event()
        self.assertEqual(a.slug, "randonnee-a-eze")
        self.assertEqual(b.slug, "randonnee-a-eze-2")

    def test_upcoming_and_past(self):
        today = timezone.localdate()
        future = make_event(title="Futur")
        past = make_event(title="Passé", start_date=today - timedelta(days=3))
        ongoing = make_event(title="Camp", start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
                             start_time=None, end_time=None)
        self.assertEqual(list(Event.objects.upcoming()), [ongoing, future])
        self.assertEqual(list(Event.objects.past()), [past])

    def test_same_end_date_is_dropped(self):
        e = make_event(end_date=timezone.localdate() + timedelta(days=10))
        self.assertIsNone(e.end_date)

    def test_poster_is_converted_to_webp(self):
        e = make_event(poster=png())
        self.assertTrue(e.poster.name.endswith(".webp"))
        with Image.open(e.poster.path) as img:
            self.assertLessEqual(max(img.size), 1600)


class IcalTests(TestCase):
    def test_all_day_event_uses_dates(self):
        e = make_event(start_date=date(2026, 1, 17), end_date=date(2026, 1, 18), start_time=None, end_time=None)
        ics = calendar([e])
        self.assertIn("DTSTART;VALUE=DATE:20260117", ics)
        self.assertIn("DTEND;VALUE=DATE:20260119", ics)  # date de fin exclusive

    def test_timed_event_in_utc(self):
        e = make_event(start_date=date(2026, 6, 12), start_time=time(18, 20), end_time=time(21, 20))
        ics = calendar([e])
        self.assertIn("DTSTART:20260612T162000Z", ics)
        self.assertIn("DTEND:20260612T192000Z", ics)

    def test_lines_are_folded(self):
        e = make_event(body="x" * 400)
        self.assertTrue(all(len(line.encode()) <= 75 for line in calendar([e]).split("\r\n")))


class MarkdownTests(TestCase):
    def test_scripts_are_stripped(self):
        html = render("Salut <script>alert(1)</script> [x](javascript:alert(1))")
        self.assertNotIn("<script", html)
        self.assertNotIn("javascript:", html)

    def test_bare_urls_become_links(self):
        html = render("Inscription : https://www.helloasso.com/evt.")
        self.assertIn('<a href="https://www.helloasso.com/evt"', html)

    def test_h1_is_demoted(self):
        self.assertIn("<h2>Titre</h2>", render("# Titre"))


class PublicPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.event = make_event(registration_url="https://www.helloasso.com/evt")
        cls.hidden = make_event(title="Secret", is_published=False)
        cls.post = Post.objects.create(title="Prix de thèse", body="Texte", status=Post.Status.PUBLISHED,
                                       published_at=timezone.now() - timedelta(days=1), legacy_slug="prix-de-these-cped")
        cls.draft = Post.objects.create(title="Brouillon", body="…")
        Resource.objects.create(title="Financer sa thèse", slug="financer-sa-these", category="doctorat",
                                summary="Bourses", body="## Bourses")
        board = Board.objects.create(year=2025)
        Member.objects.create(board=board, name="Vincent Foriel", role="Trésorier")

    def test_pages_render(self):
        for url in ["/", "/evenements/", "/actu/", "/missions/", "/equipe/", "/ressources/",
                    "/ressources/financer-sa-these/", "/contact/", "/soutenir/", "/mentions-legales/",
                    "/confidentialite/", "/sitemap.xml", "/robots.txt", "/actu/rss/", "/evenements/agenda.ics"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_home_shows_next_event(self):
        response = self.client.get("/")
        self.assertContains(response, "Randonnée à Èze")
        self.assertNotContains(response, "Secret")

    def test_event_detail_has_signup(self):
        response = self.client.get(self.event.get_absolute_url())
        self.assertContains(response, "https://www.helloasso.com/evt")
        self.assertContains(response, "Ajouter à mon agenda")

    def test_unpublished_event_is_hidden(self):
        self.assertEqual(self.client.get(self.hidden.get_absolute_url()).status_code, 404)
        self.assertNotIn("Secret", self.client.get("/evenements/agenda.ics").content.decode())

    def test_draft_post_is_hidden(self):
        self.assertEqual(self.client.get(self.draft.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get("/actu/"), "Brouillon")

    def test_filter_by_kind(self):
        make_event(title="Ski à Auron", types=",plein-air,")
        response = self.client.get("/evenements/?type=plein-air")
        self.assertEqual([e.title for e in response.context["upcoming"]], ["Ski à Auron"])

    def test_whatsapp_is_the_main_call_to_action(self):
        response = self.client.get("/")
        self.assertContains(response, "https://chat.whatsapp.com/C2zmLuCQ0L61vB0wChRbvI")
        self.assertContains(response, "Rejoindre la communauté WhatsApp")

    def test_google_maps_link(self):
        self.assertIn("https://www.google.com/maps/search/?api=1&query=Gare+d%27%C3%88ze", self.event.maps_url)
        self.assertContains(self.client.get(self.event.get_absolute_url()), "Voir sur Google Maps")

    def test_csp_header(self):
        csp = self.client.get("/")["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)


class LegacyRedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.event = make_event(slug="phd-winter-camp-2026", title="Winter camp")
        Post.objects.create(title="Prix", slug="prix-de-these-cped", legacy_slug="prix-de-these-cped",
                            legacy_slug_en="prize-cped", body="x",
                            status=Post.Status.PUBLISHED, published_at=timezone.now() - timedelta(days=1))

    def assertRedirectsTo(self, old, new):
        response = self.client.get(old)
        self.assertEqual(response.status_code, 301, old)
        self.assertEqual(response["Location"], new)

    def test_old_urls(self):
        self.assertRedirectsTo("/events/phd-winter-camp-2026/", "/evenements/phd-winter-camp-2026/")
        self.assertRedirectsTo("/events/inconnu/", "/evenements/")
        self.assertRedirectsTo("/evenement/", "/evenements/")
        self.assertRedirectsTo("/don/", "/soutenir/")
        self.assertRedirectsTo("/prix-de-these-cped/", "/actu/prix-de-these-cped/")
        self.assertRedirectsTo("/politique-de-confidentialite/", "/confidentialite/")
        self.assertRedirectsTo("/en/contact-us/", "/en/contact/")
        self.assertRedirectsTo("/en/prize-cped/", "/en/news/prix-de-these-cped/")
        self.assertRedirectsTo("/en/ajc06-association-of-young-researchers-from-06-alpes-maritimes/", "/en/")

    def test_wix_urls(self):
        self.assertRedirectsTo("/board", "/equipe/")
        self.assertRedirectsTo("/nos-missions", "/missions/")
        self.assertRedirectsTo("/liens-uca", "/ressources/faire-son-doctorat-a-luca/")
        self.assertRedirectsTo("/single-post/2019/02/10/prix-de-these-cped", "/actu/prix-de-these-cped/")
        self.assertRedirectsTo("/single-post/2017/11/23/phd-meet-up", "/actu/")
        self.assertRedirectsTo("/actu/categories/post-doc", "/actu/")

    def test_old_english_pages_still_exist(self):
        for url in ["/en/team/", "/en/our-missions/", "/en/legal-notice/", "/en/privacy-policy/", "/en/news/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_unknown_stays_404(self):
        self.assertEqual(self.client.get("/nimporte-quoi/").status_code, 404)


class ContactTests(TestCase):
    def data(self, **extra):
        data = {"name": "Alex", "email": "alex@example.org", "subject": "rejoindre", "message": "Bonjour", "consent": "on"}
        data.update(extra)
        return data

    def test_message_saved_and_mailed(self):
        response = self.client.post("/contact/", self.data())
        self.assertRedirects(response, "/contact/")
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rejoindre l'équipe", mail.outbox[0].subject)

    def test_honeypot_drops_spam(self):
        self.client.post("/contact/", self.data(website="http://spam.example"))
        self.assertEqual(ContactMessage.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_consent_required(self):
        response = self.client.post("/contact/", self.data(consent=""))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_subject_prefill(self):
        self.assertContains(self.client.get("/contact/?sujet=rejoindre"), 'value="rejoindre" id="id_subject_1" required checked')


@override_settings(MEDIA_ROOT=MEDIA)
class GestionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user("bureau", password="x", is_staff=True)
        cls.member = User.objects.create_user("membre", password="x")

    def test_login_required(self):
        response = self.client.get("/gestion/")
        self.assertRedirects(response, "/gestion/connexion/?next=/gestion/")

    def test_non_staff_forbidden(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get("/gestion/").status_code, 403)

    def test_create_event_with_poster(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse("gestion:event_new"), {
            "title": "Laser game", "type_list": ["meetup"], "start_date": "2030-06-12", "start_time": "18:20",
            "end_time": "21:20", "venue": "Laser Game Evolution", "price": "5 €", "is_published": "on",
            "body": "Inscription : https://www.helloasso.com/laser", "poster": png(),
        })
        self.assertRedirects(response, reverse("gestion:events"))
        event = Event.objects.get()
        self.assertEqual(event.slug, "laser-game")
        self.assertTrue(event.poster.name.endswith(".webp"))
        self.assertContains(self.client.get(event.get_absolute_url()), "Laser Game Evolution")

    def test_invalid_dates_rejected(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse("gestion:event_new"), {
            "title": "Camp", "type_list": ["camp"], "start_date": "2030-06-12", "end_date": "2030-06-10",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La date de fin est avant la date de début.")
        self.assertFalse(Event.objects.exists())

    def test_duplicate_event(self):
        self.client.force_login(self.editor)
        original = make_event(price="Gratuit")
        response = self.client.get(reverse("gestion:event_duplicate", args=[original.pk]))
        self.assertContains(response, 'value="Gratuit"')
        self.assertNotContains(response, f'value="{original.start_date:%Y-%m-%d}"')

    def test_post_scheduled_then_live(self):
        self.client.force_login(self.editor)
        later = (timezone.localtime() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("gestion:post_new"), {"title": "Appel", "status": "published",
                                                       "published_at": later, "body": "Texte"})
        post = Post.objects.get()
        self.assertEqual(post.author, self.editor)
        self.assertFalse(post.is_live)
        self.client.logout()
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)

    def test_preview_and_upload(self):
        self.client.force_login(self.editor)
        preview = self.client.post(reverse("gestion:preview"), {"text": "**gras**"}).json()
        self.assertIn("<strong>gras</strong>", preview["html"])
        upload = self.client.post(reverse("gestion:upload"), {"file": png("photo.png", (2400, 1600))}).json()
        self.assertTrue(upload["url"].endswith(".webp"))
        bad = self.client.post(reverse("gestion:upload"), {"file": SimpleUploadedFile("x.png", b"nope")})
        self.assertEqual(bad.status_code, 400)

    def test_inbox_toggle(self):
        self.client.force_login(self.editor)
        msg = ContactMessage.objects.create(name="A", email="a@example.org", subject="question", message="?")
        self.client.post(reverse("gestion:inbox_toggle", args=[msg.pk]))
        msg.refresh_from_db()
        self.assertTrue(msg.handled)


class EnglishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.translated = make_event(title="Randonnée", title_en="Hike", body="Texte", body_en="Some **text**",
                                    price="Gratuit", price_en="Free")
        cls.french_only = make_event(title="Soirée jeux", body="Seulement en français",
                                     start_date=timezone.localdate() + timedelta(days=20))
        cls.post = Post.objects.create(title="Appel", title_en="Call", body="Texte", body_en="Text",
                                       status=Post.Status.PUBLISHED, published_at=timezone.now() - timedelta(days=1))

    def test_english_urls(self):
        with translation.override("en"):
            self.assertEqual(reverse("events:list"), "/en/events/")
            self.assertEqual(reverse("core:team"), "/en/team/")
            self.assertEqual(self.translated.get_absolute_url(), "/en/events/randonnee/")
        with translation.override("fr"):
            self.assertEqual(reverse("events:list"), "/evenements/")

    def test_pages_render_in_english(self):
        for url in ["/en/", "/en/events/", "/en/news/", "/en/our-missions/", "/en/team/", "/en/resources/",
                    "/en/contact/", "/en/support/", "/en/legal-notice/", "/en/privacy-policy/",
                    "/en/events/agenda.ics", "/en/news/rss/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_interface_is_translated(self):
        response = self.client.get("/en/")
        self.assertContains(response, '<html lang="en"')
        self.assertContains(response, "Join the WhatsApp community")
        self.assertNotContains(response, "Rejoindre la communauté WhatsApp")

    def test_content_uses_english_version(self):
        response = self.client.get("/en/events/randonnee/")
        self.assertContains(response, "Hike")
        self.assertContains(response, "<strong>text</strong>")
        self.assertContains(response, "Free")
        self.assertContains(response, "View on Google Maps")
        self.assertContains(self.client.get("/en/news/"), "Call")

    def test_falls_back_to_french(self):
        response = self.client.get(self.french_only.get_absolute_url().replace("/evenements/", "/en/events/"))
        self.assertContains(response, "Soirée jeux")
        self.assertContains(response, "This description is only available in French.")

    def test_language_switch_points_to_same_page(self):
        response = self.client.get("/equipe/")
        self.assertContains(response, 'href="/en/team/" hreflang="en"')
        self.assertContains(self.client.get("/en/team/"), 'href="/equipe/" hreflang="fr"')

    def test_english_countdown_and_plural(self):
        response = self.client.get("/en/events/")
        self.assertContains(response, "In 10 days")
        self.assertContains(response, "In 20 days")

    def test_english_calendar(self):
        ics = self.client.get("/en/events/agenda.ics").content.decode()
        self.assertIn("SUMMARY:Hike", ics)
        self.assertIn("/en/events/randonnee/", ics)

    def test_gestion_stays_in_french(self):
        editor = User.objects.create_user("bureau", password="x", is_staff=True)
        self.client.force_login(editor)
        response = self.client.get("/gestion/evenements/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, "Nouvel événement")
        self.assertContains(response, "Version anglaise", count=0)
        self.assertContains(self.client.get(reverse("gestion:event_edit", args=[self.translated.pk])), "Version anglaise")
