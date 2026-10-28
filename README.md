# AJC06-Website

Site de l'Association des Jeunes Chercheurs des Alpes-Maritimes (AJC06), https://ajc06.com (en ligne depuis le 27/10/2026, l'ancien WordPress est archivé sur https://archive.ajc06.com).
Django 6.1, gabarits et CSS écrits à la main, aucune ressource tierce. Le plan de la refonte est dans [docs/PLAN.md](docs/PLAN.md).

## Lancer en local

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS : .venv/bin/pip
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py load_seed            # contenu repris de l'ancien site
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

- Site : http://localhost:8000
- Espace bureau (édition des événements et articles) : http://localhost:8000/gestion/
- Admin Django (équipe, ressources, comptes) : http://localhost:8000/admin/

En développement, les courriels du formulaire de contact s'affichent dans la console.

## Publier du contenu

Les membres du bureau ont un compte avec la case « statut équipe » cochée (admin Django → Utilisateurs).
Dans `/gestion/` :

- **Événement** : titre, type, date (heures vides = toute la journée ; date de fin seulement s'il dure plusieurs jours),
  lieu, prix, lien HelloAsso, affiche, description. « Dupliquer » reprend tout sauf la date et l'affiche,
  pratique pour les meet-ups récurrents. Un événement non publié n'apparaît nulle part.
- **Article** : brouillon ou publié ; une date future programme la publication.
- La description s'écrit en Markdown, avec barre d'outils, aperçu et insertion d'images.
  Les images sont redimensionnées (1600 px max) et converties en WebP.

Chaque formulaire a une section repliable **Version anglaise** : si elle reste vide, le site anglais affiche
le texte français (avec une mention « only available in French »). La liste des événements signale « FR seul ».

L'agenda est aussi exposé en iCal (`/evenements/agenda.ics`) pour s'y abonner depuis un calendrier, et les
articles en RSS (`/actu/rss/`).

## Espace membres

N'importe qui peut créer un compte (`/compte/inscription/`, connexion par courriel) :

- **profil** personnalisable (`/membres/<nom>/`) : photo, discipline, école doctorale, labo, sujet de thèse, présentation,
  centres d'intérêt, liens, couleur du profil ; visible par les membres connectés, ou public si la personne le choisit ;
- **sorties proposées par les membres** (`/evenements/proposer/`) : publiées tout de suite dans l'agenda avec la
  mention « Proposé par », filtrables (« Par l'AJC06 » / « Par les membres ») ; l'organisateur·rice les modifie ou supprime ;
- **« J'y vais »** sur tous les événements (complet si le nombre de places est atteint), liste des participant·es pour les
  membres connectés, « N de tes amis y vont » ;
- **amis** (demande, acceptation, retrait) et **invitations** d'amis à un événement ;
- **notifications** sur le site (demandes d'ami, invitations, inscriptions à mes sorties) avec pastille sur l'avatar ;
- **modération** : « Signaler » sur les sorties et les profils ; le bureau traite les signalements dans
  `/gestion/signalements/` et peut masquer une sortie ; un compte se désactive dans l'admin ;
- **garde-fous** : piège à robots et 5 inscriptions par heure et par adresse IP, 5 sorties par jour et par membre ;
- **RGPD** : suppression du compte par la personne elle-même, politique de confidentialité à jour.

Validation des nouveaux comptes, réglage « validation des nouveaux comptes » de `/gestion/reglages/` :

- `aucune` : compte actif dès l'inscription ;
- `bureau` : le compte attend qu'un membre du bureau le valide (ou le refuse) dans `/gestion/comptes/`, signalé dans
  le menu et sur le tableau de bord ; c'est le mode à utiliser sans serveur mail ;
- `courriel` : un lien (valable trois jours, renvoyable depuis la page de connexion) active le compte ; le bureau peut
  aussi valider à la main si le message n'arrive pas. À n'activer qu'une fois le SMTP en place.

Le mot de passe oublié et le lien de confirmation envoient un courriel : il faut un SMTP configuré (sinon le lien
n'apparaît que dans les journaux).

## Événements de l'asso, dossiers université, soutien

- **Types** (plusieurs par événement) : Plein air, Culture & découverte, Visite, Vie de l'asso, Afterwork, Soirée à thème, Coworking,
  Carrière & formation, Conférence/workshop/séminaire, Médiation scientifique (Pint of Science, Fête de la science, MT180…), Soutenance de thèse, Sport, Autre (texte libre). Réservés au
  bureau : PhD meet-up, Camp, Rentrée doctorale. Liste dans `events/models.py` (`TYPES`).
- **Demande de soutien** : en proposant une sortie, un membre peut demander le soutien de l'asso (au moins un mois
  avant ; somme demandée, accès, prix par personne, coûts fixes, budget, réservations par l'asso ou remboursement sur
  factures). La sortie reste privée jusqu'à la décision du bureau (`/gestion/soutiens/`). Acceptée, elle devient un
  événement de l'asso, mis en attente le temps du dossier.
- **En attente** : un événement en attente n'est visible que du bureau (et de son organisateur·rice).
- **Dossier université** (`/gestion/evenements/<id>/dossier/`) : projet prévisionnel (à transmettre deux semaines avant)
  et bilan, au format des documents remis à la DVU (convention UniCA 2026-2028), en PDF avec participant·es (HelloAsso et
  site), photos, et devis/factures annexés. Génération dans `projets/pdf.py` (fpdf2 + pypdf, polices Archivo statiques
  dans `static/fonts/pdf/`).
- **Filtres et alertes** (`/compte/alertes/`, menu du compte) : chaque membre coche les types d'événements et l'origine
  qui l'intéressent ; `python manage.py send_alerts` (cron) le prévient des nouveaux événements, sur le site et par courriel.
- **Nice-Event** : les sorties de membres cochées « publier aussi sur Nice-Event » (case cochée par défaut) sont publiées
  dans `/evenements/nice-event.json`, lu par nice-event.fr, avec un bouton « Voir sur Nice-Event » sur la page.
- **HelloAsso** : `python manage.py sync_helloasso` récupère les billets des événements dont le lien d'inscription pointe
  vers un formulaire de l'AJC06 (cron horaire en production). Identifiants dans `/gestion/reglages/`.
- **Photos et vidéos** (`/photos/`) : tout membre peut en publier plusieurs à la fois, liées ou non à un événement, en
  identifiant d'autres membres ; l'accord des personnes photographiées est obligatoire, une personne identifiée peut se
  retirer ou signaler le média. Photos converties en WebP (12 Mo max.), vidéos MP4/MOV/WebM jusqu'à 50 Mo (servies par
  plages d'octets pour Safari), et liens externes : YouTube, Vimeo, Dailymotion se lisent sur place mais le lecteur ne se
  charge qu'au clic (CSP `frame-src` dans `core/embeds.py`), Pinterest, Google Photos, Drive, Flickr… en carte cliquable.
- **Commentaires** sous chaque événement (membres connectés ; noms masqués aux visiteurs sauf profil public),
  signalables, masqués automatiquement après trois signalements, supprimables par leur auteur·rice et le bureau.
- **Événements passés** : rubrique « Y est allé·e » du profil, visible par tous ceux qui voient le profil, les amis ou
  la personne seule (réglage du profil).
- **Partage** : bloc « Fais tourner ! » sur chaque événement (WhatsApp, Facebook, LinkedIn, courriel, lien, partage
  natif sur mobile, visuel de story à télécharger), sans rien charger chez les réseaux avant le clic.
- **Diffusion par le bureau** (`/gestion/evenements/<id>/diffuser/`, icône de partage dans la liste des événements) :
  Instagram, Facebook et courriel à une liste, avec visuel généré (`social/visuals.py` : affiche entière ou titre en
  grand, formats portrait, paysage et story) et textes pré-remplis modifiables, tout de suite ou programmés ; historique
  dans `/gestion/diffusions/` (annuler, relancer). Les diffusions programmées partent avec `python manage.py send_posts`
  (cron) et, à défaut, au passage du ping de `robots.txt` toutes les 5 minutes. Courriels en copie cachée par paquets
  de 50, visuel en pièce jointe.
  Pour Instagram et Facebook (réglages › Diffusion) : Page Facebook de l'asso reliée au compte Instagram professionnel,
  application sur developers.facebook.com avec `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`,
  `instagram_basic`, `instagram_content_publish`, puis jeton de Page longue durée (Explorateur de l'API Graph →
  jeton utilisateur → échange longue durée → `GET /me/accounts`), identifiant de la Page et identifiant Instagram
  (`GET /<page-id>?fields=instagram_business_account`). Boutons « Tester » sans rien publier.
- **Coordonnées** du profil (téléphone, WhatsApp, Discord, Instagram, Facebook, X, autre) : jamais publiques,
  visibles des amis par défaut.

## Réglages du site (à la place du .env)

`/gestion/reglages/` (superutilisateurs seulement) règle sans toucher au `.env` ni redémarrer : serveur mail (avec un
bouton « courriel de test »), expéditeur et adresse de contact, validation des nouveaux comptes, identifiants HelloAsso,
hébergeur des mentions légales. Les secrets (mot de passe SMTP, client_secret HelloAsso) sont chiffrés en base avec
`CONFIG_ENCRYPTION_KEY` (à défaut, une clé dérivée de `DJANGO_SECRET_KEY`) et ne sont jamais réaffichés ; chaque
modification est journalisée. À la première lecture, les réglages reprennent les anciennes variables du `.env`
(`EMAIL_*`, `ACCOUNT_VALIDATION`, `HELLOASSO_*`, `CONTACT_EMAIL`, `LEGAL_HOST`), qui ne servent plus ensuite.
Module partagé avec le site Nice-Event (`siteconfig/`).

## Effets saisonniers et annonces

Effets cumulables, calculés selon la date (heure de Paris) dans `core/effects.py`, animés par `static/js/effects.js` :
30 ans (toute l'année 2026), anniversaire (17-30 avril, création le 24 avril 1996), Pâques (semaine précédente → lundi),
Pride (juin), Halloween (24 oct. → 1er nov.), Noël (1er-26 déc.), nouvel an (29 déc. → 3 janv.). Le bureau les
prévisualise depuis `/gestion/effets/` ; les visiteurs peuvent les couper (pied de page). Le bandeau d'annonce se gère
dans `/gestion/annonces/`.

## Français et anglais

Le site français est à la racine, l'anglais sous `/en/` avec des adresses traduites (`/en/events/`, `/en/team/`,
`/en/our-missions/`… qui reprennent celles de l'ancien site). L'espace bureau et l'admin restent en français.

- Textes de l'interface : `{% translate %}` dans les gabarits, catalogue `locale/en/LC_MESSAGES/django.po`.
  Après avoir modifié un texte, lancer `python scripts/i18n.py` (extrait les chaînes, conserve les traductions,
  compile le `.mo`, sans besoin de GNU gettext) puis compléter les `msgstr` vides ; `--check` échoue s'il en reste.
- Pages surtout rédactionnelles (missions, soutien, mentions légales, confidentialité) : une version par langue,
  `templates/core/<page>.html` et `templates/core/en/<page>.html`.
- Contenus (événements, articles, ressources, équipe) : champs `<champ>_en` facultatifs, repli sur le français.

## Contenu repris de l'ancien site

`seed/` contient tout ce qui a été récupéré d'ajc06.com : `events.json` (38 événements, avec dates exactes tirées
des exports iCal), `posts.json` (14 articles), `resources/*.md` (fiches réécrites à la main depuis les pages Divi),
`team.json` (bureaux 2017 → 2026) et les médias en WebP. Les versions anglaises sont dans `seed/translations/`
(événements, articles sans version anglaise d'origine) et `seed/resources/en/`. `scripts/scrape_wordpress.py` régénère événements,
articles et médias ; `load_seed` peut être relancé sans créer de doublons.

Les anciennes adresses (`/events/…`, `/evenement/`, `/don/`, articles à la racine, pages `/en/…`) redirigent en 301.

## Sécurité et sauvegardes

- **Blocage des essais de mots de passe** (`core/security.py`, sur toutes les connexions : membres, bureau, admin) :
  5 échecs en 15 minutes depuis une même adresse IP la bloquent une heure ; tenter les identifiants `admin`,
  `administrator`, `root`, `wp-admin`… la bloque 24 heures dès le premier essai. Les blocages se voient et se lèvent
  dans l'admin (« Adresses bloquées »). Derrière un reverse proxy qui pose `X-Forwarded-For`, mettre `TRUST_X_FORWARDED_FOR=True`
  (jamais sinon : l'en-tête serait falsifiable).
- **Limites d'envoi** : 5 inscriptions, 5 messages de contact et 5 demandes de mot de passe oublié par heure et par
  adresse IP (3 par adresse mail pour le mot de passe oublié), 5 renvois de lien de confirmation.
- **Fichiers téléversés** (`core/media.py`) : publics et mis en cache une semaine, sauf `media/dossiers/` (devis,
  factures, photos des bilans) réservé au bureau. Images limitées à 12 Mo et 40 mégapixels (`core/images.py`).
  Les listes affichent des miniatures (`{{ image|thumb:192 }}`), créées au premier affichage dans `media/thumbs/`
  (exclues des sauvegardes, on peut supprimer le dossier sans risque).
- **Sauvegardes** : `python manage.py backup_site` copie la base à chaud (gzip) chaque jour et archive les médias le
  dimanche (`--media` pour forcer) dans `BACKUP_DIR` ; 60 jours de base et 8 archives de médias sont conservés.
  Restauration : arrêter l'application, `gunzip` la copie voulue à la place de `DATABASE_PATH`, extraire l'archive des
  médias dans le dossier parent de `MEDIA_ROOT`, redémarrer.

## Tests

```sh
.venv311/Scripts/python manage.py test tests     # Python 3.11, comme en production
```

## Production : o2switch (ajc06.com)

Hébergement mutualisé de l'asso (`ssh ajc06`), application Python cPanel (Passenger, Python 3.11, d'où Django 5.2 LTS) :

- code dans `~/ajc06-site` (copie du dépôt, sans git), `.env` à côté (droits 600) ;
- virtualenv `~/virtualenv/ajc06-site/3.11`, point d'entrée `passenger_wsgi.py`. Attention : recréer l'application
  avec `cloudlinux-selector create` remplace ce fichier par un modèle qui ne marche pas, il faut le recopier ;
- domaines : ajc06.com (racine web `~/public_html`, qui ne contient que le `.htaccess` Passenger, `.well-known` et
  `old_website`) ; www.ajc06.com redirige en 301 vers ajc06.com. Les variables `DJANGO_ALLOWED_HOSTS`,
  `DJANGO_CSRF_TRUSTED_ORIGINS` et `SITE_URL` du `.env` listent ces domaines ;
- beta.ajc06.com (racine `~/website`, domaine sous lequel l'application est enregistrée dans cPanel) sert la beta :
  code `~/ajc06-beta`, virtualenv `~/virtualenv/ajc06-beta/3.11`, données `~/ajc06-beta-data`, `.env` propre (autre
  `DJANGO_SECRET_KEY`, pas de HelloAsso, courriels dans les journaux), non indexée. Son `.htaccess` Passenger est écrit à
  la main : « Setup Python App » de cPanel le ferait pointer vers `~/ajc06-site`. Pas de cron pour la beta.
  `~/deploy/ajc06-beta-reset.sh` y recopie la base et les médias de prod, vide les secrets des réglages (SMTP, HelloAsso,
  Facebook/Instagram, liste de diffusion), annule les diffusions programmées et affiche un bandeau « version de test » ;
- l'ancien WordPress est archivé sur https://archive.ajc06.com (racine `~/public_html/old_website`, `PassengerEnabled off`
  dans son `.htaccess`, non indexé ; sauvegarde de la base avant bascule dans `~/wordpress-backup`). Le WordPress de
  l'ancien beta est rangé dans `~/beta-wordpress-archive` ;
- base, médias et sauvegardes hors du code : `~/ajc06-data/{db.sqlite3,media,backups}`, journal des crons dans
  `~/ajc06-data/cron.log` ;
- crons (installer avec `crontab fichier`, `crontab -` ne marche pas sous CageFS) : `backup_site` à 3 h 30,
  `sync_helloasso` toutes les heures, `send_alerts` toutes les 15 minutes (alertes des membres), `send_posts` toutes
  les 5 minutes (diffusions programmées), et un appel à `https://ajc06.com/robots.txt` toutes les 5 minutes pour
  garder l'application chargée (sinon le premier visiteur après une pause attend ~2,5 s ; `PassengerMinInstances`
  est refusé dans le `.htaccess` et casse le site) ;
- `CACHE_DIR=~/ajc06-data/cache` : cache sur disque partagé entre les processus Passenger (limites d'envoi).

Mise à jour : automatique. o2switch n'accepte le SSH que depuis les IP autorisées dans cPanel, donc pas de GitHub
Action : un cron lance `~/deploy/ajc06-deploy.sh` toutes les 2 minutes, qui récupère le dépôt (miroir
`~/deploy/ajc06.git`) et déploie ce qui a changé :

- branche `main` → https://beta.ajc06.com ;
- branche `stable` → https://ajc06.com. Mettre en production ce qui est validé sur la beta : `git push origin main:stable`.

Pour chaque instance : `git archive` du commit dans le dossier du code (les fichiers supprimés du dépôt sont retirés),
`pip install` si `requirements.txt` a changé, `migrate`, `collectstatic`, redémarrage Passenger, puis appel du site.
Le commit en ligne est noté dans `~/deploy/{prod,beta}.rev` ; un échec dans `{prod,beta}.failed` (pas de nouvel essai
avant le commit suivant). Journaux : `~/deploy/logs/{prod,beta}.log`. Redéployer sans nouveau commit :
`ssh ajc06 '~/deploy/ajc06-deploy.sh --force prod'` (ou `beta`). Les tests tournent dans GitHub Actions
(`.github/workflows/tests.yml`) : vérifier qu'ils sont verts sur `main` avant de pousser sur `stable`.

Ancienne méthode, à la main :

```sh
tar czf ajc06.tgz --exclude=.venv* --exclude=./media --exclude=./backups --exclude=staticfiles \
    --exclude='db.sqlite3*' --exclude=__pycache__ --exclude=.env --exclude=passenger_wsgi.py .
scp ajc06.tgz ajc06: && ssh ajc06 'tar xzf ajc06.tgz -C ~/ajc06-site && rm ajc06.tgz && cd ~/ajc06-site \
    && source ~/virtualenv/ajc06-site/3.11/bin/activate && pip install -q -r requirements.txt \
    && python manage.py migrate && python manage.py collectstatic --noinput && touch tmp/restart.txt'
```


### Avec Docker (autre hébergeur)

Image Docker (gunicorn, WhiteNoise pour les fichiers statiques, SQLite et médias dans le volume `/data`) :

```sh
cp .env.example .env        # remplir
docker compose up -d --build
docker compose exec web python manage.py load_seed          # première mise en ligne
docker compose exec web python manage.py createsuperuser
```

Derrière Caddy, mettre `TRUST_X_FORWARDED_FOR=True` ; exemple de site Caddy :

```caddy
ajc06.com, www.ajc06.com {
    reverse_proxy ajc06_web:8000
}
```
