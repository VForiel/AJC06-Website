"""Billets HelloAsso -> participations des membres du site.

Un billet est relié au compte qui a confirmé son adresse (celle du participant, sinon celle du payeur), si le
membre l'accepte (réglage « relier mes inscriptions HelloAsso », coché par défaut). Plusieurs billets pris avec la
même adresse : la personne vient accompagnée, « +1 » par billet en plus ; le compteur public reste le nombre de
billets. Une participation retirée par la personne n'est pas recréée (HelloAssoUnlink).
"""

from collections import Counter, defaultdict

from community.models import Attendance, EmailAddress, Notification

from .models import HelloAssoTicket, HelloAssoUnlink


def owners(emails):
    """{adresse: id du compte} pour les adresses confirmées des membres qui acceptent la liaison."""
    rows = EmailAddress.objects.filter(email__in=emails, confirmed=True, user__is_active=True,
                                       user__profile__link_helloasso=True).values_list("email", "user_id")
    return dict(rows)


def link_event(event):
    """Met les participations « via HelloAsso » de l'événement en accord avec ses billets."""
    tickets = Counter(HelloAssoTicket.objects.filter(event=event).exclude(email="").values_list("email", flat=True))
    found = owners(list(tickets))
    per_user = defaultdict(int)
    for email, n in tickets.items():
        if email in found:
            per_user[found[email]] += n
    for user_id in HelloAssoUnlink.objects.filter(event=event).values_list("user_id", flat=True):
        per_user.pop(user_id, None)

    first_time = []
    for user_id, n in per_user.items():
        attendance, created = Attendance.objects.get_or_create(
            event=event, user_id=user_id, defaults={"via_helloasso": True, "guests": n - 1})
        if created:
            first_time.append(user_id)
        elif attendance.guests != n - 1:
            attendance.guests = n - 1
            attendance.save(update_fields=["guests"])
    # Billet remboursé, adresse retirée, liaison refusée : la participation HelloAsso disparaît
    Attendance.objects.filter(event=event, via_helloasso=True).exclude(user_id__in=per_user).delete()
    Attendance.objects.filter(event=event, via_helloasso=False, guests__gt=0).exclude(user_id__in=per_user).update(guests=0)

    # À la première participation reliée, la personne est prévenue (et peut la retirer depuis la page)
    already = set(Notification.objects.filter(recipient_id__in=first_time, verb=Notification.Verb.HELLOASSO)
                  .values_list("recipient_id", flat=True))
    Notification.objects.bulk_create([Notification(recipient_id=uid, verb=Notification.Verb.HELLOASSO, event=event)
                                      for uid in first_time if uid not in already])
    return len(per_user)


def link_user(user):
    """Après l'ajout ou la confirmation d'une adresse, ou un changement de réglage : relie (ou délie) ses billets."""
    emails = list(EmailAddress.objects.filter(user=user).values_list("email", flat=True))
    events = set(HelloAssoTicket.objects.filter(email__in=emails).values_list("event_id", flat=True))
    events |= set(Attendance.objects.filter(user=user, via_helloasso=True).values_list("event_id", flat=True))
    from events.models import Event

    for event in Event.objects.filter(pk__in=events):
        link_event(event)


def unlink(user, event):
    """La personne retire une participation venue de HelloAsso : elle ne revient plus."""
    if HelloAssoTicket.objects.filter(event=event, email__in=EmailAddress.objects.filter(user=user).values("email")).exists():
        HelloAssoUnlink.objects.get_or_create(user=user, event=event)


def relink(user, event):
    """« J'y vais » redonné à la main : on oublie le retrait, les +1 HelloAsso reviennent."""
    HelloAssoUnlink.objects.filter(user=user, event=event).delete()
    link_event(event)
