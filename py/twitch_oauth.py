"""Fluxo de Authorization Code da Twitch para obter um user access token.

Nao persiste nada: o access_token e usado apenas dentro da requisicao que o
solicitou e descartado ao final. O 'state' e um nonce assinado (HMAC) com
timestamp embutido, verificado sem qualquer armazenamento no servidor.
"""

import hashlib
import hmac
import json
import time
import uuid
from urllib import error, parse, request as urllib_request

TWITCH_OAUTH_AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_OAUTH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
SUBSCRIPTIONS_SCOPE = "channel:read:subscriptions"
STATE_MAX_AGE_SECONDS = 300


def _sign(secret, nonce, timestamp):
    payload = f"{nonce}.{timestamp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_state(secret):
    nonce = uuid.uuid4().hex
    timestamp = str(int(time.time()))
    signature = _sign(secret, nonce, timestamp)
    return f"{nonce}.{timestamp}.{signature}"


def verify_state(secret, state):
    if not state or state.count(".") != 2:
        return False

    nonce, timestamp, signature = state.split(".")
    if not timestamp.isdigit():
        return False

    if abs(time.time() - int(timestamp)) > STATE_MAX_AGE_SECONDS:
        return False

    expected = _sign(secret, nonce, timestamp)
    return hmac.compare_digest(expected, signature)


def build_authorize_url(client_id, client_secret, redirect_uri):
    state = sign_state(client_secret)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SUBSCRIPTIONS_SCOPE,
        "state": state,
    }
    return f"{TWITCH_OAUTH_AUTHORIZE_URL}?{parse.urlencode(params)}"


def exchange_code_for_token(client_id, client_secret, code, redirect_uri):
    form_data = parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode("utf-8")

    req = urllib_request.Request(
        TWITCH_OAUTH_TOKEN_URL,
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as http_err:
        try:
            body_text = http_err.read().decode("utf-8")
        except Exception:
            body_text = "<sem corpo>"
        return {"ok": False, "error": f"Falha ao trocar codigo por token (HTTP {http_err.code}): {body_text}"}
    except Exception as exc:
        return {"ok": False, "error": f"Falha ao trocar codigo por token: {exc}"}

    access_token = payload.get("access_token")
    if not access_token:
        return {"ok": False, "error": "A Twitch nao retornou um access_token valido"}

    return {"ok": True, "access_token": access_token}
