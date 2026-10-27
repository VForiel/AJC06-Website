import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from events.models import Event

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator

from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from core.security import client_ip, throttled
from projets.models import SupportRequest

from . import confirmation

from .forms import (AlertForm, CommentForm, CommunityEventForm, DeleteAccountForm, EmailForm, PhotoForm, ProfileForm, ReportForm, SignupForm,
                    SupportRequestForm)
from .models import (AlertPreference, Attendance, Comment, Friendship, Notification, Photo, Profile, Report, friends_of,
                     relation)

SIGNUPS_PER_HOUR = 5
EVENTS_PER_DAY = 5

logger = logging.getLogger(__name__)


def profile_of(user):
    """Profil du membre, créé à la volée pour les comptes antérieurs à l'espace membres (bureau, admin)."""
    profile = getattr(user, "profile", None)
    if profile is None:
        profile = Profile.objects.create(user=user, display_name=user.get_full_name() or user.username.split("@")[0])
    return profile


def notify(recipient, actor, verb, event=None, photo=None):
    if recipient.pk != actor.pk:
        Notification.objects.create(recipient=recipient, actor=actor, verb=verb, event=event, photo=photo)


def notify_board(actor, verb, event=None):
    for staff in get_user_model().objects.filter(is_staff=True, is_active=True):
        notify(staff, actor, verb, event)


# Compte ---------------------------------------------------------------------


def signup(request):
    if request.user.is_authenticated:
        return redirect("community:me")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if form.is_spam() or throttled(f"signup:{client_ip(request)}", SIGNUPS_PER_HOUR, 3600):
            messages.error(request, _("Trop d'inscriptions depuis cette connexion, réessaie plus tard."))
            return redirect("community:signup")
        if confirmation.required():
            user = form.save(confirm=True)
            by_board = confirmation.mode() == "bureau"
            if not by_board:
                confirmation.send(user)
            return render(request, "community/confirm_sent.html", {"email": user.email, "by_board": by_board})
        user = form.save()
        login(request, user, backend="community.auth.EmailBackend")
        messages.success(request, _("Bienvenue ! Complète ton profil pour que les autres doctorant·es te trouvent."))
        return redirect("community:settings")
    return render(request, "community/signup.html", {"form": form})


def confirm(request, uidb64, token):
    try:
        user = get_user_model().objects.select_related("profile").get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (ValueError, TypeError, OverflowError, get_user_model().DoesNotExist):
        user = None
    if user is None or user.profile.email_confirmed or not confirmation.tokens.check_token(user, token):
        messages.error(request, _("Ce lien de confirmation n'est plus valable. Connecte-toi, ou demande un nouveau lien."))
        return redirect("community:login")
    confirmation.approve(user)
    login(request, user, backend="community.auth.EmailBackend")
    messages.success(request, _("Adresse confirmée, bienvenue ! Complète ton profil pour que les autres doctorant·es te trouvent."))
    return redirect("community:settings")



class PasswordResetView(auth_views.PasswordResetView):
    """Mot de passe oublié, limité pour qu'on ne puisse pas inonder une boîte mail de liens."""

    template_name = "community/password_reset.html"
    email_template_name = "community/password_reset_email.txt"
    subject_template_name = "community/password_reset_subject.txt"
    success_url = reverse_lazy("community:password_reset_done")

    def form_valid(self, form):
        email = form.cleaned_data["email"].strip().lower()
        if throttled(f"reset:{client_ip(self.request)}", 5, 3600) or throttled(f"reset-mail:{email}", 3, 3600):
            return redirect(self.success_url)  # même page de confirmation : rien n'est révélé
        return super().form_valid(form)

@require_POST
def confirm_resend(request):
    email = request.POST.get("email", "").strip().lower()
    if not throttled(f"confirm:{client_ip(request)}", 5, 3600):
        user = get_user_model().objects.filter(email__iexact=email, is_active=False,
                                               profile__email_confirmed=False).select_related("profile").first()
        if user:
            confirmation.send(user)
    # Même réponse que le compte existe ou non : on ne révèle pas les adresses inscrites.
    messages.success(request, _("Si un compte en attente existe avec cette adresse, un nouveau lien vient d'être envoyé."))
    return render(request, "community/confirm_sent.html", {"email": email})


