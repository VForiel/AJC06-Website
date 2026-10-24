"""Normalisation des images téléversées : orientation, taille maximale, WebP."""

import io
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 40_000_000  # ~ 8000 × 5000 : au-delà, la conversion mobiliserait trop de mémoire
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def validate_image(uploaded):
    """Refuse avant enregistrement les fichiers trop lourds ou aux dimensions démesurées (bombe de décompression)."""
    if uploaded.size > MAX_BYTES:
        raise ValidationError(_("Image trop lourde (12 Mo maximum)."))
    try:
        uploaded.seek(0)
        width, height = Image.open(uploaded).size  # ne lit que l'en-tête
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ValidationError(_("Image illisible ou trop grande. Essaie en JPEG ou PNG."))
    finally:
        uploaded.seek(0)
    if width * height > MAX_PIXELS:
        raise ValidationError(_("Image trop grande (40 mégapixels maximum)."))


def to_webp(uploaded, max_side=MAX_SIDE):
    """Renvoie un ContentFile WebP à partir d'un fichier image téléversé."""
    img = Image.open(uploaded)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82, method=6)
    name = Path(getattr(uploaded, "name", "image")).stem[:60] + ".webp"
    return ContentFile(buf.getvalue(), name=name)


def normalize_field(instance, field_name, max_side=MAX_SIDE):
    """Convertit le fichier d'un ImageField s'il vient d'être téléversé (pas encore enregistré)."""
    field = getattr(instance, field_name)
    if field and not field._committed:
        field.file.seek(0)
        webp = to_webp(field.file, max_side)
        field.save(webp.name, webp, save=False)
