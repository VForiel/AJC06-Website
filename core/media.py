"""Fichiers téléversés, servis par Django (l'hébergement mutualisé ne permet pas de les confier à un serveur frontal).

Les pièces des dossiers université (devis, factures, photos du bilan) sont réservées au bureau ; le reste est public
et mis en cache par le navigateur (les noms changent à chaque nouveau téléversement).
"""

from django.conf import settings
from django.http import Http404
from django.views.static import serve

PRIVATE_PREFIXES = ("dossiers/",)
CACHE = "public, max-age=604800"  # une semaine


def media(request, path):
    if path.startswith(PRIVATE_PREFIXES):
        if not (request.user.is_authenticated and request.user.is_staff):
            raise Http404  # même réponse qu'un fichier absent : on ne confirme pas son existence
        response = serve(request, path, document_root=settings.MEDIA_ROOT)
        response["Cache-Control"] = "private, no-store"
        return response
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = CACHE
    return response
