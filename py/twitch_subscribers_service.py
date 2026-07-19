"""Consulta paginada ao endpoint Helix Get Broadcaster Subscriptions."""

import json
from urllib import error, parse, request as urllib_request

HELIX_SUBSCRIPTIONS_URL = "https://api.twitch.tv/helix/subscriptions"
PAGE_SIZE = 100


def _friendly_http_error(status_code, body_text):
    if status_code == 401:
        return "Token da Twitch invalido ou expirado. Tente autorizar novamente."
    if status_code == 403:
        return "A Twitch recusou o acesso aos subscribers (o canal precisa ser Afiliado/Parceiro para ter subscribers)."
    return f"A Twitch retornou um erro (HTTP {status_code}): {body_text}"


def fetch_all_subscribers(access_token, client_id, broadcaster_id):
    subscribers = []
    cursor = None

    while True:
        params = {"broadcaster_id": broadcaster_id, "first": str(PAGE_SIZE)}
        if cursor:
            params["after"] = cursor

        url = f"{HELIX_SUBSCRIPTIONS_URL}?{parse.urlencode(params)}"
        req = urllib_request.Request(
            url,
            headers={
                "Client-Id": client_id,
                "Authorization": f"Bearer {access_token}",
            },
        )

        try:
            with urllib_request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as http_err:
            try:
                body_text = http_err.read().decode("utf-8")
            except Exception:
                body_text = "<sem corpo>"
            return {"ok": False, "error": _friendly_http_error(http_err.code, body_text)}
        except Exception as exc:
            return {"ok": False, "error": f"Falha ao consultar subscribers da Twitch: {exc}"}

        subscribers.extend(payload.get("data", []) or [])

        cursor = ((payload.get("pagination", {}) or {}).get("cursor") or "").strip()
        if not cursor:
            break

    return {"ok": True, "subscribers": subscribers}
