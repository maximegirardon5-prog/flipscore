"""Outils HTTP communs aux connecteurs : délai entre appels, nouvelles tentatives, erreurs.

Règles appliquées à toutes les sources :
- erreurs passagères (réseau, 429 « trop de requêtes », 5xx) : nouvelles tentatives
  espacées de plus en plus (1 s, 2 s, 4 s…), puis SourceTemporaryError ;
- accès refusé (403) : SourceBlockedError immédiatement, sans insister ;
- respect d'un délai minimal entre deux appels.
"""

import time
from collections.abc import Callable

import httpx

from app.core.errors import SourceBlockedError, SourceTemporaryError
from app.core.logging import get_logger

log = get_logger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class PoliteHttpClient:
    def __init__(
        self,
        source: str,
        *,
        min_interval_seconds: float = 0.0,
        max_retries: int = 3,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self.min_interval_seconds = min_interval_seconds
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_call = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "FlipScore/0.2 (outil personnel)"},
        )

    def _wait_politely(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self.min_interval_seconds:
            self._sleep(self.min_interval_seconds - elapsed)
        self._last_call = time.monotonic()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Envoie la requête avec nouvelles tentatives. Renvoie la réponse (même 4xx,
        sauf 403) : c'est à l'appelant d'interpréter 401, 404…"""
        last_error = ""
        for attempt in range(self.max_retries + 1):
            self._wait_politely()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:  # réseau coupé, délai dépassé…
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 403:
                    raise SourceBlockedError(f"{self.source} : accès refusé (403)")
                if response.status_code not in RETRYABLE_STATUS:
                    return response
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < self.max_retries:
                    self._sleep(min(int(retry_after), 60))
                    continue
            if attempt < self.max_retries:
                delay = 2**attempt
                log.warning(
                    "erreur passagère, nouvelle tentative",
                    extra={"source": self.source, "error": last_error, "delay_s": delay},
                )
                self._sleep(delay)
        raise SourceTemporaryError(f"{self.source} : échec après tentatives ({last_error})")

    def close(self) -> None:
        self._client.close()
