from django.conf import settings

from events.models import Event

from . import effects
from .models import Announcement

WHATSAPP_URL = "https://chat.whatsapp.com/C2zmLuCQ0L61vB0wChRbvI"
INSTAGRAM_URL = "https://www.instagram.com/assojc06/"
DISCORD_URL = "https://discord.com/invite/Na9zkQP78Z"

# WhatsApp et Instagram sont les canaux principaux de l'asso, dans cet ordre partout sur le site.
SOCIALS = [
    ("WhatsApp", WHATSAPP_URL),
    ("Instagram", INSTAGRAM_URL),
    ("Discord", DISCORD_URL),
    ("Facebook", "https://www.facebook.com/groups/ajc06/"),
]

HELLOASSO = "https://www.helloasso.com/associations/association-des-jeunes-chercheurs-des-alpes-mariti"


def site(request):
    return {
        "SITE_URL": settings.SITE_URL,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
        "LEGAL_HOST": settings.LEGAL_HOST,
        "SOCIALS": SOCIALS,
        "WHATSAPP_URL": WHATSAPP_URL,
        "INSTAGRAM_URL": INSTAGRAM_URL,
        "DISCORD_URL": DISCORD_URL,
        "HELLOASSO_URL": HELLOASSO,
        "DONATE_URL": f"{HELLOASSO}/formulaires/1",
        "next_event": Event.objects.published().official().upcoming().first(),
        "announcement": Announcement.current(),
        "effects": current_effects(request),
        "asso_age": effects.age(),
    }


def current_effects(request):
    """Effets du jour, ou aperçu choisi par un membre du bureau (?effets=noel,halloween ; ?effets=reset)."""
    user = getattr(request, "user", None)
    if user is not None and user.is_staff:
        wanted = request.GET.get("effets")
        if wanted == "reset":
            request.session.pop("effects_preview", None)
        elif wanted is not None:
            request.session["effects_preview"] = [c for c in wanted.split(",") if c in effects.EFFECTS]
        preview = request.session.get("effects_preview")
        if preview is not None:
            return preview
    return effects.active()
