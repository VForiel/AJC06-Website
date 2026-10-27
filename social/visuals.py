"""Visuels des événements, générés par le serveur (Pillow) : Instagram, Facebook, courriels, story à télécharger.

Avec affiche : l'affiche entière (jamais recadrée) sur fond nuit, puis un bandeau papier avec types, titre, date et lieu.
Sans affiche : le titre en grand sur fond nuit, filet mimosa, date et lieu.
Toujours : le logo de l'AJC06 et « ajc06.com ».

Les images sont mises en cache dans MEDIA_ROOT/visuels/ ; leur nom change dès que l'événement est modifié.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import translation
from PIL import Image, ImageDraw, ImageFont, ImageOps

from events.models import TYPE_LABELS

STATIC = Path(settings.BASE_DIR) / "static"
VERSION = 1  # à incrémenter quand le dessin change : tous les visuels sont régénérés

FORMATS = {
    "portrait": (1080, 1350),  # Instagram, Facebook
    "story": (1080, 1920),  # stories Instagram / Facebook
    "og": (1200, 630),  # aperçus de liens, courriels
}

PAPER, INK, MUTED = "#f7f4ec", "#0f1d2e", "#4a5563"
NIGHT, AZUR, MIMOSA, ON_NIGHT = "#0f1d2e", "#1460a6", "#f6c431", "#eef1ec"


@lru_cache(maxsize=32)
def font(name, size):
    files = {"display": "Archivo-CondensedBlack.ttf", "bold": "Archivo-Bold.ttf", "text": "Archivo-Regular.ttf"}
    return ImageFont.truetype(str(STATIC / "fonts" / "pdf" / files[name]), size)


def wrap(draw, text, f, width, max_lines):
    """Lignes d'au plus `width` px ; la dernière finit par « … » si le texte ne tient pas."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=f) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=f) > width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines


def fit(draw, text, name, sizes, width, max_lines):
    """Plus grande taille de police pour laquelle le texte tient en `max_lines` lignes."""
    for size in sizes:
        f = font(name, size)
        lines = wrap(draw, text, f, width, max_lines)
        if not lines[-1].endswith("…") or size == sizes[-1]:
            return f, lines
    return f, lines


def draw_lines(draw, x, y, lines, f, fill, leading=1.05):
    step = round(f.size * leading)
    for line in lines:
        draw.text((x, y), line, font=f, fill=fill)
        y += step
    return y


def emoji_free(text):
    """Les polices Archivo n'ont pas d'émojis : on les retire (avec les sélecteurs de variante et les liants)."""
    def keep(c):
        n = ord(c)
        return (n < 0x2600 or 0x2C00 <= n < 0x1F000) and not (0xFE00 <= n <= 0xFE0F or n == 0x200D)

    return " ".join("".join(c for c in text if keep(c)).split())


def labels(event):
    from core.templatetags.ajc import hours, when

    with translation.override("fr"):
        kinds = [str(event.other_type if c == "autre" and event.other_type else TYPE_LABELS.get(c, c))
                 for c in event.type_codes][:2]
        date = when(event).capitalize()
        time = hours(event)
    place = event.venue or event.address
    return {"kinds": " · ".join(kinds).upper(), "title": emoji_free(event.title), "date": date, "time": time,
            "place": place, "price": event.price}


@lru_cache(maxsize=4)
def logo_image(height):
    mark = Image.open(STATIC / "img" / "pdf" / "ajc06-logo.png").convert("RGBA")
    mark = mark.crop(mark.getbbox())  # le fichier a de larges marges transparentes
    return ImageOps.contain(mark, (height * 5, height))


def logo(img, x, y, height):
    mark = logo_image(height)
    img.paste(mark, (x, y), mark)
    return mark.width


def poster_image(event):
    try:
        with Image.open(event.poster.path) as src:
            return ImageOps.exif_transpose(src).convert("RGB")
    except (OSError, ValueError):
        return None


