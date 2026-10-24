"""Fige le contenu de l'ancien site WordPress (ajc06.com) dans seed/.

Usage : python scripts/scrape_wordpress.py <dossier-cache>

Le dossier de cache garde les réponses HTTP brutes pour pouvoir relancer le script sans tout retélécharger.
Sorties : seed/events.json, seed/posts.json et les fichiers dans seed/media/.
Les fiches ressources, l'équipe et les pages fixes sont reprises à la main (seed/resources/*.md, seed/team.json).
"""

import hashlib
import html
import io
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify
from PIL import Image

SITE = "https://ajc06.com"
ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
MEDIA = SEED / "media"
MAX_SIDE = 1600

# Type de chaque événement, choisi à la lecture des titres (voir events.models.Event.Kind).
KINDS = {
    "assemblee-generale": "asso",
    "camp": "camp",
    "observatoire": "visite",
    "rothschild": "visite",
    "opera": "culture",
    "theatre": "culture",
    "cinema": "culture",
    "noir": "culture",
    "handisport": "culture",
    "ski": "plein-air",
    "randonnee": "plein-air",
    "kayak": "plein-air",
    "paddle": "plein-air",
    "ballade": "plein-air",
    "subaquatique": "plein-air",
}


def fetch(url, cache):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    path = cache / key
    if not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "ajc06-migration"})
        with urllib.request.urlopen(req, timeout=60) as r:
            path.write_bytes(r.read())
    return path.read_bytes()


def save_media(url, cache, folder):
    """Télécharge une image ou un PDF, convertit les images en WebP, renvoie le chemin relatif à MEDIA."""
    url = url.replace("ajc06.com//", "ajc06.com/")
    name = Path(url.split("?")[0]).stem.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:60] or "fichier"
    # Plusieurs fichiers WordPress portent le même nom (« Capture.png ») : on préfixe par le mois de dépôt.
    month = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
    if month:
        name = f"{month.group(1)}-{month.group(2)}-{name}"
    data = fetch(url, cache)
    (MEDIA / folder).mkdir(parents=True, exist_ok=True)
    if url.lower().endswith(".pdf"):
        rel = f"{folder}/{name}.pdf"
        (MEDIA / rel).write_bytes(data)
        return rel
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    rel = f"{folder}/{name}.webp"
    img.save(MEDIA / rel, "WEBP", quality=82, method=6)
    return rel


def to_markdown(fragment, cache, folder):
    """HTML WordPress -> Markdown propre, images et PDF rapatriés."""
    soup = BeautifulSoup(fragment, "html.parser")
    for tag in soup(["script", "style", "iframe"]):
        tag.decompose()
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if "ajc06.com" in src:
            img["src"] = "/media/" + save_media(src, cache, folder)
            img.attrs = {"src": img["src"], "alt": img.get("alt", "")}
        else:
            img.decompose()
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if "ajc06.com/wp-content/uploads" in href and href.lower().endswith(".pdf"):
            a["href"] = "/media/" + save_media(href, cache, "documents")
    # Les blocs « fichier » de WordPress répètent le lien avec un bouton « Télécharger ».
    for a in soup.select("a.wp-block-file__button"):
        a.decompose()
    md = markdownify(str(soup), heading_style="ATX", bullets="-", strip=["span", "div"])
    md = md.replace(" ", " ")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def parse_ics(text):
    text = re.sub(r"\r?\n[ \t]", "", text)
    fields = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            name, *params = key.split(";")
            fields.setdefault(name, (params, value))
    return fields


def ics_date(params, value):
    if "VALUE=DATE" in params:
        return datetime.strptime(value, "%Y%m%d").date().isoformat(), True
    return datetime.strptime(value, "%Y%m%dT%H%M%S").isoformat(), False


