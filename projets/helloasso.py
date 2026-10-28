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


def config():
    from siteconfig.models import SiteConfig

    return SiteConfig.get()


def configured():
    return config().helloasso_ready


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
    current = config()
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": current.helloasso_client_id,
        "client_secret": current.helloasso_client_secret,
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


def org_forms(org):
    """Tous les formulaires d'événement de l'organisation, clôturés compris (mis en cache une heure)."""
    key = f"helloasso:forms:{org}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    auth = {"Authorization": f"Bearer {token()}"}
    forms, continuation = [], ""
    for _page in range(20):
        query = [("pageSize", 100), ("formTypes", "Event")]
        query += [("states", state) for state in ("Public", "Private", "Draft", "Disabled")]
        if continuation:
            query.append(("continuationToken", continuation))
        page = _request(f"{API}/v5/organizations/{org}/forms?{urllib.parse.urlencode(query)}", headers=auth)
        data = page.get("data") or []
        forms += data
        continuation = (page.get("pagination") or {}).get("continuationToken", "")
        if len(data) < 100 or not continuation:
            break
    cache.set(key, forms, 3600)
    return forms


def _words(text):
    return set(re.findall(r"\w{3,}", (text or "").lower())) - {"phd", "meet", "the", "des", "les", "une", "ajc06"}


def find_form(event, taken=()):
    """Lien HelloAsso d'un événement qui n'en a pas : formulaire du même jour, au titre le plus proche."""
    org = config().helloasso_organization
    best, best_score = None, 0
    for form in org_forms(org):
        start = (form.get("startDate") or "")[:10]
        if start != event.start_date.isoformat() or form.get("formType", "Event") != "Event":
            continue
        url = f"https://www.helloasso.com/associations/{org}/evenements/{form.get('formSlug')}"
        if url in taken:
            continue
        score = len(_words(event.title) & _words(form.get("title"))) + 1  # même jour : déjà un indice
        if score > best_score:
            best, best_score = url, score
    return best


def discover_links(events):
    """Renseigne le lien des événements passés qui n'en ont pas. Renvoie les événements complétés."""
    from events.models import Event

    taken = set(Event.objects.filter(registration_url__contains="helloasso.com").values_list("registration_url", flat=True))
    found = []
    for event in events:
        if event.registration_url or event.is_upcoming:
            continue
        url = find_form(event, taken)
        if url:
            event.registration_url = url
            event.save(update_fields=["registration_url"])
            taken.add(url)
            found.append(event)
    return found


def sync_event(event):
    """Met à jour les billets et le compteur d'un événement. Renvoie le nombre d'inscriptions, ou None."""
    link = parse_link(event.registration_url)
    if not link or not configured():
        return None
    org, form_type, slug = link
    if org != config().helloasso_organization:
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


def needs_sync(event):
    """Jamais synchronisé, ou pas depuis la fin de l'événement : les billets d'une campagne passée sont alors définitifs."""
    if not parse_link(event.registration_url):
        return False
    synced = event.helloasso_synced_at
    return synced is None or timezone.localtime(synced).date() <= event.last_date


def ensure_synced(event):
    """Synchronise si besoin (pages du bureau, bilans) ; renvoie un message d'erreur, ou None."""
    if not configured() or not needs_sync(event):
        return None
    try:
        sync_event(event)
    except HelloAssoError as error:
        log.warning("HelloAsso %s : %s", event.slug, error)
        return str(error)
    return None


def problem(event):
    """Pourquoi les inscriptions HelloAsso d'un événement ne peuvent pas être lues (pour le bureau), ou None."""
    url = event.registration_url or ""
    if "helloasso" not in url:
        return None
    link = parse_link(url)
    if not link:
        return "Le lien d'inscription n'est pas un lien de formulaire HelloAsso reconnu (…/associations/<asso>/evenements/<nom>)."
    if not configured():
        return "Identifiants HelloAsso absents dans les réglages du site : les inscriptions ne peuvent pas être lues."
    if link[0] != config().helloasso_organization:
        return f"Le formulaire appartient à une autre organisation HelloAsso ({link[0]}) : pas d'accès à ses inscriptions."
    return None


def sync_on_visit(event):
    """Première visite d'un événement passé jamais lu : lit sa campagne (sans attendre le cron). Une tentative par heure."""
    if event.is_upcoming or not configured() or not needs_sync(event):
        return
    key = f"helloasso:tried:{event.pk}"
    if cache.get(key):
        return
    cache.set(key, 1, 3600)
    ensure_synced(event)
