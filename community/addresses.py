"""Adresses e-mail des membres : ajout, lien de confirmation (signé, 3 jours), adresse principale.

Une adresse confirmée n'appartient qu'à un compte. Elle sert à reconnaître les billets HelloAsso du membre.
"""

import logging

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _

from .models import EmailAddress

log = logging.getLogger(__name__)

SALT = "community.address"
MAX_AGE = 3 * 24 * 3600
MAX_PER_USER = 6


def normalize(email):
    return (email or "").strip().lower()


def taken(email, user):
    """Vrai si l'adresse est déjà confirmée par un autre compte, ou est l'adresse de connexion d'un autre compte."""
    from django.contrib.auth import get_user_model

    email = normalize(email)
    return (EmailAddress.objects.filter(email=email, confirmed=True).exclude(user=user).exists()
            or get_user_model().objects.filter(email__iexact=email).exclude(pk=user.pk).exists())


def ensure_primary(user):
    """L'adresse du compte figure parmi ses adresses (non confirmée si elle est nouvelle)."""
    email = normalize(user.email)
    if email:
        EmailAddress.objects.get_or_create(user=user, email=email)


def link(address):
    token = signing.dumps({"id": address.pk, "email": address.email}, salt=SALT)
    return settings.SITE_URL + reverse("community:address_confirm", args=[token])


def send(address):
    context = {"name": address.user.profile.display_name, "email": address.email, "link": link(address)}
    try:
        send_mail(_("AJC06 : confirme ton adresse"), render_to_string("community/address_email.txt", context),
                  settings.DEFAULT_FROM_EMAIL, [address.email], fail_silently=False)
        return True
    except Exception:
        log.exception("Lien de confirmation non envoyé pour l'adresse %s", address.pk)
        return False


def from_token(token):
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
    return EmailAddress.objects.filter(pk=data.get("id"), email=data.get("email")).select_related("user").first()


def confirm(address):
    """Confirme l'adresse et relie les billets HelloAsso qui la portent. Faux si un autre compte l'a confirmée."""
    from projets import linking

    with transaction.atomic():
        if EmailAddress.objects.filter(email=address.email, confirmed=True).exclude(user=address.user).exists():
            return False
        if not address.confirmed:
            address.confirmed = True
            address.save(update_fields=["confirmed"])
        # Ajouts non confirmés de la même adresse par d'autres comptes : sans objet désormais
        EmailAddress.objects.filter(email=address.email, confirmed=False).exclude(user=address.user).delete()
    linking.link_user(address.user)
    return True


def confirm_primary(user):
    """Le compte vient d'être confirmé par le lien reçu à l'inscription : son adresse l'est aussi."""
    ensure_primary(user)
    address = EmailAddress.objects.filter(user=user, email=normalize(user.email)).first()
    if address:
        confirm(address)
