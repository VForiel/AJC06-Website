from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from django import forms
from django.http import HttpResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify

from blog.models import Post
from community import confirmation
from community.models import Notification, Profile, Report
from core import effects
from core.models import Announcement
from projets import helloasso, pdf, services
from projets.forms import AttachmentForm, DossierForm, budget_formset
from projets.models import Attachment, BudgetLine, SupportRequest
from core import markdown
from core.models import ContactMessage, Upload
from events.models import Event

from .forms import EventForm, PostForm, UploadForm

User = get_user_model()


def editor_required(view):
    """Réservé aux membres du bureau (comptes « équipe » de l'admin Django)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("gestion:login"))
        if not (request.user.is_active and request.user.is_staff):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@editor_required
def dashboard(request):
    return render(request, "gestion/dashboard.html", {
        "upcoming": Event.objects.upcoming()[:5],
        "drafts": Post.objects.filter(Q(status=Post.Status.DRAFT) | Q(published_at__gt=timezone.now()))[:5],
        "inbox": ContactMessage.objects.filter(handled=False)[:5],
        "reports": Report.objects.filter(handled=False).select_related("event", "profile")[:5],
        "supports": SupportRequest.objects.filter(status=SupportRequest.Status.PENDING).select_related("event", "requester__profile"),
        "deadlines": services.deadlines(Event.objects.official().select_related("dossier"))[:6],
        "community_upcoming": Event.objects.community().upcoming().select_related("organizer__profile")[:5],
        "pending_accounts": confirmation.pending().select_related("profile").order_by("-date_joined")[:8],
        "counts": {
            "reports": Report.objects.filter(handled=False).count(),
            "members": Profile.objects.filter(user__is_active=True).count(),
            "events": Event.objects.count(),
            "posts": Post.objects.live().count(),
            "inbox": ContactMessage.objects.filter(handled=False).count(),
        },
    })


# Événements ---------------------------------------------------------------


@editor_required
def event_list(request):
    q = request.GET.get("q", "").strip()
    events = Event.objects.select_related("organizer__profile")
    if q:
        events = events.filter(Q(title__icontains=q) | Q(venue__icontains=q))
    return render(request, "gestion/event_list.html", {
        "upcoming": events.upcoming(), "past": events.past(), "q": q,
    })


@editor_required
def event_edit(request, pk=None, source=None):
    event = get_object_or_404(Event, pk=pk) if pk else None
    initial = {}
    if source:  # duplication : on reprend tout sauf la date et l'affiche
        original = get_object_or_404(Event, pk=source)
        initial = {f: getattr(original, f) for f in EventForm.Meta.fields if f not in ("start_date", "end_date", "poster")}
        initial["is_published"] = False
        initial["type_list"] = original.type_codes
    form = EventForm(request.POST or None, request.FILES or None, instance=event, initial=initial)
    if source and not request.POST:
        form.fields["type_list"].initial = initial["type_list"]
    if request.method == "POST" and form.is_valid():
        event = form.save()
        state = "publié" if event.is_published else "enregistré (non publié)"
        messages.success(request, f"« {event.title} » {state}.")
        if "continue" in request.POST:
            return redirect("gestion:event_edit", pk=event.pk)
        return redirect("gestion:events")
    return render(request, "gestion/event_form.html", {"form": form, "event": event, "duplicate": bool(source)})


@editor_required
def event_duplicate(request, pk):
    return event_edit(request, source=pk)


@editor_required
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if request.method == "POST":
        event.delete()
        messages.success(request, f"« {event.title} » supprimé.")
        return redirect("gestion:events")
    return render(request, "gestion/confirm_delete.html", {"object": event, "kind": "l'événement",
                                                            "back": "gestion:event_edit"})


# Articles -----------------------------------------------------------------


@editor_required
def post_list(request):
    return render(request, "gestion/post_list.html", {"posts": Post.objects.all()})


@editor_required
def post_edit(request, pk=None):
    post = get_object_or_404(Post, pk=pk) if pk else None
    form = PostForm(request.POST or None, request.FILES or None, instance=post)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        if not post.author_id:
            post.author = request.user
        post.save()
        if post.is_live:
            messages.success(request, f"« {post.title} » est en ligne.")
        elif post.status == Post.Status.PUBLISHED:
            messages.success(request, f"« {post.title} » sera publié le {timezone.localtime(post.published_at):%d/%m/%Y à %H:%M}.")
        else:
            messages.success(request, f"Brouillon « {post.title} » enregistré.")
        if "continue" in request.POST:
            return redirect("gestion:post_edit", pk=post.pk)
        return redirect("gestion:posts")
    return render(request, "gestion/post_form.html", {"form": form, "post": post})


@editor_required
def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if request.method == "POST":
        post.delete()
        messages.success(request, f"« {post.title} » supprimé.")
        return redirect("gestion:posts")
    return render(request, "gestion/confirm_delete.html", {"object": post, "kind": "l'article",
                                                            "back": "gestion:post_edit"})


# Messages de contact ------------------------------------------------------


@editor_required
def inbox(request):
    return render(request, "gestion/inbox.html", {"items": ContactMessage.objects.all()[:200]})


@editor_required
@require_POST
def inbox_toggle(request, pk):
    item = get_object_or_404(ContactMessage, pk=pk)
    item.handled = not item.handled
    item.save(update_fields=["handled"])
    return redirect("gestion:inbox")


# Modération ---------------------------------------------------------------


@editor_required
def reports(request):
    return render(request, "gestion/reports.html", {
        "items": Report.objects.select_related("reporter__profile", "event", "profile")[:200],
    })


@editor_required
def accounts(request):
    """Comptes en attente (lien de confirmation pas ouvert, ou validation par le bureau) et derniers inscrits."""
    return render(request, "gestion/accounts.html", {
        "pending": confirmation.pending().select_related("profile").order_by("-date_joined"),
        "recent": User.objects.filter(is_active=True).select_related("profile").order_by("-date_joined")[:15],
        "mode": confirmation.mode(),
    })


@editor_required
@require_POST
def account_decide(request, pk):
    user = get_object_or_404(confirmation.pending().select_related("profile"), pk=pk)
    name = user.profile.display_name
    if request.POST.get("decision") == "valider":
        confirmation.approve(user)
        confirmation.send_approved(user)
        messages.success(request, f"Compte de {name} validé.")
    elif request.POST.get("decision") == "refuser":
        user.delete()
        messages.success(request, f"Inscription de {name} refusée et supprimée.")
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = reverse("gestion:accounts")
    return redirect(back)


@editor_required
@require_POST
def report_toggle(request, pk):
    item = get_object_or_404(Report, pk=pk)
    item.handled = not item.handled
    item.save(update_fields=["handled"])
    return redirect("gestion:reports")


@editor_required
@require_POST
def event_hide(request, pk):
    """Retire un événement communautaire de l'agenda (il reste visible ici et peut être republié)."""
    event = get_object_or_404(Event, pk=pk)
    event.is_published = not event.is_published
    event.save(update_fields=["is_published"])
    messages.success(request, f"« {event.title} » {'republié' if event.is_published else 'masqué'}.")
    return redirect(request.POST.get("next") or "gestion:reports")