def render(event, fmt="portrait"):
    width, height = FORMATS[fmt]
    img = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(img)
    info = labels(event)
    poster = poster_image(event) if event.poster else None
    pad = 64 if fmt != "og" else 56

    if fmt == "og":  # affiche à gauche (ou aplat nuit), texte à droite
        left = round(width * 0.4)
        draw.rectangle((0, 0, left, height), fill=NIGHT)
        if poster:
            shown = ImageOps.contain(poster, (left - 40, height - 40))
            img.paste(shown, ((left - shown.width) // 2, (height - shown.height) // 2))
        else:
            f, lines = fit(draw, info["title"], "display", (96, 84, 72, 60), left - 2 * pad, 4)
            draw_lines(draw, pad, pad, lines, f, ON_NIGHT, 0.98)
        x, text_width, y = left + pad, width - left - 2 * pad, pad
    else:
        band = round(height * (0.36 if fmt == "portrait" else 0.3))
        top = height - band
        draw.rectangle((0, 0, width, top), fill=NIGHT)
        if poster:
            shown = ImageOps.contain(poster, (width - 2 * pad, top - 2 * pad))
            img.paste(shown, ((width - shown.width) // 2, (top - shown.height) // 2))
        else:
            f, lines = fit(draw, info["title"], "display", (150, 132, 116, 100, 88), width - 2 * pad, 5)
            step = round(f.size * 0.98)
            y0 = (top - step * len(lines)) // 2
            draw.rectangle((pad, y0 - 48, pad + 120, y0 - 36), fill=MIMOSA)
            draw_lines(draw, pad, y0, lines, f, ON_NIGHT, 0.98)
        x, text_width, y = pad, width - 2 * pad, top + 44

    if info["kinds"]:
        f = font("bold", 26)
        w = draw.textlength(info["kinds"], font=f)
        draw.rounded_rectangle((x, y, x + w + 32, y + 46), radius=8, fill=MIMOSA)
        draw.text((x + 16, y + 9), info["kinds"], font=f, fill=INK)
        y += 70
    if poster:  # sans affiche, le titre est déjà en grand dans l'aplat
        f, lines = fit(draw, info["title"], "display", (76, 68, 60, 52), text_width, 2 if fmt != "og" else 3)
        y = draw_lines(draw, x, y, lines, f, INK, 1.0) + 12
    f = font("bold", 34 if fmt != "og" else 30)
    y = draw_lines(draw, x, y, wrap(draw, f"{info['date']} · {info['time']}", f, text_width, 2), f, AZUR, 1.2)
    f = font("text", 32 if fmt != "og" else 28)
    details = " · ".join(p for p in (info["place"], info["price"]) if p)
    if details:
        draw_lines(draw, x, y + 4, wrap(draw, details, f, text_width, 2), f, MUTED, 1.2)

    # Pied : logo et adresse du site
    foot = 84 if fmt != "og" else 64
    f = font("bold", 28)
    site = "ajc06.com"
    fy = height - pad // 2 - foot - 8
    logo(img, x, fy, foot)
    draw.text((width - pad - draw.textlength(site, font=f), fy + (foot - 28) // 2 - 2), site, font=f, fill=INK)
    return img


def cache_key(event, fmt):
    raw = f"{VERSION}|{fmt}|{event.pk}|{event.updated_at.isoformat()}|{event.poster.name if event.poster else ''}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def visual_path(event, fmt):
    """Chemin du visuel (généré au besoin), en JPEG : seul format accepté par l'API Instagram."""
    folder = Path(settings.MEDIA_ROOT) / "visuels" / str(event.pk)
    target = folder / f"{fmt}-{cache_key(event, fmt)}.jpg"
    if not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"{fmt}-*.jpg"):
            old.unlink(missing_ok=True)
        tmp = target.with_suffix(".tmp")
        render(event, fmt).save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
        tmp.replace(target)
    return target


def visual_url(event, fmt):
    path = visual_path(event, fmt)
    return f"{settings.MEDIA_URL}{path.relative_to(settings.MEDIA_ROOT).as_posix()}"
