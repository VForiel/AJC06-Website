"""Connexion avec un compte Google (OpenID Connect, flux « authorization code », sans bibliothèque tierce).

Le jeton d'identité vient directement de Google par HTTPS, échangé avec notre client_secret : sa signature n'a pas
besoin d'être vérifiée (documentation Google), mais on contrôle l'émetteur, le destinataire, l'expiration, le nonce
et que Google a vérifié l'adresse.

Rapprochement : compte Google déjà relié, sinon adresse confirmée d'un compte (principale ou supplémentaire).
Une adresse principale non confirmée n'est jamais reprise (quelqu'un aurait pu créer le compte avec l'adresse d'un
autre) : la personne se connecte alors avec son mot de passe. Sinon un compte est créé, adresse confirmée, en
suivant la validation des nouveaux comptes (le bureau valide toujours en mode « bureau »).
"""

import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
SESSION_KEY = "google_login"


class GoogleError(Exception):
    pass


def config():
    from siteconfig.models import SiteConfig

    return SiteConfig.get()


def enabled():
    return config().google_ready


def redirect_uri():
    return settings.SITE_URL + reverse("community:google_callback")


def start(request, next_url=""):
    """Adresse de Google où envoyer la personne ; state et nonce sont gardés dans la session."""
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session[SESSION_KEY] = {"state": state, "nonce": nonce, "next": next_url, "at": int(time.time())}
    query = {"client_id": config().google_client_id, "redirect_uri": redirect_uri(), "response_type": "code",
             "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account"}
    return f"{AUTHORIZE}?{urllib.parse.urlencode(query)}"


def _decode(segment):
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def identity(request):
    """Au retour de Google : {sub, email, name} vérifiés, ou GoogleError. Renvoie aussi l'adresse de retour."""
    pending = request.session.pop(SESSION_KEY, None) or {}
    if request.GET.get("error"):
        raise GoogleError("cancelled")
    if not pending or not secrets.compare_digest(request.GET.get("state", ""), pending.get("state", "")):
        raise GoogleError("state")
    if time.time() - pending.get("at", 0) > 600:
        raise GoogleError("expired")
    current = config()
    data = urllib.parse.urlencode({"code": request.GET.get("code", ""), "client_id": current.google_client_id,
                                   "client_secret": current.google_client_secret, "redirect_uri": redirect_uri(),
                                   "grant_type": "authorization_code"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN, data=data), timeout=15) as response:
            answer = json.load(response)
        claims = _decode(answer["id_token"].split(".")[1])
    except (urllib.error.URLError, KeyError, IndexError, ValueError) as error:
        raise GoogleError("token") from error
    if (claims.get("iss") not in ISSUERS or claims.get("aud") != current.google_client_id
            or claims.get("exp", 0) < time.time() or claims.get("nonce") != pending.get("nonce")):
        raise GoogleError("claims")
    if not claims.get("email") or not claims.get("email_verified"):
        raise GoogleError("email")
    info = {"sub": str(claims["sub"]), "email": claims["email"].strip().lower(),
            "name": (claims.get("name") or claims.get("given_name") or "").strip()[:80]}
    return info, pending.get("next", "")


def find_or_create(info):
    """(compte, créé) pour cette identité Google ; GoogleError("unconfirmed") si l'adresse attend une confirmation."""
    from . import addresses, confirmation
    from .models import EmailAddress, GoogleAccount

    User = get_user_model()
    linked = GoogleAccount.objects.filter(sub=info["sub"]).select_related("user").first()
    if linked:
        return linked.user, False
    address = EmailAddress.objects.filter(email=info["email"], confirmed=True).select_related("user").first()
    if address:
        GoogleAccount.objects.create(user=address.user, sub=info["sub"])
        return address.user, False
    if User.objects.filter(email__iexact=info["email"]).exists():
        raise GoogleError("unconfirmed")
    with transaction.atomic():
        user = User(username=info["email"], email=info["email"])
        user.set_password(secrets.token_urlsafe(32))  # « mot de passe oublié » permet d'en choisir un
        pending = confirmation.mode() == "bureau"
        user.is_active = not pending
        user.save()
        profile = user.profile  # créé par le signal
        profile.display_name = info["name"] or info["email"].split("@")[0]
        profile.email_confirmed = not pending
        profile.save(update_fields=["display_name", "email_confirmed"])
        GoogleAccount.objects.create(user=user, sub=info["sub"])
    addresses.confirm_primary(user)  # Google a vérifié l'adresse
    return user, True