@login_required
def me(request):
    return redirect(profile_of(request.user).get_absolute_url())


@login_required
def settings_view(request):
    profile = profile_of(request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile, prefix="p")
    email_form = EmailForm(request.user, initial={"email": request.user.email}, prefix="e")
    if request.method == "POST" and "save_profile" in request.POST and form.is_valid():
        form.save()  # toujours valide : les champs refusés sont écartés (PartialSaveMixin)
        if form.skipped:
            logger.info("Profil de l'utilisateur %s : champs écartés %s", request.user.pk, ", ".join(form.skipped))
            messages.warning(request, _("Profil enregistré, sauf ces champs, laissés tels quels : %(fields)s.")
                             % {"fields": form.skipped_summary()})
        else:
            messages.success(request, _("Profil enregistré."))
        return redirect("community:settings")
    if request.method == "POST" and "save_email" in request.POST:
        email_form = EmailForm(request.user, request.POST, prefix="e")
        if email_form.is_valid():
            request.user.email = email_form.cleaned_data["email"]
            if "@" in request.user.username:
                request.user.username = request.user.email
            request.user.save(update_fields=["email", "username"])
            messages.success(request, _("Adresse mise à jour."))
            return redirect("community:settings")
    return render(request, "community/settings.html", {"form": form, "email_form": email_form, "profile": profile})


@login_required
def alerts(request):
    """Filtres et alertes : les types et l'origine des événements qui m'intéressent, et l'alerte qui va avec."""
    pref, _created = AlertPreference.objects.get_or_create(user=request.user)
    form = AlertForm(request.POST or None, instance=pref)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Alerte activée : tu seras prévenu·e des prochains événements.") if pref.active
                         else _("Filtre enregistré (alerte désactivée)."))
        return redirect("community:alerts")
    query = [("type", code) for code in pref.type_codes] + ([("par", pref.origin)] if pref.origin else [])
    from urllib.parse import urlencode

    return render(request, "community/alerts.html", {
        "form": form, "pref": pref, "agenda_query": urlencode(query),
        "matching": pref.matching(Event.objects.published().upcoming()).count(),
    })


@login_required
def delete_account(request):
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        user.delete()  # supprime profil, amitiés, participations ; ses événements restent sans organisateur
        messages.success(request, _("Ton compte et tes données ont été supprimés."))
        return redirect("core:home")
    return render(request, "community/delete_account.html", {"form": form})


# Membres --------------------------------------------------------------------


@login_required
def members(request):
    q = request.GET.get("q", "").strip()
    school = request.GET.get("ed", "")
    people = Profile.objects.select_related("user").filter(user__is_active=True)
    if q:
        people = people.filter(Q(display_name__icontains=q) | Q(discipline__icontains=q) | Q(lab__icontains=q)
                               | Q(interests__icontains=q) | Q(thesis_title__icontains=q))
    if school in Profile.School.values:
        people = people.filter(doctoral_school=school)
    me_profile = profile_of(request.user)
    suggestions = []
    if not q and not school and me_profile.doctoral_school:
        known = {u.pk for u in friends_of(request.user)} | {request.user.pk}
        suggestions = (Profile.objects.filter(doctoral_school=me_profile.doctoral_school, user__is_active=True)
                       .exclude(user__pk__in=known)[:6])
    return render(request, "community/members.html", {
        "people": people[:120], "q": q, "school": school, "schools": Profile.School.choices,
        "suggestions": suggestions,
    })


