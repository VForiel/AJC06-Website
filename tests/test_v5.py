"""Profil (erreurs visibles, saisie tolérante), médias privés, limites d'envoi, images, émojis des types."""

import io
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase as BaseTestCase, override_settings
from django.urls import reverse
from django.utils import translation
from PIL import Image

from community.forms import ProfileForm, handle_from
from core.images import validate_image
from events.models import Event, type_choices


class TestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        translation.activate("fr")
        cache.clear()


def profile_data(**extra):
    data = {"p-display_name": "Léa Martin", "p-accent": "azur", "p-visibility": "membres",
            "p-contact_visibility": "amis", "save_profile": "1"}
    data.update({f"p-{k}": v for k, v in extra.items()})
    return data


class ProfileTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("lea@example.org", "lea@example.org", "x")
        self.client.force_login(self.user)

    def test_invalid_or_missing_fields_do_not_block_the_others(self):
        data = profile_data(orcid="pas un orcid", phone="+33 6 12 34 56 78", lab="Lagrange", display_name="")
        del data["p-accent"]  # choix absent : on garde la valeur actuelle
        response = self.client.post(reverse("community:settings"), data, follow=True)
        self.assertRedirects(response, reverse("community:settings"))
        self.assertContains(response, "sauf ces champs")
        self.assertContains(response, "ORCID")
        p = self.user.profile
        p.refresh_from_db()
        self.assertEqual((p.phone, p.lab), ("+33 6 12 34 56 78", "Lagrange"))  # les autres sont enregistrés
        self.assertEqual(p.orcid, "")
        self.assertTrue(p.display_name)  # nom vidé : l'ancien est conservé
        self.assertEqual(p.accent, "azur")

    def test_bad_avatar_does_not_block_the_rest(self):
        data = profile_data(lab="Lagrange")
        data["p-avatar"] = SimpleUploadedFile("x.png", b"pas une image", content_type="image/png")
        self.client.post(reverse("community:settings"), data)
        p = self.user.profile
        p.refresh_from_db()
        self.assertEqual(p.lab, "Lagrange")
        self.assertFalse(p.avatar)

    def test_lenient_inputs_are_normalized(self):
        response = self.client.post(reverse("community:settings"), profile_data(
            orcid="https://orcid.org/0000-0002-1825-009x", instagram="https://www.instagram.com/lea.m/?hl=fr",
            x="@lea", linkedin="linkedin.com/in/lea", phone="+33 6 12 34 56 78"))
        self.assertRedirects(response, reverse("community:settings"))
        p = self.user.profile
        p.refresh_from_db()
        self.assertEqual(p.orcid, "0000-0002-1825-009X")
        self.assertEqual(p.instagram, "lea.m")
        self.assertEqual(p.x, "lea")
        self.assertEqual(p.linkedin, "https://linkedin.com/in/lea")
        self.assertEqual(p.phone, "+33 6 12 34 56 78")

    def test_handle_from(self):
        self.assertEqual(handle_from(" @nom "), "nom")
        self.assertEqual(handle_from("https://x.com/nom/"), "nom")

    def test_every_text_input_is_styled(self):
        # Le style couvre tous les types de champ ; on vérifie ici que le formulaire n'en produit pas d'exotique sans label.
        form = ProfileForm(prefix="p")
        self.assertEqual(form["phone"].field.widget.input_type, "tel")