def scrape_events(cache):
    sitemap = fetch(f"{SITE}/event-sitemap.xml", cache).decode()
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", sitemap) if not u.rstrip("/").endswith("/events")]
    events = []
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        page = BeautifulSoup(fetch(url, cache), "html.parser")
        ics = parse_ics(fetch(url + "ical/", cache).decode("utf-8"))
        start, all_day = ics_date(*ics["DTSTART"])
        end, _ = ics_date(*ics["DTEND"])
        if all_day:  # DTEND iCal est exclusif
            end = datetime.fromordinal(datetime.fromisoformat(end).toordinal() - 1).date().isoformat()
        title = html.unescape(page.find("h1", class_="entry-title").get_text(strip=True))
        where = page.select_one(".em-event-where .em-item-meta-line div")
        venue, address = "", ""
        if where:
            parts = [s.strip() for s in where.get_text("\n").split("\n") if s.strip()]
            venue = parts[0] if parts else ""
            address = ", ".join(parts[1:])
        lat = page.select_one(".em-location-map-coords .lat")
        lng = page.select_one(".em-location-map-coords .lng")
        image = page.select_one(".em-item-image img")
        content = page.select_one(".em-event-content")
        body = to_markdown(content.decode_contents(), cache, "evenements") if content else ""
        signup = re.search(r"https://www\.helloasso\.com/[^\s)\"'<>]+", body)
        price = re.search(r"\*\*Prix ?:?\*\* ?:? ?([^\n]+)", body) or re.search(r"Prix ?: ?([^\n]+)", body)
        events.append({
            "slug": slug,
            "title": title,
            "start": start,
            "end": end,
            "all_day": all_day,
            "venue": venue,
            "address": address,
            "latitude": float(lat.text) if lat and lat.text.strip() else None,
            "longitude": float(lng.text) if lng and lng.text.strip() else None,
            "image": save_media(image["src"], cache, "evenements") if image else "",
            "registration_url": signup.group(0).split("?")[0] if signup else "",
            "price": price.group(1).strip(" *") if price else "",
            "kind": next((k for key, k in KINDS.items() if key in slug), "meetup"),
            "body": body,
        })
        print("événement", start[:10], slug)
    events.sort(key=lambda e: e["start"])
    return events


def post_text(p, cache, cover):
    excerpt = BeautifulSoup(p["excerpt"]["rendered"], "html.parser").get_text(" ", strip=True)
    excerpt = re.sub(r"\s*\[(…|&hellip;|\.\.\.)\]\s*$", "…", html.unescape(excerpt))
    body = to_markdown(p["content"]["rendered"], cache, "actu")
    if cover:  # l'image de tête répète souvent la couverture
        body = re.sub(r"^!\[[^\]]*\]\(/media/" + re.escape(cover) + r"\)\s*", "", body)
    return html.unescape(p["title"]["rendered"]), excerpt, body


def scrape_posts(cache):
    posts = json.loads(fetch(f"{SITE}/wp-json/wp/v2/posts?per_page=100", cache))
    # Les versions anglaises (/en/…) partagent l'image de couverture de leur version française.
    english = {p["featured_media"]: p for p in posts if "/en/" in p["link"] and p["featured_media"]}
    out, seen = [], set()
    for p in posts:
        if "/en/" in p["link"]:
            continue
        title = html.unescape(p["title"]["rendered"])
        if title in seen:
            continue
        seen.add(title)
        cover = ""
        if p["featured_media"]:
            media = json.loads(fetch(f"{SITE}/wp-json/wp/v2/media/{p['featured_media']}", cache))
            cover = save_media(media["source_url"], cache, "actu")
        title, excerpt, body = post_text(p, cache, cover)
        slug = urllib.request.unquote(p["slug"]).replace("·", "-")
        item = {
            "slug": re.sub(r"[^a-z0-9-]+", "-", slug).strip("-"),
            "legacy_slug": urllib.request.unquote(p["slug"]),
            "title": title,
            "published_at": p["date"],
            "cover": cover,
            "excerpt": excerpt,
            "body": body,
        }
        en = english.get(p["featured_media"])
        if en:
            en_title, en_excerpt, en_body = post_text(en, cache, cover)
            item["en"] = {"legacy_slug": urllib.request.unquote(en["slug"]), "title": en_title,
                          "excerpt": en_excerpt, "body": en_body}
        out.append(item)
        print("article", p["date"][:10], slug, "+ en" if en else "")
    out.sort(key=lambda p: p["published_at"])
    return out


def main():
    cache = Path(sys.argv[1])
    cache.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    for name, data in (("events", scrape_events(cache)), ("posts", scrape_posts(cache))):
        (SEED / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