# Outils de l'éditeur ------------------------------------------------------


@editor_required
@require_POST
def preview(request):
    return JsonResponse({"html": markdown.render(request.POST.get("text", ""))})


@editor_required
@require_POST
def upload(request):
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"error": "Ce fichier n'est pas une image valide."}, status=400)
    item = Upload.objects.create(file=form.cleaned_data["file"], uploaded_by=request.user)
    return JsonResponse({"url": item.file.url})


# Demandes de soutien ---------------------------------------------------------


@editor_required
def supports(request):
    return render(request, "gestion/supports.html", {
        "pending": SupportRequest.objects.filter(status=SupportRequest.Status.PENDING).select_related("event", "requester__profile"),
        "done": SupportRequest.objects.exclude(status=SupportRequest.Status.PENDING).select_related("event", "requester__profile")[:30],
    })


@editor_required
@require_POST
def support_decide(request, pk):
    support = get_object_or_404(SupportRequest, pk=pk)
    note = request.POST.get("note", "").strip()
    if request.POST.get("decision") == "accept":
        services.approve(support, request.user, note)
        messages.success(request, f"Soutien accordé à « {support.event.title} ». L'événement est en attente le temps du dossier UniCA.")
    else:
        services.refuse(support, request.user, note)
        messages.success(request, f"Demande pour « {support.event.title} » refusée.")
    if support.requester:
        Notification.objects.create(recipient=support.requester, actor=request.user,
                                    verb=Notification.Verb.SUPPORT_ANSWER, event=support.event)
    return redirect("gestion:supports")


# Dossier université (projet prévisionnel, bilan) -------------------------------


