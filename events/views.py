from itertools import groupby

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from .ical import calendar
from .models import TYPES, Event, with_emoji


def event_list(request):
    events = Event.objects.published().select_related("organizer__profile")
    kind = request.GET.get("type", "")
    if kind not in {code for code, _label, _staff in TYPES}:
        kind = ""
    if kind:
        events = events.with_type(kind)
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
        "origin": origin,
        "past_count": len(past),
    })


def event_detail(request, slug):
    from community.models import Attendance, friends_of

    event = get_object_or_404(Event.objects.select_related("organizer__profile"), slug=slug)
    visible = event.is_published and not event.on_hold
    if not visible and not (request.user.is_authenticated and (request.user.is_staff or event.organizer_id == request.user.pk)):
        raise Http404
    photos = event.photos.filter(is_hidden=False)[:12]
    others = Event.objects.published().upcoming().exclude(pk=event.pk)[:3]
    if not others:
        others = Event.objects.published().past().with_type(event.main_type).exclude(pk=event.pk).exclude(poster="")[:3]
    attendees = [a.user for a in Attendance.objects.filter(event=event, user__is_active=True).select_related("user__profile")]
    context = {"event": event, "others": others, "attendees": attendees, "attendee_count": len(attendees),
               "visible": visible, "photos": photos}
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


def _ics_response(body, filename):
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def event_ics(request, slug):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    return _ics_response(calendar([event], name=event.title_tr), f"{event.slug}.ics")


def agenda_ics(request):
    return _ics_response(calendar(Event.objects.published().order_by("start_date")), "ajc06.ics")
