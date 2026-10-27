"""Clients minimaux de l'API Graph de Meta (Facebook et Instagram) et envoi par courriel (adapté de Nice-Event).

Chaque fonction `publish_<canal>` renvoie (identifiant, lien) ou lève PublishError avec un message lisible ;
`check(<réseau>, config)` vérifie les identifiants sans rien publier. Facebook et Instagram vont chercher le visuel
à son adresse publique sur le site : pas de téléversement, et urllib suffit (pas de dépendance à installer).
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

TIMEOUT = 30
BCC_BATCH = 50  # destinataires par message : les serveurs SMTP limitent le nombre d'adresses par envoi


class PublishError(Exception):
    pass


class NetworkError(PublishError):
    """Réseau injoignable ou erreur passagère (5xx) : l'envoi sera retenté."""


def call(method, url, what, params, timeout=TIMEOUT):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url, data = f"{url}?{data.decode()}", None
    request = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "ajc06-site"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            detail = (json.loads(body).get("error") or {}).get("message", "")
        except (ValueError, AttributeError):
            detail = body[:300].decode(errors="replace")
        error = NetworkError if exc.code >= 500 else PublishError
        raise error(f"{what} : {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NetworkError(f"{what} : {exc}") from exc
    return json.loads(body) if body else {}


def graph(config, path):
    return f"https://graph.facebook.com/{config.meta_api_version}/{path}"


def publish_facebook(post, config, image_path, image_url, alt):
    answer = call("POST", graph(config, f"{config.facebook_page_id}/photos"), "Publication sur Facebook",
                  {"url": image_url, "caption": post.text, "access_token": config.facebook_page_token}, timeout=60)
    post_id = answer.get("post_id") or answer.get("id")
    return post_id, f"https://www.facebook.com/{post_id}"


def publish_instagram(post, config, image_path, image_url, alt):
    """Instagram va chercher l'image (JPEG) à son adresse publique, la traite, puis on publie."""
    token = config.facebook_page_token
    container = call("POST", graph(config, f"{config.instagram_user_id}/media"), "Préparation sur Instagram",
                     {"image_url": image_url, "caption": post.text, "alt_text": alt[:1000], "access_token": token},
                     timeout=60)["id"]
    for _attempt in range(20):
        state = call("GET", graph(config, container), "Suivi Instagram",
                     {"fields": "status_code", "access_token": token})
        if state.get("status_code") == "FINISHED":
            break
        if state.get("status_code") in ("ERROR", "EXPIRED"):
            raise PublishError(f"Instagram a refusé l'image ({state.get('status_code')})")
        time.sleep(3)
    media = call("POST", graph(config, f"{config.instagram_user_id}/media_publish"), "Publication sur Instagram",
                 {"creation_id": container, "access_token": token}, timeout=60)["id"]
    link = call("GET", graph(config, media), "Lien Instagram", {"fields": "permalink", "access_token": token})
    return media, link.get("permalink", "")


def publish_email(post, config, image_path, image_url, alt):
    """Envoi en copie cachée (personne ne voit les autres adresses), par paquets, avec le visuel en pièce jointe.
    Le backend par défaut (siteconfig.mail.ConfigEmailBackend) lit le serveur SMTP dans les réglages."""
    from django.core.mail import get_connection

    recipients = post.recipient_list
    if not recipients:
        raise PublishError("Aucun destinataire.")
    from django.utils import translation

    event = post.event
    with translation.override(post.visual_language):  # page anglaise du site pour un courriel tout en anglais
        url = settings.SITE_URL + event.get_absolute_url()
    html = render_to_string("social/email.html", {
        "post": post, "event": event, "image_url": image_url, "alt": alt, "url": url, "english": post.language == "en",
    })
    connection = get_connection()
    with open(image_path, "rb") as f:
        image = f.read()
    for i in range(0, len(recipients), BCC_BATCH):
        message = EmailMultiAlternatives(post.subject or event.title, post.text, config.from_email, [config.contact_email],
                                         bcc=recipients[i:i + BCC_BATCH], connection=connection,
                                         reply_to=[config.contact_email])
        message.attach_alternative(html, "text/html")
        message.attach(f"ajc06-{event.slug}.jpg", image, "image/jpeg")
        message.send()
    return "", ""


PUBLISHERS = {"facebook": publish_facebook, "instagram": publish_instagram, "email": publish_email}


def check(network, config):
    """(ok, message) : les identifiants permettent-ils de publier ?"""
    try:
        if network == "facebook":
            page = call("GET", graph(config, config.facebook_page_id), "Page Facebook",
                        {"fields": "name", "access_token": config.facebook_page_token})
            return True, f"Page « {page.get('name')} »"
        if network == "instagram":
            account = call("GET", graph(config, config.instagram_user_id), "Compte Instagram",
                           {"fields": "username", "access_token": config.facebook_page_token})
            return True, f"Compte @{account.get('username')}"
    except (PublishError, KeyError) as exc:
        return False, str(exc)[:300]
    return False, "Réseau inconnu"
