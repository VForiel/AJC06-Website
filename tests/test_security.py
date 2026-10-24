"""Blocage des essais de mots de passe, confirmation de l'adresse à l'inscription, sauvegardes."""

import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase as BaseTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import translation

from community.confirmation import link
from core.models import Ban, LoginFailure


class TestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("fr")
        cache.clear()


class BanTests(TestCase):
    def setUp(self):
        super().setUp()
        User.objects.create_user("lea@example.org", "lea@example.org", "bon-mot-de-passe")

    def fail(self, url_name="community:login", username="lea@example.org", ip="203.0.113.7"):
        return self.client.post(reverse(url_name), {"username": username, "password": "faux"}, REMOTE_ADDR=ip)

    def test_five_failures_ban_the_ip(self):
        for _ in range(4):
            self.fail()
        self.assertFalse(Ban.objects.exists())
        self.assertEqual(self.client.get("/", REMOTE_ADDR="203.0.113.7").status_code, 200)
        self.fail()
        self.assertTrue(Ban.objects.filter(ip="203.0.113.7").exists())
        self.assertEqual(self.client.get("/", REMOTE_ADDR="203.0.113.7").status_code, 403)
        self.assertEqual(self.client.get("/", REMOTE_ADDR="198.51.100.2").status_code, 200)  # les autres passent

    def test_admin_username_is_banned_at_once(self):
        self.fail(url_name="gestion:login", username="admin")
        ban = Ban.objects.get(ip="203.0.113.7")
        self.assertIn("admin", ban.reason)
        self.assertEqual(self.client.get("/", REMOTE_ADDR="203.0.113.7").status_code, 403)

    def test_django_admin_login_is_covered(self):
        self.client.post("/admin/login/", {"username": "Admin", "password": "x"}, REMOTE_ADDR="203.0.113.9")
        self.assertTrue(Ban.objects.filter(ip="203.0.113.9").exists())

    def test_success_clears_failures(self):
        for _ in range(3):
            self.fail()
        self.client.post(reverse("community:login"), {"username": "lea@example.org", "password": "bon-mot-de-passe"},
                         REMOTE_ADDR="203.0.113.7")
        self.assertFalse(LoginFailure.objects.filter(ip="203.0.113.7").exists())

    def test_forwarded_header_ignored_unless_trusted(self):
        for _ in range(5):
            self.client.post(reverse("community:login"), {"username": "x@example.org", "password": "x"},
                             REMOTE_ADDR="203.0.113.7", HTTP_X_FORWARDED_FOR="192.0.2.50")
        self.assertTrue(Ban.objects.filter(ip="203.0.113.7").exists())
        self.assertFalse(Ban.objects.filter(ip="192.0.2.50").exists())

    @override_settings(TRUST_X_FORWARDED_FOR=True)
    def test_forwarded_header_behind_proxy(self):
        self.client.post(reverse("community:login"), {"username": "admin", "password": "x"},
                         REMOTE_ADDR="172.20.0.4", HTTP_X_FORWARDED_FOR="192.0.2.50, 172.20.0.4")
        self.assertTrue(Ban.objects.filter(ip="192.0.2.50").exists())


@override_settings(ACCOUNT_EMAIL_CONFIRMATION=True)
class ConfirmationTests(TestCase):
    def signup(self, email="camille@example.org"):
        return self.client.post(reverse("community:signup"), {
            "display_name": "Camille Martin", "email": email, "password": "une-phrase-longue", "consent": "on"})

    def test_signup_sends_link_and_account_stays_inactive(self):
        response = self.signup()
        self.assertContains(response, "Regarde ta boîte mail")
        user = User.objects.get(email="camille@example.org")
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_confirmed)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/compte/confirmer/", mail.outbox[0].body)
        self.assertNotIn("_auth_user_id", self.client.session)
        login = self.client.post(reverse("community:login"), {"username": "camille@example.org", "password": "une-phrase-longue"})
        self.assertEqual(login.status_code, 200)  # pas de connexion avant confirmation

    def test_link_activates_once(self):
        self.signup()
        user = User.objects.get(email="camille@example.org")
        url = link(user).split("://", 1)[1].split("/", 1)[1]
        response = self.client.get("/" + url)
        self.assertRedirects(response, reverse("community:settings"))
        user.refresh_from_db()
        self.assertTrue(user.is_active and user.profile.email_confirmed)
        self.client.logout()
        self.assertRedirects(self.client.get("/" + url), reverse("community:login"))  # lien déjà utilisé

    def test_resend_does_not_reveal_accounts(self):
        self.signup()
        mail.outbox.clear()
        a = self.client.post(reverse("community:confirm_resend"), {"email": "camille@example.org"})
        b = self.client.post(reverse("community:confirm_resend"), {"email": "inconnu@example.org"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(a.status_code, b.status_code)

    def test_moderated_account_cannot_reactivate(self):
        user = User.objects.create_user("x@example.org", "x@example.org", "x", is_active=False)  # désactivé par le bureau
        url = link(user).split("://", 1)[1].split("/", 1)[1]
        self.client.get("/" + url)
        user.refresh_from_db()
        self.assertFalse(user.is_active)


class BackupTests(TransactionTestCase):
    """Sans transaction englobante : la copie SQLite attendrait sinon la fin de la transaction du test."""

    def test_backup_creates_readable_archives(self):
        target = Path(tempfile.mkdtemp())
        media = Path(tempfile.mkdtemp())
        (media / "photo.txt").write_text("x")
        try:
            with override_settings(BACKUP_DIR=target, MEDIA_ROOT=media):
                User.objects.create_user("x@example.org", "x@example.org", "x")
                call_command("backup_site", "--media", stdout=open(target / "out.txt", "w"))
            dumps = list(target.glob("db-*.sqlite3.gz"))
            self.assertEqual(len(dumps), 1)
            self.assertTrue(list(target.glob("media-*.tar.gz")))
            raw = target / "check.sqlite3"
            raw.write_bytes(gzip.decompress(dumps[0].read_bytes()))
            tables = {r[0] for r in sqlite3.connect(raw).execute("select name from sqlite_master where type='table'")}
            self.assertIn("auth_user", tables)
        finally:
            shutil.rmtree(target, ignore_errors=True)
            shutil.rmtree(media, ignore_errors=True)
