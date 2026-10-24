"""PDF du projet prévisionnel et du bilan, au format des documents remis à l'université (DVU).

Mise en page reprise des dossiers de l'AJC06 : couverture (rappel de la convention, logos AJC06 et UniCA),
description du projet, budget dépenses / recettes, puis annexes (devis, factures, photos).
"""

import io
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.dateformat import format as dformat
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

from core.templatetags.ajc import hours, when

STATIC = Path(settings.BASE_DIR) / "static"
FONTS = STATIC / "fonts" / "pdf"
INK = (15, 29, 46)
AZUR = (20, 96, 166)
GREY = (90, 98, 110)
LINE = (210, 214, 220)
SHADE = (232, 234, 238)

CONVENTION = (
    "L'AJC06 a pour mission de dynamiser la vie scientifique et culturelle de l'ensemble des doctorants présents "
    "ou inscrits sur notre territoire en favorisant l'information et la communication entre eux, tout en valorisant "
    "la formation par la recherche pour aider les jeunes chercheur(se)s dans leur parcours professionnel. De plus, "
    "nous nous engageons à représenter et défendre les intérêts des jeunes chercheuses et chercheurs des "
    "Alpes-Maritimes, afin d'assurer une meilleure visibilité et reconnaissance de leurs travaux."
)


def euros(value):
    value = Decimal(value or 0)
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return (text[:-3] if text.endswith(",00") else text) + " €"


def lines(text):
    return [l.strip(" -•\t") for l in (text or "").splitlines() if l.strip(" -•\t")]


