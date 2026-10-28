from datetime import timedelta
from itertools import groupby

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import cache_control

from .ical import calendar
from .models import TYPES, Event, with_emoji


def event_list(request):
    events = Event.objects.published().select_related("organizer__profile")
    known = {code for code, _label, _staff in TYPES}
    # Plusieurs types possibles (?type=a&type=b, lien de la page « Filtres et alertes ») : l'un ou l'autre.
    kinds = [k for k in request.GET.getlist("type") if k in known]
    kind = kinds[0] if len(kinds) == 1 else ""
    if kinds:
        events = events.with_types(kinds)
    origin = request.GET.get("par", "")
    if origin == "asso":
        events = events.official()
    elif origin == "communaute":
        events = events.community()
    else:
        origin = ""
    past = events.past()
    years = [(year, list(items)) for year, items in groupby(past, key=lambda e: e.start_date.year)]
    return render(request, "events/list.html", {
        "upcoming": events.upcoming(),
        "years": years,
        "kinds": [(code, with_emoji(code, label)) for code, label, _staff in TYPES if code != "autre"],
        "kind": kind,
        "several": len(kinds) > 1,
        "origin": origin,
        "past_count": len(past),
    })


def event_detail(request, slug):
    from community.models import Attendance, friends_of

    event = get_object_or_404(Event.objects.select_related("organizer__profile"), slug=slug)
    visible = event.is_published and not event.on_hold
    if not visible and not (request.user.is_authenticated and (request.user.is_staff or event.organizer_id == request.user.pk)):
        raise Http404
    from projets import helloasso

    helloasso.sync_on_visit(event)  # campagne clôturée jamais lue : nombre de participant·es
    photos = event.photos.filter(is_hidden=False)[:12]
    others = Event.objects.published().upcoming().exclude(pk=event.pk)[:3]
    if not others:
        others = Event.objects.published().past().with_type(event.main_type).exclude(pk=event.pk).exclude(poster="")[:3]
    attendees = [a.user for a in Attendance.objects.filter(event=event, user__is_active=True).select_related("user__profile")]
    from community.forms import CommentForm
    from community.models import Comment

    from_helloasso = event.has_helloasso_count
    context = {"event": event, "others": others, "attendees": attendees, "attendee_count": len(attendees),
               "from_helloasso": from_helloasso,
               "participant_count": event.helloasso_count if from_helloasso else len(attendees),
               "visible": visible, "photos": photos,
               "comments": Comment.objects.filter(event=event, is_hidden=False, author__is_active=True)
               .select_related("author__profile"),
               "comment_form": CommentForm(),
               "share_url": request.build_absolute_uri(event.get_absolute_url()),
               "share_text": share_text(event),
               "story_url": reverse("events:visual", args=[event.slug, "story"]) + "?telecharger=1"}
    if request.user.is_authenticated:
        friends = list(friends_of(request.user))
        going_ids = {u.pk for u in attendees}
        context.update({
            "is_going": request.user.pk in going_ids,
            "friends_going": [f for f in friends if f.pk in going_ids],
            "invitable": [f for f in friends if f.pk not in going_ids],
            "can_edit": event.is_community and (event.organizer_id == request.user.pk or request.user.is_staff),
        })
    return render(request, "events/detail.html", context)


def share_text(event):
    """Texte des liens de partage : « PhD meet-up de rentrée — 17 janvier 2026, Nice »."""
    from core.templatetags.ajc import when

    place = f", {event.venue}" if event.venue else ""
    return f"{event.title_tr} — {when(event)}{place}"


VISUALS = {"og", "portrait", "story"}


def event_visual(request, slug, fmt):
    """Visuel généré de l'événement (story à télécharger, diffusion sur les réseaux et par courriel)."""
    from django.http import FileResponse

    from social.visuals import visual_path

    event = get_object_or_404(Event, slug=slug)
    if fmt not in VISUALS or not (event.is_published and not event.on_hold or request.user.is_staff):
        raise Http404
    response = FileResponse(open(visual_path(event, fmt), "rb"), content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=3600"
    if request.GET.get("telecharger"):
        response["Content-Disposition"] = f'attachment; filename="ajc06-{event.slug}-{fmt}.jpg"'
    return response


def _ics_response(body, filename):
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def event_ics(request, slug):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    return _ics_response(calendar([event], name=event.title_tr), f"{event.slug}.ics")


def poster_version(event):
    try:
        return int(event.poster.storage.get_modified_time(event.poster.name).timestamp())
    except (OSError, NotImplementedError):
        return int(event.updated_at.timestamp())


@cache_control(max_age=600)
def nice_event_feed(request):
    """Sorties de membres à venir cochées « publier aussi sur Nice-Event », avec tout leur détail (lu par nice-event.fr)."""
    events = (Event.objects.published().filter(is_community=True, on_nice_event=True).upcoming()
              .order_by("start_date", "start_time"))
    site = settings.SITE_URL
    items = []
    for e in events:
        end = e.ends_at if (e.end_time or e.multi_day) else None
        if e.all_day and end:
            end = end.replace(hour=23, minute=59) - timedelta(days=1)
        items.append({
            "id": e.pk, "url": site + e.get_absolute_url(), "title": e.title, "title_en": e.title_en,
            "summary": e.summary, "summary_en": e.summary_en, "description": e.body, "description_en": e.body_en,
            "start": e.starts_at.isoformat() if not e.all_day else e.start_date.isoformat(),
            "end": end.isoformat() if end else None, "all_day": e.all_day,
            "place": e.venue, "address": e.address, "lat": e.latitude, "lon": e.longitude,
            # ?v= : l'adresse change quand l'affiche est remplacée, même sous le même nom (Nice-Event la reprend alors)
            "image": f"{site}{e.poster.url}?v={poster_version(e)}" if e.poster else "", "price": e.price,
            "registration_url": e.registration_url, "types": e.type_codes,
            "organizer": "AJC06 (sortie proposée par un·e membre)", "updated": e.updated_at.isoformat(),
        })
    return JsonResponse({"source": "AJC06", "site": site, "events": items}, json_dumps_params={"ensure_ascii": False})


def agenda_ics(request):
    return _ics_response(calendar(Event.objects.published().order_by("start_date")), "ajc06.ics")
