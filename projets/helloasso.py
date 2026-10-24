"""Synchronisation des inscriptions HelloAsso (API v5, identifiants « client credentials »).

Seuls les billets des formulaires de l'organisation AJC06 sont lus. Les noms servent aux listes des bilans
(espace bureau) ; le site public n'affiche que le nombre d'inscriptions.
"""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import HelloAssoTicket

log = logging.getLogger(__name__)

API = "https://api.helloasso.com"
# HelloAsso filtre les requêtes sans User-Agent explicite (réponse 403).
HEADERS = {"User-Agent": "AJC06-Website/1.0 (+https://ajc06.com)", "Accept": "application/json"}
FORM_TYPES = {"evenements": "Event", "adhesions": "Membership", "formulaires": "Donation", "boutiques": "Shop",
              "paiements": "PaymentForm", "collectes": "CrowdFunding"}
LINK = re.compile(r"helloasso\.com/associations/(?P<org>[^/]+)/(?P<type>[^/]+)/(?P<slug>[^/?#]+)")


class HelloAssoError(Exception):
    pass


def configured():
    return bool(settings.HELLOASSO_CLIENT_ID and settings.HELLOASSO_CLIENT_SECRET)


def parse_link(url):
    """« …/associations/<org>/evenements/<slug> » -> (org, "Event", slug), ou None."""
    match = LINK.search(url or "")
    if not match or match["type"] not in FORM_TYPES:
        return None
    return match["org"], FORM_TYPES[match["type"]], match["slug"]


def _request(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**HEADERS, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise HelloAssoError(f"HelloAsso a répondu {error.code} pour {url.split('?')[0]}") from error
    except urllib.error.URLError as error:
        raise HelloAssoError(f"HelloAsso injoignable : {error.reason}") from error


def token():
    cached = cache.get("helloasso:token")
    if cached:
        return cached
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": settings.HELLOASSO_CLIENT_ID,
        "client_secret": settings.HELLOASSO_CLIENT_SECRET,
    }).encode()
    answer = _request(f"{API}/oauth2/token", data, {"Content-Type": "application/x-www-form-urlencoded"})
    cache.set("helloasso:token", answer["access_token"], max(60, int(answer.get("expires_in", 1800)) - 120))
    return answer["access_token"]


def form_items(org, form_type, slug):
    """Tous les billets du formulaire (pages de 100, jeton de continuation)."""
    auth = {"Authorization": f"Bearer {token()}"}
    items, continuation = [], ""
    for _page in range(50):
        query = {"pageSize": 100, "itemStates": "Processed"}
        if continuation:
            query["continuationToken"] = continuation
        page = _request(f"{API}/v5/organizations/{org}/forms/{form_type}/{slug}/items?{urllib.parse.urlencode(query)}",
                        headers=auth)
        data = page.get("data") or []
        items += data
        continuation = (page.get("pagination") or {}).get("continuationToken", "")
        if len(data) < 100 or not continuation:
            break
    return items


def sync_event(event):
    """Met à jour les billets et le compteur d'un événement. Renvoie le nombre d'inscriptions, ou None."""
    link = parse_link(event.registration_url)
    if not link or not configured():
        return None
    org, form_type, slug = link
    if org != settings.HELLOASSO_ORGANIZATION:
        return None  # formulaire d'une autre organisation : pas d'accès
    items = [i for i in form_items(org, form_type, slug) if i.get("type") in ("Registration", "Membership", None)]
    seen = set()
    for item in items:
        user = item.get("user") or item.get("payer") or {}
        seen.add(item["id"])
        HelloAssoTicket.objects.update_or_create(ticket_id=item["id"], defaults={
            "event": event,
            "first_name": (user.get("firstName") or "")[:100],
            "last_name": (user.get("lastName") or "")[:100],
            "tier": (item.get("name") or "")[:200],
            "amount": Decimal(item.get("amount") or 0) / 100,
        })
    HelloAssoTicket.objects.filter(event=event).exclude(ticket_id__in=seen).delete()  # remboursés / annulés
    event.helloasso_count = len(items)
    event.helloasso_synced_at = timezone.now()
    event.save(update_fields=["helloasso_count", "helloasso_synced_at"])
    return len(items)
