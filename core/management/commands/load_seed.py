"""Charge le contenu repris de l'ancien site (dossier seed/) dans la base.

La commande peut être relancée : les éléments sont retrouvés par leur slug et mis à jour.
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from blog.models import Post
from core.models import Board, Member, Resource
from events.models import Event

SEED = Path(settings.BASE_DIR) / "seed"


def front_matter(text):
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    meta = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    return meta, match.group(2).strip()


def split_moment(value):
    """« 2024-03-28T20:00:00 » -> (date, time) ; « 2024-09-07 » -> (date, None)."""
    if "T" not in value:
        return datetime.fromisoformat(value).date(), None
    moment = datetime.fromisoformat(value)
    return moment.date(), moment.time()


def event_translations():
    """seed/translations/events.en.md : blocs « === slug » avec en-têtes « clé: valeur » et sections « --- body »."""
    text = (SEED / "translations" / "events.en.md").read_text(encoding="utf-8")
    out = {}
    for block in re.split(r"^=== ", text, flags=re.M)[1:]:
        slug, rest = block.split("\n", 1)
        head, *sections = re.split(r"^--- (\w+)\n", rest, flags=re.M)
        data = dict(line.split(": ", 1) for line in head.strip().splitlines())
        data.update({name: body.strip() for name, body in zip(sections[::2], sections[1::2])})
        out[slug.strip()] = data
    return out


class Command(BaseCommand):
    help = "Charge les événements, articles, ressources et l'équipe repris de l'ancien site, en français et en anglais."

    def handle(self, *args, **options):
        self.copy_media()
        with transaction.atomic():
            self.load_events()
            self.load_posts()
            self.load_resources()
            self.load_team()

    def copy_media(self):
        source = SEED / "media"
        for path in source.rglob("*"):
            if path.is_file():
                target = Path(settings.MEDIA_ROOT) / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(path, target)
        self.stdout.write("Médias copiés.")

    def load_events(self):
        english = event_translations()
        for item in json.loads((SEED / "events.json").read_text(encoding="utf-8")):
            start_date, start_time = split_moment(item["start"])
            end_date, end_time = split_moment(item["end"])
            if start_time is not None and start_time.hour == 0 and end_time and end_time.hour == 0:
                start_time = end_time = None  # « 00:00 → 00:00 » : journée(s) entière(s)
            if item["all_day"]:
                start_time = end_time = None
            en = english.get(item["slug"], {})
            Event.objects.update_or_create(slug=item["slug"], defaults={
                "title": item["title"],
                "types": f",{'rentree' if 'rentree' in item['slug'] or 'welcome-day' in item['slug'] else item['kind']},",
                "start_date": start_date,
                "start_time": start_time,
                "end_date": end_date if end_date != start_date else None,
                "end_time": end_time,
                "venue": item["venue"][:1].upper() + item["venue"][1:],
                "address": item["address"],
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "price": item["price"] or en.get("price_fr", ""),
                "registration_url": item["registration_url"],
                "poster": item["image"],
                # Les descriptions bilingues de l'ancien site sont séparées : body_fr ne garde que le français.
                "body": en.get("body_fr", item["body"]),
                "title_en": en.get("title", ""),
                "price_en": en.get("price", ""),
                "body_en": en.get("body", ""),
                "is_published": True,
            })
        missing = Event.objects.filter(title_en="").count()
        self.stdout.write(f"{Event.objects.count()} événements ({missing} sans version anglaise).")

    def load_posts(self):
        translated = json.loads((SEED / "translations" / "posts.en.json").read_text(encoding="utf-8"))
        for item in json.loads((SEED / "posts.json").read_text(encoding="utf-8")):
            published = datetime.fromisoformat(item["published_at"])
            en = item.get("en") or translated.get(item["slug"], {})
            Post.objects.update_or_create(slug=item["slug"], defaults={
                "title": item["title"],
                "legacy_slug": item["legacy_slug"],
                "legacy_slug_en": en.get("legacy_slug", ""),
                "status": Post.Status.PUBLISHED,
                "published_at": timezone.make_aware(published),
                "cover": item["cover"],
                "excerpt": item["excerpt"][:300],
                "body": item["body"],
                "title_en": en.get("title", ""),
                "excerpt_en": en.get("excerpt", "")[:300],
                "body_en": en.get("body", ""),
            })
        missing = Post.objects.filter(body_en="").count()
        self.stdout.write(f"{Post.objects.count()} articles ({missing} sans version anglaise).")

    def load_resources(self):
        for path in sorted((SEED / "resources").glob("*.md")):
            meta, body = front_matter(path.read_text(encoding="utf-8"))
            en_path = path.parent / "en" / path.name
            en_meta, en_body = front_matter(en_path.read_text(encoding="utf-8")) if en_path.exists() else ({}, "")
            if "image" in meta:
                image = settings.MEDIA_URL + meta["image"]
                body, en_body = body.replace("{image}", image), en_body.replace("{image}", image)
            Resource.objects.update_or_create(slug=path.stem, defaults={
                "title": meta["title"],
                "category": meta["category"],
                "order": int(meta.get("order", 0)),
                "summary": meta["summary"],
                "body": body,
                "title_en": en_meta.get("title", ""),
                "summary_en": en_meta.get("summary", ""),
                "body_en": en_body,
            })
        self.stdout.write(f"{Resource.objects.count()} ressources.")

    def load_team(self):
        data = json.loads((SEED / "team.json").read_text(encoding="utf-8"))
        roles_en = data["roles_en"]
        for entry in data["boards"]:
            board, _ = Board.objects.get_or_create(year=entry["year"])
            board.members.all().delete()
            for order, m in enumerate(entry["members"]):
                Member.objects.create(
                    board=board, order=order, name=m["name"], role=m["role"], role_en=roles_en.get(m["role"], ""),
                    about=m.get("about", ""), about_en=m.get("about_en", ""),
                    photo=m.get("photo", ""), linkedin=m.get("linkedin", ""),
                )
        self.stdout.write(f"{Board.objects.count()} bureaux, {Member.objects.count()} mandats.")
