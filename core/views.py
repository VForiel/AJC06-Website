import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from blog.models import Post
from events.models import Event
from siteconfig.models import SiteConfig

from .forms import ContactForm
from .i18n import is_english
from .models import SUBJECTS, Board, Member, Resource
from .security import client_ip, throttled

log = logging.getLogger(__name__)
CONTACTS_PER_HOUR = 5


def localized(name):
    """Pages surtout rédactionnelles : une version par langue (core/en/<page>.html), repli sur le français."""
    folder, file = name.rsplit("/", 1)
    return [f"{folder}/en/{file}", name] if is_english() else [name]


def home(request):
    events = Event.objects.published()
    official = events.official()
    past = official.past()
    first_board = Board.objects.order_by("year").first()
    return render(request, "core/home.html", {
        "upcoming": official.upcoming()[:3],
        "community": events.community().upcoming().select_related("organizer__profile")[:4],
        "wall": past.exclude(poster="")[:10],
        "posts": Post.objects.live()[:3],
        "stats": {
            "events": past.count(),
            "since": first_board.year if first_board else 2017,
            "volunteers": Member.objects.values("name").distinct().count(),
            "first_event": past.last(),
            "places": past.exclude(venue="").values("venue").distinct().count(),
        },
    })


def missions(request):
    return render(request, localized("core/missions.html"))


def team(request):
    boards = list(Board.objects.prefetch_related("members"))
    return render(request, "core/team.html", {"current": boards[0] if boards else None, "previous": boards[1:]})


def resources(request):
    items = Resource.objects.all()
    groups = [(value, label, [r for r in items if r.category == value]) for value, label in Resource.Category.choices]
    return render(request, "core/resources.html", {"groups": groups})


def resource(request, slug):
    item = get_object_or_404(Resource, slug=slug)
    siblings = Resource.objects.filter(category=item.category).exclude(pk=item.pk)
    return render(request, "core/resource.html", {"resource": item, "siblings": siblings})


def contact(request):
    subject = request.GET.get("sujet")
    form = ContactForm(request.POST or None, initial={"subject": subject} if subject in dict(SUBJECTS) else None)
    if request.method == "POST" and form.is_valid():
        if throttled(f"contact:{client_ip(request)}", CONTACTS_PER_HOUR, 3600):
            messages.error(request, _("Trop de messages envoyés depuis cette connexion, réessaie dans une heure."))
            return redirect("core:contact")
        if not form.is_spam():
            msg = form.save()
            try:
                send_mail(
                    f"[Site AJC06] {msg.get_subject_display()} — {msg.name}",
                    f"{msg.message}\n\n— {msg.name} <{msg.email}>",
                    None,
                    [SiteConfig.get().contact_email],
                    fail_silently=False,
                )
            except Exception:  # le message reste lisible dans /gestion/
                log.exception("Envoi du courriel de contact impossible")
        messages.success(request, _("Message envoyé. On te répond dès que possible, en général sous quelques jours."))
        return redirect("core:contact")
    return render(request, "core/contact.html", {"form": form})


def support(request):
    return render(request, localized("core/support.html"))


def legal(request):
    return render(request, localized("core/legal.html"))


def privacy(request):
    return render(request, localized("core/privacy.html"))


@require_GET
def robots(request):
    lines = ["User-agent: *", "Disallow: /gestion/", "Disallow: /admin/", f"Sitemap: {settings.SITE_URL}/sitemap.xml"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def not_found(request, exception=None):
    return render(request, "404.html", {"upcoming": Event.objects.published().upcoming()[:2]}, status=404)
