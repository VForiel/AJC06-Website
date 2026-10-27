"""Diffusion des événements (Instagram, Facebook, courriel), partage, commentaires, médias multiples, événements passés."""

import io
import json
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase as BaseTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from community.models import Attendance, Comment, Friendship, Photo, Profile, Report
from events.models import Event
from siteconfig.models import SiteConfig
from social.models import Post
from social.service import send_due
from social.visuals import FORMATS, render

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
    Profile.objects.get(user=user).save()
    user.profile.refresh_from_db()
    return user


def jpeg(name="affiche.jpg", size=(600, 850)):
    buf = io.BytesIO()
    Image.new("RGB", size, "#3894c0").save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def mp4(name="clip.mp4"):
    return SimpleUploadedFile(name, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000, content_type="video/mp4")


def in_days(n):
    return timezone.localdate() + timedelta(days=n)


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@override_settings(MEDIA_ROOT=MEDIA, SITE_URL="https://beta.ajc06.com")
class DiffusionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.staff = member("Camille Bureau", staff=True)
        self.event = Event.objects.create(title="PhD meet-up 🎉 de rentrée", types=",meetup,", start_date=in_days(10),
                                          venue="Bar des Oiseaux", price="Gratuit", summary="On fait connaissance.",
                                          registration_url="https://www.helloasso.com/x")
        config = SiteConfig.get()
        config.smtp_host, config.diffusion_emails = "smtp.example.org", "doctorants@example.org\nautre@example.org"
        config.facebook_enabled, config.facebook_page_id, config.facebook_page_token = True, "123", "jeton"
        config.instagram_enabled, config.instagram_user_id = True, "456"
        config.save()

    def test_visuals_with_and_without_poster(self):
        for fmt, size in FORMATS.items():
            self.assertEqual(render(self.event, fmt).size, size)
        self.event.poster = jpeg()
        self.event.save()
        for fmt, size in FORMATS.items():
            self.assertEqual(render(self.event, fmt).size, size)
        response = self.client.get(reverse("events:visual", args=[self.event.slug, "story"]) + "?telecharger=1")
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_members_cannot_diffuse(self):
        self.client.force_login(member("Alice Durand"))
        self.assertEqual(self.client.get(reverse("gestion:diffuse", args=[self.event.pk])).status_code, 403)

    def test_form_is_prefilled(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("gestion:diffuse", args=[self.event.pk]))
        self.assertContains(page, "Bar des Oiseaux")
        self.assertContains(page, "lien en bio")
        self.assertContains(page, "doctorants@example.org")
        self.assertContains(page, "/media/visuels/")
        self.assertRegex(page.content.decode(), r'name="language" value="fr"[^>]*checked')  # sans version anglaise

    def test_languages(self):
        from social.texts import SEPARATOR, default_subject, default_text

        self.event.title_en, self.event.summary_en = "Back-to-school PhD meet-up", "Let's meet."
        self.event.save()
        en = default_text(self.event, "facebook", language="en")
        self.assertIn("Back-to-school PhD meet-up", en)
        self.assertIn("/en/", en)
        self.assertNotIn("Inscription", en)
        both = default_text(self.event, "instagram", "#AJC06", language="both")
        self.assertIn(SEPARATOR.strip(), both)
        self.assertLess(both.index("On fait connaissance."), both.index("Let's meet."))
        self.assertTrue(both.endswith("#AJC06"))
        self.assertLessEqual(len(both), 2200)
        self.assertIn(" / ", default_subject(self.event, "both"))
        self.client.force_login(self.staff)
        page = self.client.get(reverse("gestion:diffuse", args=[self.event.pk]))
        self.assertRegex(page.content.decode(), r'name="language" value="both"[^>]*checked')  # bilingue par défaut
        self.assertContains(page, 'id="diffusion-prefills"')
        self.client.post(reverse("gestion:diffuse", args=[self.event.pk]), {
            "on_email": "on", "text_email": en, "subject": "Meet-up", "recipients": "a@example.org", "when": "now",
            "language": "en"})
        post = Post.objects.get()
        self.assertEqual((post.language, post.status), ("en", Post.Status.PUBLISHED))
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("See the event", html)
        self.assertIn("/media/visuels/", html)
        self.assertIn("/en-og-", html)  # visuel anglais

    def test_email_now_in_bcc_with_visual(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:diffuse", args=[self.event.pk]), {
            "on_email": "on", "text_email": "Bonjour à toutes et à tous", "subject": "Meet-up",
            "recipients": "a@example.org\nb@example.org", "when": "now", "language": "fr"})
        post = Post.objects.get()
        self.assertEqual(post.status, Post.Status.PUBLISHED, post.error)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, "Meet-up")
        self.assertEqual(message.bcc, ["a@example.org", "b@example.org"])
        self.assertEqual(message.attachments[0][2], "image/jpeg")
        self.assertIn("https://beta.ajc06.com/media/visuels/", message.alternatives[0][0])

    def test_invalid_recipient_refused(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:diffuse", args=[self.event.pk]), {
            "on_email": "on", "text_email": "Salut", "subject": "x", "recipients": "pas-une-adresse", "when": "now", "language": "fr"})
        self.assertFalse(Post.objects.exists())

    def test_scheduled_posts_go_out_when_due(self):
        self.client.force_login(self.staff)
        later = timezone.localtime() + timedelta(hours=2)
        self.client.post(reverse("gestion:diffuse", args=[self.event.pk]), {
            "on_instagram": "on", "text_instagram": "Insta", "on_facebook": "on", "text_facebook": "Facebook",
            "language": "fr", "when": "later", "scheduled_at": later.strftime("%Y-%m-%dT%H:%M")})
        self.assertEqual(Post.objects.filter(status=Post.Status.SCHEDULED).count(), 2)
        self.assertEqual(send_due(), "Rien à diffuser")
        Post.objects.update(scheduled_at=timezone.now() - timedelta(minutes=1))
        calls = []

        def fake(request, timeout=0):
            calls.append(request)
            url = request.full_url
            if url.endswith("/123/photos"):
                return FakeResponse({"post_id": "123_9"})
            if url.endswith("/456/media"):
                return FakeResponse({"id": "c1"})
            if "/c1?" in url:
                return FakeResponse({"status_code": "FINISHED"})
            if url.endswith("/media_publish"):
                return FakeResponse({"id": "m1"})
            return FakeResponse({"permalink": "https://instagram.com/p/x"})

        with mock.patch("social.networks.urllib.request.urlopen", fake):
            send_due()
        statuses = dict(Post.objects.values_list("network", "status"))
        self.assertEqual(statuses, {"instagram": "published", "facebook": "published"})
        sent = next(c for c in calls if c.full_url.endswith("/456/media")).data.decode()
        self.assertIn("beta.ajc06.com%2Fmedia%2Fvisuels%2F", sent)
        self.assertEqual(Post.objects.get(network="instagram").external_url, "https://instagram.com/p/x")
        self.assertEqual(Post.objects.get(network="facebook").external_url, "https://www.facebook.com/123_9")

    def test_network_error_is_retried_then_fails(self):
        post = Post.objects.create(event=self.event, network="facebook", text="x", scheduled_at=timezone.now())
        import urllib.error

        with mock.patch("social.networks.urllib.request.urlopen", side_effect=urllib.error.URLError("hors ligne")):
            send_due()
        post.refresh_from_db()
        self.assertEqual(post.status, Post.Status.SCHEDULED)  # retentée plus tard
        self.assertIn("hors ligne", post.error)

    def test_unconfigured_channel_is_disabled(self):
        config = SiteConfig.get()
        config.facebook_enabled = False
        config.save()
        self.client.force_login(self.staff)
        self.client.post(reverse("gestion:diffuse", args=[self.event.pk]), {
            "on_facebook": "on", "text_facebook": "x", "when": "now", "language": "fr"})
        self.assertFalse(Post.objects.exists())

    def test_robots_kick_sends_due_posts(self):
        Post.objects.create(event=self.event, network="email", text="x", subject="s", recipients="a@example.org",
                            scheduled_at=timezone.now() - timedelta(minutes=1))
        with mock.patch("social.service.threading.Thread") as thread:
            self.client.get("/robots.txt")
        thread.assert_called_once()

    def test_share_block_for_visitors(self):
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, "Fais tourner")
        self.assertContains(page, "https://wa.me/?text=")
        self.assertContains(page, reverse("events:visual", args=[self.event.slug, "story"]))