def profile(request, handle):
    person = get_object_or_404(Profile.objects.select_related("user"), handle=handle, user__is_active=True)
    if not person.visible_to(request.user):
        return render(request, "community/profile_private.html", {"person": person}, status=403)
    rel = relation(request.user, person.user)
    today = timezone.localdate()
    going = []
    photos = Photo.objects.filter(is_hidden=False).filter(Q(tagged=person.user) | Q(uploader=person.user)).distinct()[:8]
    if person.show_events or rel == "self":
        going = (Event.objects.published().upcoming().filter(attendances__user=person.user)
                 .exclude(organizer=person.user).select_related("organizer__profile")[:6])
    organized = Event.objects.published().filter(organizer=person.user).order_by("-start_date")[:6]
    went = []
    if person.past_events_visible_to(rel):
        went = (Event.objects.published().past().filter(attendances__user=person.user)
                .select_related("organizer__profile")[:12])
    return render(request, "community/profile.html", {
        "person": person, "rel": rel, "friends": friends_of(person.user)[:12],
        "friend_count": friends_of(person.user).count(), "going": going, "organized": organized, "today": today,
        "went": went,
        "photos": photos, "show_contacts": person.has_contacts and person.contacts_visible_to(request.user, rel),
    })


# Amis -----------------------------------------------------------------------


@login_required
def friends(request):
    received = Friendship.objects.filter(to_user=request.user, accepted=False).select_related("from_user__profile")
    sent = Friendship.objects.filter(from_user=request.user, accepted=False).select_related("to_user__profile")
    return render(request, "community/friends.html", {
        "friends": friends_of(request.user), "received": received, "sent": sent,
    })


@login_required
@require_POST
def friend_action(request, handle, action):
    other = get_object_or_404(Profile, handle=handle).user
    if other.pk == request.user.pk:
        raise Http404
    link = Friendship.objects.between(request.user, other).first()
    if action == "add" and not link:
        Friendship.objects.create(from_user=request.user, to_user=other)
        notify(other, request.user, Notification.Verb.FRIEND_REQUEST)
        messages.success(request, _("Demande envoyée."))
    elif action == "accept" and link and not link.accepted and link.to_user_id == request.user.pk:
        link.accepted = True
        link.save(update_fields=["accepted"])
        notify(other, request.user, Notification.Verb.FRIEND_ACCEPTED)
        messages.success(request, _("Vous êtes maintenant amis."))
    elif action in ("decline", "cancel", "remove") and link:
        link.delete()
    return redirect(request.POST.get("next") or other.profile.get_absolute_url())


# Notifications ----------------------------------------------------------------


@login_required
def notifications(request):
    items = list(request.user.notifications.select_related("actor__profile", "event")[:60])
    request.user.notifications.filter(read=False).update(read=True)
    return render(request, "community/notifications.html", {"items": items})


# Événements communautaires ------------------------------------------------------


@login_required
def event_new(request):
    form = CommunityEventForm(request.POST or None, request.FILES or None)
    support_form = SupportRequestForm(request.POST or None, prefix="s")
    wants_support = request.method == "POST" and request.POST.get("request_support")
    if request.method == "POST" and form.is_valid() and (not wants_support or support_form.is_valid()):
        if throttled(f"events:{request.user.pk}", EVENTS_PER_DAY, 86400):
            messages.error(request, _("Tu as déjà proposé beaucoup d'événements aujourd'hui, réessaie demain."))
            return redirect("events:list")
        event = form.save(commit=False)
        event.is_community = True
        event.organizer = request.user
        # Avec demande de soutien : pas publié tant que le bureau n'a pas répondu.
        event.is_published = not wants_support
        event.save()
        Attendance.objects.get_or_create(event=event, user=request.user)
        if wants_support:
            support = support_form.save(commit=False)
            support.event, support.requester = event, request.user
            support.save()
            notify_board(request.user, Notification.Verb.SUPPORT, event)
            messages.success(request, _("Demande envoyée au bureau. Tu recevras une notification dès qu'il aura répondu ; d'ici là, l'événement n'est visible que par toi."))
        else:
            messages.success(request, _("C'est en ligne ! Invite tes amis depuis la page de l'événement."))
        return redirect(event.get_absolute_url())
    return render(request, "community/event_form.html", {"form": form, "support_form": support_form})


