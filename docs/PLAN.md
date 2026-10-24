# Refonte du site de l'AJC06 — plan

## 1. Ce qu'on reprend du site actuel (WordPress + Divi, ajc06.com)

| Contenu | Source | Volume |
|---|---|---|
| Événements | plugin Events Manager (pages `/events/<slug>/` + export iCal par événement) | 38 événements, mars 2024 → juin 2026 |
| Actualités | API REST `wp/v2/posts`, versions françaises | 13 articles + PDF joints |
| Ressources | API REST `wp/v2/project` (fiches « Faire son doctorat », « Financer sa thèse »…) | 7 fiches |
| Équipe | page `/equipe` | bureau 2025 (6 personnes, photos) + bureaux 2017 → 2024 |
| Missions, don, contact, mentions légales, confidentialité | pages | 5 pages |

Le script `scripts/scrape_wordpress.py` fige tout dans `seed/` (JSON + images converties en WebP) ;
la commande `python manage.py load_seed` charge ce contenu dans une base vide. On ne dépend plus de l'ancien site.

Les versions anglaises (`/en/…`) ne sont pas reprises dans cette première version (voir § 7).

## 2. Architecture

- **Django 6.1** (CSP native), SQLite par défaut, PostgreSQL possible via `DATABASE_URL`.
- Gabarits Django + CSS écrit à la main + un peu de JavaScript sans dépendance. Pas de framework front, pas de CDN :
  police (Archivo, variable) et scripts servis par le site (WhiteNoise).
- Contenu rédigé en **Markdown**, converti et nettoyé côté serveur (`markdown` + `nh3`).
- Images téléversées redimensionnées et converties en WebP (Pillow).

Applications :

| App | Rôle |
|---|---|
| `core` | pages fixes, équipe, ressources, contact, rendu Markdown, redirections des anciennes URL |
| `events` | événements, agenda iCal (par événement et flux global à s'abonner) |
| `blog` | articles, flux RSS |
| `gestion` | espace d'édition du bureau (`/gestion/`) |

## 3. Pages publiques

| URL | Contenu |
|---|---|
| `/` | accroche, prochain rendez-vous (compte à rebours), chiffres réels, missions, mur des événements passés, dernières actus, « comment participer » |
| `/evenements/` | à venir puis archives par année, filtre par type |
| `/evenements/<slug>/` | date, heure, lieu (lien carte), prix, bouton d'inscription HelloAsso, ajout au calendrier |
| `/evenements/agenda.ics` | flux d'agenda à ajouter dans Google Agenda / Apple Calendrier / Thunderbird |
| `/actu/`, `/actu/<slug>/`, `/actu/rss/` | articles |
| `/missions/`, `/equipe/`, `/ressources/…`, `/soutenir/`, `/contact/` | association |
| `/mentions-legales/`, `/confidentialite/` | légal |

Les anciennes URL (`/events/…`, `/evenement/`, `/actu/…`, `/don/`, `/equipe`, articles à la racine…) redirigent en 301.

## 4. Espace d'édition `/gestion/`

Pensé pour un membre du bureau qui n'a jamais touché Django :

- tableau de bord : prochains événements, brouillons, derniers messages reçus ;
- formulaire d'événement d'une page : titre, type, début/fin (ou journée entière), lieu, prix, lien d'inscription,
  affiche, résumé, description ;
- **dupliquer** un événement (les meet-ups reviennent souvent) ;
- formulaire d'article : brouillon / publié, date de publication, couverture ;
- éditeur Markdown avec barre d'outils, aperçu, insertion d'image par téléversement ;
- messages du formulaire de contact.

L'admin Django reste disponible pour le reste (équipe, ressources, comptes).

## 5. Direction visuelle

- Identité tirée du logo : bleu « azur » `#1460A6`, bleu clair `#3894C0`, encre marine, papier crème.
  Un seul accent chaud, **jaune mimosa** (la fleur de février dans le 06), pour ce qui doit attirer l'œil :
  prochain événement, inscription, surlignage.
- Typographie unique Archivo : titres en largeur condensée et graisse forte (effet affiche),
  texte courant en largeur normale.
- Les événements sont présentés comme un **programme de saison** : grosse date, type, lieu, une ligne par événement.
- Le mur des affiches passées rend visible tout ce que l'asso a déjà organisé.
- Thème clair et sombre, bordures fines, pas de dégradés, pas de verre dépoli, pas d'emoji décoratifs.

## 6. Qualité

- Tests (`python manage.py test`) : modèles, pages publiques, iCal, redirections, droits de l'espace d'édition.
- Captures Playwright en bureau et mobile, clair et sombre, avant de valider.
- CSP stricte, en-têtes de sécurité, formulaire de contact avec piège à robots.
- `Dockerfile` + `compose.yaml` prêts pour VPS1 (gunicorn derrière Caddy), non déployés.

## 7. Version 2 (24/10/2026)

- Version anglaise complète : interface, pages, 38 événements, 14 articles, 7 fiches, équipe.
- WhatsApp devient l'appel principal (avec Instagram), Discord reste proposé.
- Bureau 2026, liens Google Maps, déploiement provisoire sur VPS1.

## 8. Version 3 (24/10/2026) : espace membres

- Comptes ouverts à tous, profils personnalisables, amis, notifications.
- Sorties proposées par les membres, « J'y vais », invitations, signalements et modération par le bureau.

## 9. Ensuite

- Enregistrement DNS de l'adresse provisoire, puis domaine ajc06.com une fois le site validé par le bureau.
- SMTP pour le formulaire de contact et le mot de passe oublié, puis confirmation de l'adresse à l'inscription.
- Notifications par courriel (facultatives), pour les invitations et les demandes d'ami.
- Migration vers le serveur de l'association.