class Document(FPDF):
    def __init__(self, title):
        super().__init__(format="A4")
        self.doc_title = title
        self.set_auto_page_break(True, margin=22)
        self.set_margins(22, 20, 22)
        self.add_font("Archivo", "", str(FONTS / "Archivo-Regular.ttf"))
        self.add_font("Archivo", "B", str(FONTS / "Archivo-Bold.ttf"))
        self.add_font("Display", "", str(FONTS / "Archivo-CondensedBlack.ttf"))
        self.set_title(title)
        self.set_author("AJC06 — Association des Jeunes Chercheurs des Alpes-Maritimes")
        self.set_creator("ajc06.com")

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font("Archivo", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"AJC06 — {self.doc_title}", align="L")
        self.set_x(-40)
        self.cell(18, 6, f"{self.page_no()}", align="R")

    # Blocs ------------------------------------------------------------------

    def cover(self, kicker, title, intro):
        self.add_page()
        self.set_y(46)
        self.set_text_color(*INK)
        self.set_font("Display", "", 30)
        self.multi_cell(0, 13, kicker, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Display", "", 24)
        self.multi_cell(0, 11, title, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(14)
        self.set_font("Archivo", "B", 12)
        self.multi_cell(0, 7, "Rappel : Contenu de la convention AJC06 - Université Côte d'Azur", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.paragraph(CONVENTION, align="J")
        for text in intro:
            self.ln(2)
            self.paragraph(text)
        # Logos en pied de couverture, comme dans les dossiers papier
        self.image(str(STATIC / "img" / "pdf" / "ajc06-logo.png"), x=22, y=250, h=26)
        self.image(str(STATIC / "img" / "pdf" / "unica-logo.png"), x=150, y=252, h=22)

    def heading(self, text):
        if self.get_y() > 250:
            self.add_page()
        self.ln(4)
        self.set_font("Display", "", 20)
        self.set_text_color(*INK)
        self.multi_cell(0, 10, text, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def label(self, text):
        if self.get_y() > 262:
            self.add_page()
        self.ln(2)
        self.set_font("Archivo", "B", 11)
        self.set_text_color(*INK)
        self.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

    def paragraph(self, text, size=10.5, align="L"):
        if not text:
            return
        self.set_font("Archivo", "", size)
        self.set_text_color(*INK)
        self.multi_cell(0, 5.6, text, align=align, new_x="LMARGIN", new_y="NEXT")

    def field(self, name, value):
        """« Nom : valeur » sur une ligne, le nom en gras."""
        if not value:
            return
        self.set_text_color(*INK)
        self.set_font("Archivo", "B", 10.5)
        self.write(5.8, f"{name} : ")
        self.set_font("Archivo", "", 10.5)
        self.write(5.8, str(value))
        self.ln(7)

    def bullets(self, items, numbered=False):
        """Liste à puces ; « Titre : texte » met le titre en gras. Les lignes longues restent alignées sous le texte."""
        for n, item in enumerate(items, 1):
            if self.get_y() > 268:
                self.add_page()
            self.set_x(self.l_margin + 4)
            self.set_font("Archivo", "", 10.5)
            self.set_text_color(*INK)
            self.cell(7, 5.8, f"{n}." if numbered else "•")
            head, sep, rest = item.partition(" : ")
            text = item.replace("*", "")
            if sep and len(head) < 60:
                text = f"**{head.replace('*', '')} :** {rest.replace('*', '')}"
            width = self.w - self.r_margin - self.get_x()
            self.multi_cell(width, 5.8, text, markdown=True, new_x="LMARGIN", new_y="NEXT")
            self.ln(1.2)

    def budget(self, rows):
        """rows : [(intitulé, dépense, recette)] ; ligne TOTAL grisée."""
        widths = (88, 39, 39)
        self.set_draw_color(*INK)
        self.set_font("Archivo", "B", 10.5)
        for w, text in zip(widths, ("Intitulé", "Dépenses", "Recettes")):
            self.cell(w, 10, text, border=1, align="C")
        self.ln()
        self.set_font("Archivo", "", 10.5)
        spend = income = Decimal(0)
        for label, out, inc in rows:
            spend += out or 0
            income += inc or 0
            count = len(self.multi_cell(widths[0], 7, label, dry_run=True, output="LINES"))
            row_h = 7 * max(1, count)
            if self.get_y() + row_h > self.h - 24:
                self.add_page()
            y = self.get_y()
            self.multi_cell(widths[0], 7, label, border=1, new_x="RIGHT", new_y="TOP")
            self.set_xy(self.l_margin + widths[0], y)
            self.cell(widths[1], row_h, euros(out) if out else "", border=1, align="C")
            self.cell(widths[2], row_h, euros(inc) if inc else "", border=1, align="C")
            self.ln(row_h)
        self.set_fill_color(*SHADE)
        self.set_font("Archivo", "B", 10.5)
        self.cell(widths[0], 9, "TOTAL", border=1, fill=True)
        self.cell(widths[1], 9, euros(spend), border=1, align="C", fill=True)
        self.cell(widths[2], 9, euros(income), border=1, align="C", fill=True)
        self.ln(12)

    def people(self, names):
        if not names:
            self.paragraph("Liste non disponible.")
            return
        self.set_font("Archivo", "", 9.5)
        self.set_text_color(*INK)
        col = (self.w - self.l_margin - self.r_margin) / 3
        for n, name in enumerate(names):
            if n % 3 == 0 and n:
                self.ln(5.6)
            if self.get_y() > 270:
                self.add_page()
            self.set_x(self.l_margin + (n % 3) * col)
            self.cell(col, 5.6, f"{n + 1}. {name}")
        self.ln(9)

    def photos(self, paths, per_row=2):
        gap = 6
        width = (self.w - self.l_margin - self.r_margin - gap * (per_row - 1)) / per_row
        x0 = self.l_margin
        for n, path in enumerate(paths):
            if n % per_row == 0:
                if n:
                    self.ln(gap)
                if self.get_y() + width * 0.75 > self.h - 22:
                    self.add_page()
                row_y = self.get_y()
            x = x0 + (n % per_row) * (width + gap)
            try:
                self.image(str(path), x=x, y=row_y, w=width, h=width * 0.75, keep_aspect_ratio=True)
            except Exception:  # image illisible : on passe
                continue
            if n % per_row == per_row - 1 or n == len(paths) - 1:
                self.set_y(row_y + width * 0.75)
        self.ln(gap)


PARTICLES = {"de", "di", "du", "da", "des", "del", "della", "le", "la", "van", "von", "der", "den", "d'", "y", "e"}


def tidy_name(name):
    """« KENZA BENMOUSSA » / « antoine solcourt » -> « Kenza Benmoussa » / « Antoine Solcourt »."""
    words = " ".join(name.split()).split(" ")
    out = []
    for n, word in enumerate(words):
        low = word.lower()
        if n and low in PARTICLES:
            out.append(low)
        else:
            out.append("-".join(part[:1].upper() + part[1:].lower() for part in word.split("-")))
    return " ".join(out)


def participants(event):
    """Noms des inscrit·es : HelloAsso d'abord, puis les membres du site qui ont indiqué venir."""
    names, seen = [], set()
    for t in event.helloasso_tickets.all():
        name = tidy_name(t.full_name)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    for a in event.attendances.select_related("user__profile"):
        name = tidy_name(a.user.profile.display_name)
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names


def _finish(pdf, appended):
    """Sortie de fpdf2, suivie des annexes PDF (devis, factures) fusionnées avec pypdf."""
    data = bytes(pdf.output())
    pdfs = [a for a in appended if a.is_pdf]
    if not pdfs:
        return data
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(data)))
    for attachment in pdfs:
        try:
            with attachment.file.open("rb") as handle:
                writer.append(PdfReader(io.BytesIO(handle.read())))
        except Exception:  # fichier corrompu : on n'empêche pas la génération du dossier
            continue
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _event_sentence(event):
    capacity = f", dans la limite des {event.capacity} places disponibles" if event.capacity else ""
    where = f" Il aura lieu à {event.venue}." if event.venue else ""
    return f"Cet événement sera ouvert à tous les doctorants{capacity}.{where}"


def forecast(dossier):
    event = dossier.event
    pdf = Document(f"Projet prévisionnel — {event.title}")
    pdf.cover("Projet prévisionnel", event.title, [
        _event_sentence(event),
        f"Ligne de la convention : {dossier.get_convention_line_display()}.",
    ])

    pdf.add_page()
    pdf.heading("Description du projet")
    pdf.field("Titre", event.title)
    pdf.label("Résumé :")
    pdf.paragraph(dossier.resume or event.teaser)
    if lines(dossier.objectives):
        pdf.label("Objectifs du projet :")
        pdf.bullets(lines(dossier.objectives), numbered=True)
    pdf.label("Public visé :")
    pdf.paragraph(dossier.audience or (f"L'événement est ouvert à {event.capacity} doctorant·e·s maximum."
                                      if event.capacity else "L'événement est ouvert à tous les doctorant·e·s."))
    pdf.label("Organisation et logistique :")
    place = ", ".join(p for p in (event.venue, event.address) if p)
    pdf.bullets([l for l in (
        f"Date : {when(event).capitalize()}",
        f"Horaires : {hours(event)}",
        f"Lieu : {place}" if place else "",
        f"Transport : {dossier.transport}" if dossier.transport else "",
        f"Prestation : {dossier.services}" if dossier.services else "",
        f"Matériel : {dossier.equipment}" if dossier.equipment else "",
    ) if l])
    if lines(dossier.programme):
        pdf.label("Programme prévisionnel :")
        pdf.bullets(lines(dossier.programme))
    if lines(dossier.impact):
        pdf.label("Impact attendu :")
        pdf.bullets(lines(dossier.impact))

    pdf.add_page()
    pdf.heading("Budget prévisionnel")
    pdf.budget([(l.label, l.amount if l.side == "depense" else None, l.amount if l.side == "recette" else None)
                for l in dossier.lines("prev")])
    quotes = dossier.attachments.filter(kind="devis")
    if dossier.quotes or quotes:
        pdf.heading("Devis")
        pdf.paragraph(dossier.quotes)
        images = [a.file.path for a in quotes if a.is_image]
        if images:
            pdf.ln(4)
            pdf.photos(images, per_row=1 if len(images) == 1 else 2)
    names = participants(event)
    if names:
        pdf.heading("Inscrit·es à ce jour")
        pdf.paragraph(f"{len(names)} personne(s) inscrite(s) au {dformat(timezone.localdate(), 'j F Y')}.")
        pdf.ln(2)
        pdf.people(names)
    return _finish(pdf, list(quotes))


def report(dossier):
    event = dossier.event
    pdf = Document(f"Bilan — {event.title}")
    registered = dossier.registered_count or event.helloasso_count or event.attendee_count or None
    present = dossier.present_count
    intro = []
    if dossier.report_story:
        intro.append(dossier.report_story)
    pdf.cover("Compte-rendu", event.title, intro)

    pdf.add_page()
    pdf.heading("Participation")
    pdf.field("Date", when(event).capitalize())
    place = ", ".join(p for p in (event.venue, event.address) if p)
    pdf.field("Lieu", place)
    pdf.field("Places proposées", event.capacity)
    pdf.field("Inscrit·es", registered)
    if present is not None:
        rate = f" ({round(100 * present / registered)} %)" if registered else ""
        pdf.field("Présent·es", f"{present}{rate}")
    if dossier.report_assessment:
        pdf.label("Bilan :")
        pdf.paragraph(dossier.report_assessment)
    if lines(dossier.objectives_met):
        pdf.label("Cette action a rempli ses objectifs :")
        pdf.bullets(lines(dossier.objectives_met))

    actual = list(dossier.lines("reel")) or list(dossier.lines("prev"))
    if actual:
        pdf.heading("Bilan financier")
        pdf.budget([(l.label, l.amount if l.side == "depense" else None, l.amount if l.side == "recette" else None)
                    for l in actual])

    names = participants(event)
    if names:
        pdf.heading("Participant·es")
        pdf.people(names)

    photo_files = [p.image.path for p in event.photos.filter(is_hidden=False)]
    photo_files += [a.file.path for a in dossier.attachments.filter(kind="photo") if a.is_image]
    if photo_files:
        pdf.add_page()
        pdf.heading("Photos")
        pdf.photos(photo_files[:12])

    invoices = list(dossier.attachments.filter(kind="facture"))
    image_invoices = [a for a in invoices if a.is_image]
    if invoices:
        pdf.add_page()
        pdf.heading("Justificatifs")
        pdf.bullets([str(a) for a in invoices])
        for a in image_invoices:
            pdf.add_page()
            pdf.image(a.file.path, x=22, y=20, w=166, keep_aspect_ratio=True, h=250)
    return _finish(pdf, invoices)
