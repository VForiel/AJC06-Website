import smtplib
import socket
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.core.mail import EmailMessage
from django.db import transaction
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
from siteconfig.forms import SiteConfigForm, TestEmailForm, snapshot
from siteconfig.mail import backend_for
from siteconfig.models import ConfigChange, SiteConfig

from .forms import EventForm, PostForm, UploadForm

User = get_user_model()


def smtp_error_message(exc):
    """Message compréhensible pour les erreurs d'envoi les plus courantes."""
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected)):
        return ("Le serveur a refusé l'identifiant ou le mot de passe (Gmail coupe la connexion dans ce cas). "
                "Avec Google : identifiant = vrai compte (pas un alias), validation en deux étapes activée et "
                "mot de passe d'application de 16 lettres.")
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionRefusedError)):
        return "Serveur injoignable : vérifie le nom du serveur, le port et la sécurité (465 = SSL, 587 = STARTTLS)."
    return f"{exc.__class__.__name__} — {exc}"


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
        "items": Report.objects.select_related("reporter__profile", "event", "profile", "photo",
                                             "comment__event", "comment__author__profile")[:200],
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

    error = helloasso.ensure_synced(event)
    if error:
        messages.warning(request, f"Liste HelloAsso non mise à jour : {error}")
    return render(request, "gestion/dossier.html", {
        "event": event, "dossier": item, "form": form, "prev": prev, "real": real,
        "attach_form": AttachmentForm(), "attachments": item.attachments.all(),
        "forecast_totals": item.totals("prev"), "real_totals": item.totals("reel"),
        "participants": participants(event), "helloasso_link": helloasso.parse_link(event.registration_url),
        "helloasso_problem": helloasso.problem(event),
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
    helloasso.ensure_synced(event)  # liste des participant·es à jour, même pour une campagne clôturée
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
            messages.error(request, helloasso.problem(event) or "Pas de lien HelloAsso sur cet événement.")
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


# Réglages du site (à la place du .env) ------------------------------------


def superuser_required(view):
    """Réglages techniques (serveur mail, HelloAsso) : réservés aux superutilisateurs."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("gestion:login"))
        if not (request.user.is_active and request.user.is_superuser):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@superuser_required
def site_settings(request):
    config = SiteConfig.get()
    before = snapshot(config)
    form = SiteConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            changed = form.changed_labels(before)
            if changed:
                ConfigChange.objects.create(user=request.user, fields=", ".join(changed))
        messages.success(request, "Réglages enregistrés." if changed else "Aucun changement.")
        return redirect("gestion:settings")
    from community.google import redirect_uri as google_redirect

    return render(request, "gestion/settings.html", {
        "google_redirect": google_redirect(),
        "form": form,
        "config": config,
        "test_form": TestEmailForm(initial={"to": request.user.email}),
        "changes": ConfigChange.objects.select_related("user")[:10],
    })


@superuser_required
@require_POST
def test_email(request):
    form = TestEmailForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Adresse de test invalide.")
        return redirect("gestion:settings")
    config = SiteConfig.get()
    if not config.smtp_ready:
        messages.warning(request, "Aucun serveur SMTP réglé : le courriel n'est parti que dans les journaux du site.")
    message = EmailMessage(
        "AJC06 : courriel de test",
        "Ce message confirme que le site sait envoyer des courriels avec les réglages actuels.\n\n— ajc06.com",
        config.from_email,
        [form.cleaned_data["to"]],
        connection=backend_for(config),
    )
    try:
        message.send()
    except (smtplib.SMTPException, OSError, socket.timeout) as exc:
        messages.error(request, f"Échec de l'envoi : {smtp_error_message(exc)}")
    else:
        if config.smtp_ready:
            messages.success(request, f"Courriel de test envoyé à {form.cleaned_data['to']}. Vérifie aussi les indésirables.")
    return redirect("gestion:settings")


# Diffusion des événements (Instagram, Facebook, courriel) -------------------


@editor_required
def diffuse(request, pk):
    from social.forms import DiffusionForm
    from social.models import Post
    from social.service import claim, send
    from social.visuals import visual_url

    event = get_object_or_404(Event, pk=pk)
    config = SiteConfig.get()
    form = DiffusionForm(request.POST or None, event=event, config=config)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        at = data["scheduled_at"] if data["when"] == "later" else timezone.now()
        posts = [Post.objects.create(
            event=event, network=n, text=data[f"text_{n}"].strip(), scheduled_at=at, created_by=request.user,
            language=data["language"],
            subject=data["subject"].strip() if n == "email" else "", recipients=data["recipients"] if n == "email" else "",
        ) for n in data["chosen"]]
        if data["when"] == "now":
            for post in posts:
                if claim(post.pk):
                    send(post)
            done = [p for p in posts if Post.objects.get(pk=p.pk).status == Post.Status.PUBLISHED]
            if len(done) == len(posts):
                messages.success(request, f"Diffusé : {', '.join(p.get_network_display() for p in posts)}.")
            else:
                messages.warning(request, "Certaines diffusions ont échoué : détail ci-dessous.")
        else:
            messages.success(request, f"Programmé le {timezone.localtime(at):%d/%m à %H:%M} ({len(posts)} canal·aux).")
        return redirect("gestion:diffuse", pk=event.pk)
    return render(request, "gestion/diffuse.html", {
        "event": event, "form": form, "config": config,
        "previews": [(lang, label, visual_url(event, fmt, lang)) for lang in ("fr", "en") for fmt, label in
                     (("portrait", "Instagram, Facebook"), ("og", "Courriel"), ("story", "Story"))],
        "prefills": form.prefills(),
        "posts": event.posts.select_related("created_by")[:30],
    })


@editor_required
def diffusion_list(request):
    from django.core.paginator import Paginator

    from social.models import Post

    items = Post.objects.select_related("event", "created_by").order_by("-scheduled_at")
    return render(request, "gestion/diffusions.html", {"page": Paginator(items, 50).get_page(request.GET.get("page"))})


@editor_required
@require_POST
def diffusion_action(request, pk):
    from social.models import Post

    post = get_object_or_404(Post, pk=pk)
    action = request.POST.get("action")
    if action == "cancel" and post.status == Post.Status.SCHEDULED:
        post.status = Post.Status.CANCELLED
        post.save(update_fields=["status"])
        messages.success(request, "Diffusion annulée.")
    elif action == "retry" and post.status in (Post.Status.FAILED, Post.Status.CANCELLED):
        post.status, post.attempts, post.scheduled_at = Post.Status.SCHEDULED, 0, timezone.now()
        post.save(update_fields=["status", "attempts", "scheduled_at"])
        messages.success(request, "Relancée : elle part dans les 5 minutes.")
    target = request.POST.get("next", "")
    return redirect(target if target.startswith("/gestion/") else "gestion:diffusions")


@superuser_required
@require_POST
def test_network(request, network):
    from social.networks import check

    config = SiteConfig.get()
    if network not in ("facebook", "instagram") or not config.network_ready(network):
        messages.warning(request, "Active le réseau et enregistre ses identifiants avant de le tester.")
    else:
        ok, message = check(network, config)
        config.social_check = {**config.social_check, network: {"ok": ok, "message": message}}
        config.social_checked_at = timezone.now()
        config.save(update_fields=["social_check", "social_checked_at"])
        (messages.success if ok else messages.error)(request, f"{network.capitalize()} : {message}")
    return redirect(reverse("gestion:settings") + "#diffusion")