def _own_event(request, slug):
    event = get_object_or_404(Event, slug=slug, is_community=True)
    if event.organizer_id != request.user.pk and not request.user.is_staff:
        return None
    return event


@login_required
def event_edit(request, slug):
    event = _own_event(request, slug)
    if event is None:
        return HttpResponseForbidden()
    form = CommunityEventForm(request.POST or None, request.FILES or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Événement mis à jour."))
        return redirect(event.get_absolute_url())
    return render(request, "community/event_form.html", {"form": form, "event": event})


@login_required
def event_delete(request, slug):
    event = _own_event(request, slug)
    if event is None:
        return HttpResponseForbidden()
    if request.method == "POST":
        event.delete()
        messages.success(request, _("Événement supprimé."))
        return redirect("events:list")
    return render(request, "community/event_delete.html", {"event": event})


@login_required
@require_POST
def attend(request, slug):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    attendance = Attendance.objects.filter(event=event, user=request.user).first()
    if attendance:
        attendance.delete()
    elif not event.is_upcoming:
        messages.error(request, _("Cet événement est passé."))
    elif event.is_full:
        messages.error(request, _("Désolé, c'est complet."))
    else:
        Attendance.objects.create(event=event, user=request.user)
        if event.organizer_id:
            notify(event.organizer, request.user, Notification.Verb.ATTENDING, event)
    return redirect(event.get_absolute_url() + "#participants")


@login_required
@require_POST
def invite(request, slug):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    allowed = {u.pk: u for u in friends_of(request.user)}
    count = 0
    for pk in request.POST.getlist("friends"):
        friend = allowed.get(int(pk)) if pk.isdigit() else None
        if friend and not Notification.objects.filter(recipient=friend, actor=request.user, verb="invite", event=event).exists():
            notify(friend, request.user, Notification.Verb.INVITE, event)
            count += 1
    messages.success(request, _("Invitation envoyée.") if count == 1 else _("%(n)s invitations envoyées.") % {"n": count})
    return redirect(event.get_absolute_url() + "#participants")


AUTO_HIDE_REPORTS = 3


@login_required
def report(request, kind, key):
    if kind == "evenement":
        target = get_object_or_404(Event, slug=key)
    elif kind == "photo":
        target = get_object_or_404(Photo, pk=key)
    elif kind == "commentaire":
        target = get_object_or_404(Comment.objects.select_related("event"), pk=key if key.isdigit() else 0, is_hidden=False)
    elif kind == "profil":
        target = get_object_or_404(Profile, handle=key)
    else:
        raise Http404
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        Report.objects.create(reporter=request.user, reason=form.cleaned_data["reason"],
                              event=target if kind == "evenement" else None,
                              photo=target if kind == "photo" else None,
                              comment=target if kind == "commentaire" else None,
                              profile=target if kind == "profil" else None)
        if kind == "commentaire":
            reporters = Report.objects.filter(comment=target, handled=False).values("reporter").distinct().count()
            if reporters >= AUTO_HIDE_REPORTS:  # masqué en attendant le bureau
                target.is_hidden = True
                target.save(update_fields=["is_hidden"])
        messages.success(request, _("Merci, le bureau va regarder ça."))
        return redirect(target.get_absolute_url())
    return render(request, "community/report.html", {"form": form, "target": target})


# Photos -------------------------------------------------------------------------


def photos(request):
    items = Photo.objects.filter(is_hidden=False).select_related("event", "uploader__profile")
    page = Paginator(items, 24).get_page(request.GET.get("page"))
    return render(request, "community/photos.html", {"page": page})


def photo(request, pk):
    item = get_object_or_404(Photo.objects.select_related("event", "uploader__profile"), pk=pk, is_hidden=False)
    tagged = item.tagged.filter(is_active=True).select_related("profile")
    return render(request, "community/photo.html", {
        "photo": item, "tagged": tagged,
        "is_tagged": request.user.is_authenticated and tagged.filter(pk=request.user.pk).exists(),
        "can_delete": request.user.is_authenticated and (item.uploader_id == request.user.pk or request.user.is_staff),
    })


@login_required
def photo_new(request):
    initial = {}
    slug = request.GET.get("evenement")
    if slug:
        initial["event"] = Event.objects.published().filter(slug=slug).first()
    form = PhotoForm(request.user, request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        count = len(data["files"]) + len(data["links"])
        if throttled(f"photos:{request.user.pk}", 60, 86400, cost=count):
            messages.error(request, _("Beaucoup de photos aujourd'hui : réessaie demain."))
            return redirect("community:photos")
        common = {"uploader": request.user, "consent": True, "event": data["event"], "caption": data["caption"].strip()}
        items = [Photo(kind=Photo.Kind.PHOTO if kind == "photo" else Photo.Kind.VIDEO,
                       **({"image": f} if kind == "photo" else {"video": f}), **common) for kind, f in data["files"]]
        items += [Photo(kind=Photo.Kind.LINK, url=link, **common) for link in data["links"]]
        tagged = form.tagged_users()
        for item in items:
            item.save()
            item.tagged.add(*tagged)
        for user in tagged:  # une seule notification par personne, même pour plusieurs photos
            notify(user, request.user, Notification.Verb.PHOTO_TAG, data["event"], photo=items[0])
        messages.success(request, _("Merci ! %(n)s élément(s) ajouté(s).") % {"n": count})
        if data["event"]:
            return redirect(data["event"].get_absolute_url() + "#photos")
        return redirect(items[0].get_absolute_url() if count == 1 else "community:photos")
    return render(request, "community/photo_form.html", {"form": form})


@login_required
@require_POST
def photo_untag(request, pk):
    item = get_object_or_404(Photo, pk=pk)
    item.tagged.remove(request.user)
    messages.success(request, _("Tu n'es plus identifié·e sur cette photo. Si tu veux qu'elle soit retirée, signale-la."))
    return redirect(item.get_absolute_url())


@login_required
@require_POST
def photo_delete(request, pk):
    item = get_object_or_404(Photo, pk=pk)
    if item.uploader_id != request.user.pk and not request.user.is_staff:
        return HttpResponseForbidden()
    item.delete()
    messages.success(request, _("Photo supprimée."))
    return redirect("community:photos")


@login_required
@require_POST
def event_publish(request, slug):
    """Après un refus de soutien, l'organisateur·rice peut publier sa sortie telle quelle."""
    event = get_object_or_404(Event, slug=slug, is_community=True, organizer=request.user)
    event.is_published = True
    event.save(update_fields=["is_published"])
    messages.success(request, _("C'est en ligne ! Invite tes amis depuis la page de l'événement."))
    return redirect(event.get_absolute_url())


# Commentaires -------------------------------------------------------------------


@login_required
@require_POST
def comment_new(request, slug):
    event = get_object_or_404(Event.objects.published(), slug=slug)
    form = CommentForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Écris quelques mots (2 000 caractères au plus)."))
    elif throttled(f"comments:{request.user.pk}", 30, 3600):
        messages.error(request, _("Beaucoup de commentaires en peu de temps : réessaie plus tard."))
    else:
        comment = Comment.objects.create(event=event, author=request.user, body=form.cleaned_data["body"].strip())
        messages.success(request, _("Commentaire publié."))
        return redirect(comment.get_absolute_url())
    return redirect(event.get_absolute_url() + "#commentaires")


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("event"), pk=pk)
    if comment.author_id != request.user.pk and not request.user.is_staff:
        raise Http404
    comment.delete()
    messages.success(request, _("Commentaire supprimé."))
    target = request.POST.get("next", "")
    if target.startswith("/gestion/"):
        return redirect(target)
    return redirect(comment.event.get_absolute_url() + "#commentaires")
