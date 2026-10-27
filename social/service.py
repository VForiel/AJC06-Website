"""Envoi des diffusions : tout de suite depuis /gestion/, ou à l'heure prévue par `manage.py send_posts`.

o2switch n'a pas de processus permanent : la commande est lancée par le cron, et aussi par le passage de
robots.txt toutes les 5 minutes (cron de maintien en éveil), dans un fil d'exécution à part (kick).
"""

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, transaction
from django.utils import timezone

from siteconfig.models import SiteConfig

from . import networks
from .models import Post
from .texts import alt_text
from .visuals import visual_path, visual_url

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def claim(post_id):
    """Passe la diffusion en « envoi » si elle est toujours à envoyer (évite les doublons entre processus)."""
    with transaction.atomic():
        return Post.objects.filter(pk=post_id, status=Post.Status.SCHEDULED).update(status=Post.Status.SENDING) == 1


def send(post):
    config = SiteConfig.get()
    post.attempts += 1
    if not config.network_ready(post.network):
        post.status, post.error = Post.Status.FAILED, f"{post.get_network_display()} n'est pas configuré ou pas activé."
        post.save(update_fields=["status", "error", "attempts"])
        return post
    event = post.event
    fmt = post.visual_format
    try:
        image = visual_path(event, fmt)
        image_url = settings.SITE_URL + visual_url(event, fmt)
        external_id, url = networks.PUBLISHERS[post.network](post, config, image, image_url, alt_text(event))
    except Exception as exc:  # erreur de réseau, d'API, de SMTP… : notée sur la diffusion, jamais perdue
        log.warning("Diffusion %s en échec : %s", post.pk, exc)
        retry = post.attempts < MAX_ATTEMPTS and isinstance(exc, (networks.NetworkError, OSError))
        post.status = Post.Status.SCHEDULED if retry else Post.Status.FAILED
        if retry:
            post.scheduled_at = timezone.now() + timedelta(minutes=5 * post.attempts)
        post.error = f"{exc.__class__.__name__} : {exc}"[:2000]
        post.save(update_fields=["status", "error", "attempts", "scheduled_at"])
        return post
    post.status, post.external_id, post.external_url = Post.Status.PUBLISHED, str(external_id), url
    post.published_at, post.error = timezone.now(), ""
    post.save(update_fields=["status", "external_id", "external_url", "published_at", "error", "attempts"])
    return post


def send_due():
    sent = []
    for post_id in Post.objects.due().values_list("pk", flat=True)[:20]:
        if claim(post_id):
            post = send(Post.objects.select_related("event").get(pk=post_id))
            sent.append(f"{post.get_network_display()} #{post.pk} : {post.get_status_display()}")
    # Envoi interrompu (processus arrêté pendant l'envoi) : on retente au passage suivant
    stuck = timezone.now() - timedelta(minutes=15)
    Post.objects.filter(status=Post.Status.SENDING, scheduled_at__lt=stuck, attempts__lt=MAX_ATTEMPTS).update(
        status=Post.Status.SCHEDULED)
    return "; ".join(sent) or "Rien à diffuser"


def kick():
    """Lance send_due dans un fil à part s'il y a des diffusions dues (au plus une fois par minute)."""
    if not cache.add("social-kick", 1, 60) or not Post.objects.due().exists():
        return

    def run():
        try:
            send_due()
        except Exception:
            log.exception("Diffusions programmées")
        finally:
            close_old_connections()

    threading.Thread(target=run, daemon=True).start()