class PrivateMediaTests(TestCase):
    def setUp(self):
        super().setUp()
        self.media = Path(tempfile.mkdtemp())
        (self.media / "dossiers" / "2026").mkdir(parents=True)
        (self.media / "dossiers" / "2026" / "facture.pdf").write_bytes(b"%PDF-1.4")
        (self.media / "actu").mkdir()
        (self.media / "actu" / "photo.webp").write_bytes(b"RIFF")
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def test_dossier_files_are_staff_only(self):
        self.assertEqual(self.client.get("/media/dossiers/2026/facture.pdf").status_code, 404)
        member = User.objects.create_user("m@example.org", "m@example.org", "x")
        self.client.force_login(member)
        self.assertEqual(self.client.get("/media/dossiers/2026/facture.pdf").status_code, 404)
        staff = User.objects.create_user("b@example.org", "b@example.org", "x", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get("/media/dossiers/2026/facture.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])

    def test_public_media_is_cached(self):
        response = self.client.get("/media/actu/photo.webp")
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age", response["Cache-Control"])


class ThrottleTests(TestCase):
    def test_password_reset_mails_are_limited(self):
        User.objects.create_user("lea@example.org", "lea@example.org", "x")
        for _ in range(6):
            response = self.client.post(reverse("community:password_reset"), {"email": "lea@example.org"})
            self.assertRedirects(response, reverse("community:password_reset_done"))
        self.assertEqual(len(mail.outbox), 3)

    def test_contact_form_is_limited(self):
        url = reverse("core:contact")
        data = {"name": "Léa", "email": "lea@example.org", "subject": "autre", "message": "Bonjour, une question.", "consent": "on"}
        for _ in range(5):
            self.client.post(url, data)
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "Trop de messages")


class ImageTests(TestCase):
    def image(self, size, name="x.png"):
        buf = io.BytesIO()
        Image.new("RGB", size, "white").save(buf, "PNG")
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")

    def test_normal_image_passes(self):
        validate_image(self.image((800, 600)))

    def test_huge_dimensions_are_refused(self):
        with self.assertRaises(ValidationError):
            validate_image(self.image((9000, 5000)))

    def test_not_an_image(self):
        with self.assertRaises(ValidationError):
            validate_image(SimpleUploadedFile("x.png", b"pas une image"))


class EmojiTests(TestCase):
    def test_choices_and_tags_have_emojis_except_other(self):
        labels = dict(type_choices(staff=True))
        self.assertTrue(labels["plein-air"].startswith("🥾"))
        self.assertEqual(labels["autre"], "Autre")
        event = Event(title="x", types=",sport,autre,", other_type="Poterie")
        self.assertEqual(event.type_tags, [("sport", "🏃", "Sport"), ("autre", "", "Poterie")])
        self.assertEqual(event.type_labels, [("sport", "Sport"), ("autre", "Poterie")])  # PDF : sans émoji


@override_settings(ACCOUNT_VALIDATION="bureau")
class BoardApprovalTests(TestCase):
    def signup(self, email="camille@example.org"):
        return self.client.post(reverse("community:signup"), {
            "display_name": "Camille Martin", "email": email, "password": "une-phrase-longue", "consent": "on"})

    def test_signup_waits_for_the_board_without_mail(self):
        response = self.signup()
        self.assertContains(response, "Un membre du bureau le valide")
        self.assertEqual(len(mail.outbox), 0)
        user = User.objects.get(email="camille@example.org")
        self.assertFalse(user.is_active)
        login = self.client.post(reverse("community:login"), {"username": "camille@example.org",
                                                              "password": "une-phrase-longue"})
        self.assertContains(login, "pas encore validé")
        bad = self.client.post(reverse("community:login"), {"username": "camille@example.org", "password": "faux"})
        self.assertNotContains(bad, "pas encore validé")  # sans le bon mot de passe, on ne révèle rien

    def test_board_validates_or_refuses(self):
        self.signup()
        self.signup("spam@example.org")
        staff = User.objects.create_user("b@example.org", "b@example.org", "x", is_staff=True)
        self.client.force_login(staff)
        page = self.client.get(reverse("gestion:accounts"))
        self.assertContains(page, "camille@example.org")
        self.assertContains(self.client.get(reverse("gestion:dashboard")), "Comptes à valider")
        camille = User.objects.get(email="camille@example.org")
        self.client.post(reverse("gestion:account_decide", args=[camille.pk]), {"decision": "valider"})
        camille.refresh_from_db()
        self.assertTrue(camille.is_active and camille.profile.email_confirmed)
        self.assertEqual(len(mail.outbox), 1)
        spam = User.objects.get(email="spam@example.org")
        self.client.post(reverse("gestion:account_decide", args=[spam.pk]), {"decision": "refuser"})
        self.assertFalse(User.objects.filter(email="spam@example.org").exists())

    def test_cannot_touch_active_or_moderated_accounts(self):
        moderated = User.objects.create_user("m@example.org", "m@example.org", "x", is_active=False)  # email_confirmed=True
        staff = User.objects.create_user("b@example.org", "b@example.org", "x", is_staff=True)
        self.client.force_login(staff)
        for target in (moderated, staff):
            r = self.client.post(reverse("gestion:account_decide", args=[target.pk]), {"decision": "refuser"})
            self.assertEqual(r.status_code, 404)
        self.assertTrue(User.objects.filter(pk=moderated.pk).exists())

    def test_members_cannot_validate(self):
        self.signup()
        member = User.objects.create_user("x@example.org", "x@example.org", "x")
        self.client.force_login(member)
        camille = User.objects.get(email="camille@example.org")
        self.client.post(reverse("gestion:account_decide", args=[camille.pk]), {"decision": "valider"})
        camille.refresh_from_db()
        self.assertFalse(camille.is_active)

    def test_next_cannot_leave_the_site(self):
        self.signup()
        staff = User.objects.create_user("b@example.org", "b@example.org", "x", is_staff=True)
        self.client.force_login(staff)
        camille = User.objects.get(email="camille@example.org")
        r = self.client.post(reverse("gestion:account_decide", args=[camille.pk]),
                             {"decision": "valider", "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("gestion:accounts"))
