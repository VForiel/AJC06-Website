from django.db import migrations


def resync(apps, schema_editor):
    """Les billets déjà lus n'ont pas d'adresse : leurs campagnes seront relues (cron ou première visite)."""
    Event = apps.get_model("events", "Event")
    Event.objects.filter(helloasso_tickets__isnull=False).update(helloasso_synced_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("projets", "0002_helloassoticket_email_helloassounlink"),
    ]

    operations = [migrations.RunPython(resync, migrations.RunPython.noop)]
