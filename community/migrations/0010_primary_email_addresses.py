from django.db import migrations


def primary_addresses(apps, schema_editor):
    """Adresse principale de chaque compte : confirmée pour les comptes déjà actifs et validés (lien ou bureau)."""
    User = apps.get_model("auth", "User")
    EmailAddress = apps.get_model("community", "EmailAddress")
    taken = set()
    for user in User.objects.exclude(email="").select_related("profile").order_by("date_joined"):
        email = user.email.strip().lower()
        profile = getattr(user, "profile", None)
        confirmed = user.is_active and bool(profile and profile.email_confirmed) and email not in taken
        if confirmed:
            taken.add(email)
        EmailAddress.objects.get_or_create(user=user, email=email, defaults={"confirmed": confirmed})


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("community", "0009_attendance_guests_attendance_via_helloasso_and_more"),
    ]

    operations = [migrations.RunPython(primary_addresses, migrations.RunPython.noop)]
