from django.db import migrations
from django.utils.text import slugify


def create_profiles(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Profile = apps.get_model("community", "Profile")
    taken = set(Profile.objects.values_list("handle", flat=True))
    for user in User.objects.filter(profile__isnull=True):
        name = f"{user.first_name} {user.last_name}".strip() or user.username.split("@")[0]
        base = slugify(name)[:50] or "membre"
        handle, n = base, 2
        while handle in taken:
            handle, n = f"{base}-{n}", n + 1
        taken.add(handle)
        Profile.objects.create(user=user, display_name=name, handle=handle)


class Migration(migrations.Migration):
    dependencies = [("community", "0001_initial")]
    operations = [migrations.RunPython(create_profiles, migrations.RunPython.noop)]
