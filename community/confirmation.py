"""Validation des nouveaux comptes.

Trois modes (réglage ACCOUNT_VALIDATION) :
- « aucune » : le compte est actif tout de suite ;
- « courriel » : un lien signé (usage unique, 3 jours) est envoyé ; le bureau peut aussi valider à la main ;
- « bureau » : le compte attend qu'un membre du bureau le valide dans /gestion/comptes/ (sans serveur mail).

Un compte en attente : is_active=False et profile.email_confirmed=False (un compte désactivé par le bureau, lui,
garde email_confirmed=True et n'apparaît pas dans la liste).
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

log = logging.getLogger(__name__)


class ConfirmationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "community.confirmation"

    def _make_hash_value(self, user, timestamp):
        # L'état d'activation fait partie du jeton : une fois le compte confirmé, le lien ne sert plus.
        return f"{user.pk}{user.is_active}{user.email}{timestamp}"


tokens = ConfirmationTokenGenerator()


MODES = ("aucune", "courriel", "bureau")


def mode():
    value = getattr(settings, "ACCOUNT_VALIDATION", "")
    if value in MODES:
        return value
    return "courriel" if getattr(settings, "ACCOUNT_EMAIL_CONFIRMATION", False) else "aucune"  # ancien réglage


def required():
    return mode() != "aucune"


def pending():
    return get_user_model().objects.filter(is_active=False, profile__email_confirmed=False)


def approve(user):
    """Active un compte en attente (lien ouvert ou validation par le bureau). Faux si le compte n'était pas en attente."""
    if user.is_active or user.profile.email_confirmed:
        return False
    user.is_active = True
    user.save(update_fields=["is_active"])
    user.profile.email_confirmed = True
    user.profile.save(update_fields=["email_confirmed"])
    return True


def send_approved(user):
    """Prévient la personne que le bureau a validé son compte (sans effet tant qu'il n'y a pas de serveur mail)."""
    context = {"name": user.profile.display_name, "link": settings.SITE_URL + reverse("community:login")}
    try:
        send_mail(_("AJC06 : ton compte est validé"), render_to_string("community/approved_email.txt", context),
                  settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception:
        log.exception("Courriel de validation non envoyé à l'utilisateur %s", user.pk)


def link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return settings.SITE_URL + reverse("community:confirm", args=[uid, tokens.make_token(user)])


def send(user):
    context = {"name": user.profile.display_name, "link": link(user)}
    try:
        send_mail(
            _("AJC06 : confirme ton adresse"),
            render_to_string("community/confirm_email.txt", context),
            settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
        )
        return True
    except Exception:
        log.exception("Courriel de confirmation non envoyé à l'utilisateur %s", user.pk)
        return False
