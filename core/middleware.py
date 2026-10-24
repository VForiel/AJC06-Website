"""Redirections 301 depuis les adresses de l'ancien site WordPress (français et /en/…)."""

import re

from django.http import HttpResponsePermanentRedirect
from django.urls import reverse
from django.utils import translation

# Anciennes pages fixes, dans les deux langues de l'ancien site.
FIXED = {
    "evenement": "events:list",
    "event": "events:list",
    "events": "events:list",
    "don": "core:support",
    "team": "core:team",
    "our-missions": "core:missions",
    "resources": "core:resources",
    "news": "blog:list",
    "contact-us": "core:contact",
    "politique-de-confidentialite": "core:privacy",
    "privacy-policy": "core:privacy",
    "legal-notice": "core:legal",
    "plan-de-site": "core:home",
    "sitemap-page": "core:home",
}


def legacy_target(path):
    from blog.models import Post
    from events.models import Event

    parts = [p for p in path.strip("/").split("/") if p]
    lang = "fr"
    if parts and parts[0] == "en":
        lang, parts = "en", parts[1:]
    with translation.override(lang):
        if not parts:
            return None
        head = parts[0]
        if head == "events" and len(parts) > 1:
            if Event.objects.filter(slug=parts[1]).exists():
                return reverse("events:detail", args=[parts[1]])
            return reverse("events:list")
        if head == "locations":
            return reverse("events:list")
        if head == "category":
            return reverse("blog:list")
        if head == "ressources" and len(parts) > 1:
            return reverse("core:resources")
        if head in FIXED and len(parts) == 1:
            return reverse(FIXED[head])
        if len(parts) == 1:
            live = Post.objects.live()
            field = "legacy_slug_en" if lang == "en" else "legacy_slug"
            post = live.filter(**{field: head}).first() or live.filter(slug=head).first()
            if post:
                return post.get_absolute_url()
            if re.fullmatch(r"ajc06-.*", head):
                return reverse("core:home")
    return None


class LegacyRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 404 and request.method in ("GET", "HEAD"):
            target = legacy_target(request.path)
            if target and target != request.path:
                return HttpResponsePermanentRedirect(target)
        return response