@override_settings(MEDIA_ROOT=MEDIA)
class CommentAndMediaTests(TestCase):
    def setUp(self):
        super().setUp()
        self.alice = member("Alice Durand")
        self.event = Event.objects.create(title="Rando", types=",plein-air,", start_date=in_days(-2))

    def test_comment_names_hidden_from_visitors(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("community:comment_new", args=[self.event.slug]), {"body": "Super journée !"})
        self.assertEqual(Comment.objects.get().body, "Super journée !")
        self.client.logout()
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, "Super journée !")
        self.assertNotContains(page, "Alice Durand")

    def test_three_reports_hide_comment(self):
        comment = Comment.objects.create(event=self.event, author=self.alice, body="Pub")
        for name in ("Bob Un", "Chloé Deux", "Dan Trois"):
            self.client.force_login(member(name))
            self.client.post(reverse("community:report", args=["commentaire", comment.pk]), {"reason": "spam"})
        comment.refresh_from_db()
        self.assertTrue(comment.is_hidden)
        self.assertEqual(Report.objects.filter(comment=comment).count(), 3)

    def test_several_photos_videos_and_links(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("community:photo_new"), {
            "files": [jpeg("a.jpg"), jpeg("b.jpg"), mp4()], "links": "https://youtu.be/dQw4w9WgXcQ\npin.it/abc",
            "event": self.event.pk, "consent": "on"})
        self.assertEqual(Photo.objects.filter(kind="photo").count(), 2)
        self.assertEqual(Photo.objects.filter(kind="video").count(), 1)
        self.assertEqual(Photo.objects.filter(kind="lien").count(), 2)
        page = self.client.get(self.event.get_absolute_url())
        self.assertContains(page, "Pinterest")
        video = Photo.objects.get(kind="video")
        youtube = Photo.objects.get(url__contains="youtu")
        self.assertContains(self.client.get(youtube.get_absolute_url()), "youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertEqual(self.client.get(video.video.url, HTTP_RANGE="bytes=0-9").status_code, 206)
        self.assertContains(self.client.get(reverse("community:photos")), "media-tile-video")

    def test_heavy_or_unreadable_file_suggests_link(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("community:photo_new"), {
            "files": [SimpleUploadedFile("x.heic", b"pas une image")], "consent": "on"})
        self.assertContains(response, "Google Photos")
        self.assertFalse(Photo.objects.exists())


class PastEventsTests(TestCase):
    def test_visibility_setting(self):
        alice, bob = member("Alice Durand"), member("Bob Martin")
        past = Event.objects.create(title="Soirée jeux passée", types=",soiree,", start_date=in_days(-10))
        Attendance.objects.create(event=past, user=bob)
        url = bob.profile.get_absolute_url()
        self.client.force_login(alice)
        self.assertContains(self.client.get(url), "Soirée jeux passée")
        Profile.objects.filter(user=bob).update(past_events="amis")
        self.assertNotContains(self.client.get(url), "Soirée jeux passée")
        Friendship.objects.create(from_user=alice, to_user=bob, accepted=True)
        self.assertContains(self.client.get(url), "Soirée jeux passée")
        Profile.objects.filter(user=bob).update(past_events="moi")
        self.assertNotContains(self.client.get(url), "Soirée jeux passée")
        self.client.force_login(bob)
        self.assertContains(self.client.get(url), "Soirée jeux passée")
