"""Content-Security-Policy avec nonce par requête (Django 5.2 n'a pas encore de CSP intégrée).

La politique est décrite dans settings.SECURE_CSP ({directive: [sources]}) ; la valeur spéciale NONCE est remplacée
par le nonce de la requête, exposé aux gabarits sous le nom {{ csp_nonce }}.
"""

import secrets

SELF = "'self'"
NONE = "'none'"
NONCE = "<nonce>"


class LazyNonce:
    """Nonce généré seulement si un gabarit ou l'en-tête en a besoin."""

    def __init__(self):
        self._value = None

    def __str__(self):
        if self._value is None:
            self._value = secrets.token_urlsafe(16)
        return self._value

    @property
    def used(self):
        return self._value is not None


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        from django.conf import settings

        self.get_response = get_response
        self.policy = getattr(settings, "SECURE_CSP", {})

    def __call__(self, request):
        request.csp_nonce = LazyNonce()
        response = self.get_response(request)
        if self.policy and "Content-Security-Policy" not in response:
            parts = []
            for directive, sources in self.policy.items():
                values = [f"'nonce-{request.csp_nonce}'" if s == NONCE else s for s in sources]
                parts.append(" ".join([directive, *values]))
            response["Content-Security-Policy"] = "; ".join(parts)
        return response


def nonce(request):
    """Processeur de contexte : {{ csp_nonce }}."""
    return {"csp_nonce": getattr(request, "csp_nonce", "")}