@editor_required
def dossier(request, pk):
    event = get_object_or_404(Event, pk=pk)
    item = services.dossier_for(event)
    Formset = budget_formset("prev")
    form = DossierForm(request.POST or None, instance=item)
    prev = Formset(request.POST or None, instance=item, prefix="prev", queryset=item.budget_lines.filter(phase="prev"))
    real = Formset(request.POST or None, instance=item, prefix="reel", queryset=item.budget_lines.filter(phase="reel"))
    if request.method == "POST" and form.is_valid() and prev.is_valid() and real.is_valid():
        form.save()
        for formset, phase in ((prev, BudgetLine.Phase.FORECAST), (real, BudgetLine.Phase.ACTUAL)):
            for line in formset.save(commit=False):
                line.phase = phase
                line.save()
            for line in formset.deleted_objects:
                line.delete()
        messages.success(request, "Dossier enregistré.")
        return redirect("gestion:dossier", pk=event.pk)
    from projets.pdf import participants

    return render(request, "gestion/dossier.html", {
        "event": event, "dossier": item, "form": form, "prev": prev, "real": real,
        "attach_form": AttachmentForm(), "attachments": item.attachments.all(),
        "forecast_totals": item.totals("prev"), "real_totals": item.totals("reel"),
        "participants": participants(event), "helloasso_link": helloasso.parse_link(event.registration_url),
        "deadline": services.forecast_deadline(event),
        "support": SupportRequest.objects.filter(event=event).first(),
        "today": timezone.localdate(),
    })


@editor_required
@require_POST
def dossier_attach(request, pk):
    event = get_object_or_404(Event, pk=pk)
    item = services.dossier_for(event)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.dossier = item
        attachment.save()
        messages.success(request, "Pièce jointe ajoutée.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("gestion:dossier", pk=event.pk)


@editor_required
@require_POST
def dossier_detach(request, pk, attachment):
    item = get_object_or_404(Attachment, pk=attachment, dossier__event_id=pk)
    item.file.delete(save=False)
    item.delete()
    return redirect("gestion:dossier", pk=pk)


@editor_required
def dossier_pdf(request, pk, kind):
    event = get_object_or_404(Event, pk=pk)
    item = services.dossier_for(event)
    data = pdf.forecast(item) if kind == "previsionnel" else pdf.report(item)
    name = f"{'Projet previsionnel' if kind == 'previsionnel' else 'Bilan'} - {slugify(event.title)} - {event.start_date:%Y-%m-%d}.pdf"
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{name}"'
    return response


@editor_required
@require_POST
def event_hold(request, pk):
    event = get_object_or_404(Event, pk=pk)
    event.on_hold = not event.on_hold
    event.save(update_fields=["on_hold"])
    messages.success(request, f"« {event.title} » {'mis en attente' if event.on_hold else 'publié sur le site'}.")
    if request.POST.get("next"):
        return redirect(request.POST["next"])
    return redirect("gestion:dossier", pk=event.pk)


@editor_required
@require_POST
def helloasso_sync(request, pk):
    event = get_object_or_404(Event, pk=pk)
    try:
        count = helloasso.sync_event(event)
    except helloasso.HelloAssoError as error:
        messages.error(request, str(error))
    else:
        if count is None:
            messages.error(request, "Pas de lien HelloAsso de l'AJC06 sur cet événement (ou identifiants HelloAsso absents).")
        else:
            messages.success(request, f"{count} inscription(s) HelloAsso récupérée(s).")
    return redirect(request.POST.get("next") or "gestion:events")


# Annonces et effets ----------------------------------------------------------


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        exclude = ["created_at"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }


@editor_required
def announcements(request, pk=None):
    item = get_object_or_404(Announcement, pk=pk) if pk else None
    form = AnnouncementForm(request.POST or None, instance=item)
    if request.method == "POST":
        if "delete" in request.POST and item:
            item.delete()
            messages.success(request, "Annonce supprimée.")
            return redirect("gestion:announcements")
        if form.is_valid():
            form.save()
            messages.success(request, "Annonce enregistrée.")
            return redirect("gestion:announcements")
    return render(request, "gestion/announcements.html", {
        "form": form, "item": item, "items": Announcement.objects.all(), "current": Announcement.current(),
    })


@editor_required
def effects_page(request):
    year = timezone.localdate().year
    return render(request, "gestion/effects.html", {
        "calendar": effects.calendar(year), "next_calendar": effects.calendar(year + 1),
        "active": effects.active(), "effects": effects.EFFECTS, "year": year,
        "preview": request.session.get("effects_preview"),
        "preview_labels": [str(effects.EFFECTS[c]) for c in request.session.get("effects_preview") or []],
    })
