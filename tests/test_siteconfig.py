from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from community import confirmation
from projets import helloasso
from siteconfig.mail import ConfigEmailBackend, backend_for
from siteconfig.models import ConfigChange, SiteConfig

User = get_user_model()


class InitialValuesTests(TestCase):
    @override_settings(ENV_EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="mail.ajc06.com",
                       EMAIL_PORT=465, EMAIL_USE_SSL=True, EMAIL_USE_TLS=False, EMAIL_HOST_USER="contact@ajc06.com",
                       EMAIL_HOST_PASSWORD="pw", ACCOUNT_VALIDATION="bureau", HELLOASSO_CLIENT_ID="id",
                       HELLOASSO_CLIENT_SECRET="secret", CONTACT_EMAIL="bureau@ajc06.com")
    def test_former_env_values_are_carried_over(self):
        config = SiteConfig.get()
        self.assertEqual((config.smtp_host, config.smtp_port, config.smtp_security), ("mail.ajc06.com", 465, "ssl"))
        self.assertEqual((config.smtp_user, config.smtp_password), ("contact@ajc06.com", "pw"))
        self.assertEqual(config.contact_email, "bureau@ajc06.com")
        self.assertEqual(confirmation.mode(), "bureau")
        self.assertTrue(helloasso.configured())

    @override_settings(ENV_EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", EMAIL_HOST="mail.ajc06.com")
    def test_console_backend_in_env_means_no_smtp(self):
        self.assertEqual(SiteConfig.get().smtp_host, "")

    def test_secrets_encrypted_at_rest(self):
        config = SiteConfig.get()
        config.smtp_password, config.helloasso_client_secret = "smtp-secret", "ha-secret"
        config.save()
        with connection.cursor() as cursor:
            cursor.execute("SELECT smtp_password, helloasso_client_secret FROM siteconfig_siteconfig WHERE id = 1")
            raw = " ".join(cursor.fetchone())
        self.assertNotIn("smtp-secret", raw)
        self.assertNotIn("ha-secret", raw)
        config = SiteConfig.get()
        self.assertEqual((config.smtp_password, config.helloasso_client_secret), ("smtp-secret", "ha-secret"))


class MailBackendTests(TestCase):
    def test_console_until_smtp_is_set(self):
        self.assertIsInstance(backend_for(SiteConfig.get()), ConsoleBackend)

    def test_smtp_from_database_and_sender_replaced(self):
        config = SiteConfig.get()
        config.smtp_host, config.smtp_port, config.smtp_security = "mail.ajc06.com", 587, "starttls"
        config.from_email = "AJC06 <contact@ajc06.com>"
        config.save()
        backend = backend_for(SiteConfig.get())
        self.assertIsInstance(backend, SMTPBackend)
        self.assertTrue(backend.use_tls)
        wrapper = ConfigEmailBackend()
        sent = []
        wrapper.inner.send_messages = lambda msgs: sent.extend(msgs) or len(msgs)
        wrapper.send_messages([EmailMessage("a", "b", settings.DEFAULT_FROM_EMAIL, ["x@example.org"])])
        self.assertEqual(sent[0].from_email, "AJC06 <contact@ajc06.com>")


class SettingsPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("vincent", "v@example.org", "pw")
        self.staff = User.objects.create_user("bureau", "b@example.org", "pw", is_staff=True)

    def data(self, **overrides):
        values = {"smtp_host": "mail.ajc06.com", "smtp_port": 465, "smtp_security": "ssl", "smtp_user": "contact@ajc06.com",
                  "smtp_password": "", "from_email": "AJC06 <contact@ajc06.com>", "contact_email": "contact@ajc06.com",
                  "account_validation": "bureau", "helloasso_client_id": "id", "helloasso_client_secret": "",
                  "helloasso_organization": "association-des-jeunes-chercheurs-des-alpes-mariti", "legal_host": "o2switch",
                  "meta_api_version": "v24.0", "email_diffusion_enabled": "on"}
        values.update(overrides)
        return values

    def test_only_superusers(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("gestion:settings")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("gestion:dashboard")), "Réglages du site")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("gestion:settings")).status_code, 200)

    def test_save_keep_and_clear_secrets(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("gestion:settings"), self.data(smtp_password="s1", helloasso_client_secret="h1"))
        self.client.post(reverse("gestion:settings"), self.data(account_validation="courriel"))
        config = SiteConfig.get()
        self.assertEqual((config.smtp_password, config.helloasso_client_secret), ("s1", "h1"))
        self.assertEqual(confirmation.mode(), "courriel")
        page = self.client.get(reverse("gestion:settings")).content.decode()
        self.assertNotIn("s1\"", page)
        self.assertNotIn("h1\"", page)
        self.client.post(reverse("gestion:settings"), self.data(account_validation="courriel", clear_helloasso_client_secret="on"))
        self.assertEqual(SiteConfig.get().helloasso_client_secret, "")
        self.assertEqual(ConfigChange.objects.count(), 3)

    def test_contact_and_legal_come_from_settings(self):
        config = SiteConfig.get()
        config.contact_email, config.legal_host = "ecrire@ajc06.com", "Hébergeur de test"
        config.save()
        self.assertContains(self.client.get(reverse("core:contact")), "ecrire@ajc06.com")
        self.assertContains(self.client.get(reverse("core:legal")), "Hébergeur de test")

    def test_test_email_without_smtp(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("gestion:test_email"), {"to": "v@example.org"}, follow=True)
        self.assertContains(response, "Aucun serveur SMTP")
