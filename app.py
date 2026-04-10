from flask import Flask, request, Response, send_from_directory
import base64
import hashlib
import hmac
import json
import os
from urllib import error, parse, request as urllib_request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "dados.json")
DEFAULT_DATA = {"mortes": 0}

APP_BOOT_TIME = int(os.times().elapsed)
GOLEIRO_REWARD_TITLE = "goleiro"

# Estado em memória para notificar a webpage do OBS quando houver resgate.
POWERUP_EVENT_STATE = {
    "seq": 0,
    "last_reward": None,
}

# Função para verificar se uma variável de ambiente está presente e não vazia
def env_present(name):
    value = os.environ.get(name)
    return value is not None and value != ""

# Função para obter o status das variáveis de ambiente relevantes para a publicação no GitHub
def get_env_status():
    return {
        "GITHUB_TOKEN": env_present("GITHUB_TOKEN"),
        "GITHUB_OWNER": env_present("GITHUB_OWNER"),
        "GITHUB_REPO": env_present("GITHUB_REPO"),
        "GITHUB_REPOSITORY": env_present("GITHUB_REPOSITORY"),
        "GITHUB_BRANCH": env_present("GITHUB_BRANCH"),
        "GITHUB_FILE_PATH": env_present("GITHUB_FILE_PATH"),
        "TWITCH_CHANNEL_ID": env_present("TWITCH_CHANNEL_ID"),
        "TWITCH_DEV_ID": env_present("TWITCH_DEV_ID"),
        "TWITCH_SECRET": env_present("TWITCH_SECRET"),
        "TWITCH_TOKEN": env_present("TWITCH_TOKEN"),
        "PORT": env_present("PORT"),
    }

def get_public_base_url():
    return (os.environ.get("PUBLIC_BASE_URL", "") or "").strip().rstrip("/")

def twitch_webhook_secret():
    return (os.environ.get("TWITCH_SECRET", "") or "").strip()

def verify_twitch_signature(raw_body):
    message_id = request.headers.get("Twitch-Eventsub-Message-Id", "")
    message_timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
    provided_signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")
    secret = twitch_webhook_secret()

    if not message_id or not message_timestamp or not provided_signature or not secret:
        return False

    payload = f"{message_id}{message_timestamp}".encode("utf-8") + raw_body
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, provided_signature)

def mark_powerup_trigger(reward_title):
    POWERUP_EVENT_STATE["seq"] += 1
    POWERUP_EVENT_STATE["last_reward"] = reward_title

def create_twitch_eventsub_subscription(base_url):
    token = (os.environ.get("TWITCH_TOKEN", "") or "").strip()
    client_id = (os.environ.get("TWITCH_DEV_ID", "") or "").strip()
    channel_id = (os.environ.get("TWITCH_CHANNEL_ID", "") or "").strip()
    secret = twitch_webhook_secret()

    if not token or not client_id or not channel_id or not secret:
        return {"ok": False, "error": "Configure TWITCH_CHANNEL_ID, TWITCH_DEV_ID, TWITCH_SECRET e TWITCH_TOKEN"}

    callback_url = f"{base_url}/twitch/eventsub"
    body = {
        "type": "channel.channel_points_custom_reward_redemption.add",
        "version": "1",
        "condition": {
            "broadcaster_user_id": channel_id,
        },
        "transport": {
            "method": "webhook",
            "callback": callback_url,
            "secret": secret,
        },
    }

    req = urllib_request.Request(
        "https://api.twitch.tv/helix/eventsub/subscriptions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Client-Id": client_id,
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
            return {"ok": True, "response": response_payload}
    except error.HTTPError as http_err:
        try:
            body_text = http_err.read().decode("utf-8")
        except Exception:
            body_text = "<sem corpo>"
        return {"ok": False, "error": f"HTTP {http_err.code} - {body_text}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

# Função para logar o status das variáveis de ambiente relevantes para a publicação no GitHub
def log_env_status():
    status = get_env_status()
    print(f"[ENV] status: {status}")

# Criar arquivo se nao existir
if not os.path.exists(FILE_PATH):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_DATA, f, ensure_ascii=False, indent=2)

# Lê os dados do arquivo, tentando garantir que seja um dicionário válido. Se o arquivo estiver vazio ou com formato inválido, retorna o valor padrão.
def load_data():
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return dict(DEFAULT_DATA)

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Migra formato antigo: MORTES: X
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if first_line.upper().startswith("MORTES:"):
        raw_value = first_line.split(":", 1)[1].strip()
        try:
            mortes = int(raw_value)
        except ValueError:
            mortes = 0
        return {"mortes": mortes}

    return dict(DEFAULT_DATA)

# Salva os dados no arquivo local e publica no GitHub (se configurado)
def get_github_publish_config():
    repository = (os.environ.get("GITHUB_REPOSITORY", "") or "").strip()
    repository_owner = None
    repository_name = None

    if "/" in repository:
        repository_owner, repository_name = repository.split("/", 1)

    # Compatibilidade retroativa com variaveis separadas.
    if not repository_owner:
        repository_owner = os.environ.get("GITHUB_OWNER")

    if not repository_name:
        repository_name = os.environ.get("GITHUB_REPO")

    return {
        "token": os.environ.get("GITHUB_TOKEN"),
        "owner": repository_owner,
        "repo": repository_name,
        "branch": os.environ.get("GITHUB_BRANCH", "main"),
        "file_path": os.environ.get("GITHUB_FILE_PATH", "dados.json"),
    }

# Publica o conteúdo no GitHub usando a API. O conteúdo deve ser uma string já formatada (ex: JSON).
def publish_data_to_github(content):
    config = get_github_publish_config()
    token = config["token"]
    owner = config["owner"]
    repo = config["repo"]
    branch = config["branch"]
    file_path = config["file_path"]

    if not token or not owner or not repo:
        print("GitHub publish desativado: configure GITHUB_TOKEN, GITHUB_OWNER e GITHUB_REPO no Render")
        return

    print(f"[GITHUB] Iniciando commit em {owner}/{repo}:{branch}/{file_path}")

    encoded_path = parse.quote(file_path, safe="/")
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "death-counter-api",
    }

    sha = None
    get_url = f"{api_url}?ref={parse.quote(branch)}"

    try:
        req_get = urllib_request.Request(get_url, headers=headers, method="GET")
        with urllib_request.urlopen(req_get, timeout=10) as response:
            current_data = json.loads(response.read().decode("utf-8"))
            sha = current_data.get("sha")
    except error.HTTPError as http_err:
        if http_err.code != 404:
            print(f"Falha ao consultar arquivo no GitHub: {http_err}")
            return
    except Exception as exc:
        print(f"Falha de conexao ao consultar GitHub: {exc}")
        return

    payload = {
        "message": "chore: update dados.json",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }

    if sha:
        payload["sha"] = sha

    try:
        req_put = urllib_request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        with urllib_request.urlopen(req_put, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            commit_sha = (
                response_data.get("commit", {}).get("sha")
                or response_data.get("content", {}).get("sha")
            )
            if commit_sha:
                print(f"[GITHUB] Commit concluido com sucesso: {commit_sha}")
            else:
                print("[GITHUB] Commit concluido com sucesso")
    except error.HTTPError as http_err:
        try:
            body = http_err.read().decode("utf-8")
        except Exception:
            body = "<sem corpo>"
        print(f"Falha ao publicar dados.json no GitHub: HTTP {http_err.code} - {body}")
    except Exception as exc:
        print(f"Falha ao publicar dados.json no GitHub: {exc}")

# Salva os dados no arquivo local e publica no GitHub (se configurado)
def save_data(data):
    serialized_data = json.dumps(data, ensure_ascii=False, indent=2)

    with open(FILE_PATH, "w", encoding="utf-8") as f:
        f.write(serialized_data)

    publish_data_to_github(serialized_data)

# Tenta converter o valor para int, float, bool ou None. Se não for possível, retorna a string original.
def parse_value(value):
    if isinstance(value, (int, float, bool)) or value is None:
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None

        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

    return value

# Incrementa o contador de mortes no arquivo e retorna o novo total.
def increment_deaths_in_file():
    data = load_data()

    raw_current = data.get("mortes", 0)
    try:
        current_total = int(raw_current)
    except (TypeError, ValueError):
        current_total = 0

    new_total = current_total + 1
    data["mortes"] = new_total
    save_data(data)

    return new_total

# Decrementa o contador de mortes no arquivo e retorna o novo total.
def decrement_deaths_in_file():
    data = load_data()

    raw_current = data.get("mortes", 0)
    try:
        current_total = int(raw_current)
    except (TypeError, ValueError):
        current_total = 0

    new_total = current_total - 1
    data["mortes"] = new_total
    save_data(data)

    return new_total

# Lê o valor atual de mortes do arquivo, tentando garantir que seja um inteiro. Se não for possível, retorna 0.
def get_mortes_value(data):
    raw_value = data.get("mortes", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0

# Endpoint para SALVAR texto
@app.route("/death/save", methods=["GET", "POST"])
def save():
    payload = request.get_json(silent=True) or {}
    key = request.args.get("key") or request.form.get("key") or payload.get("key")
    value = request.args.get("value") or request.form.get("value") or payload.get("value")

    if not key:
        return {"error": "Nenhuma chave enviada"}, 400

    data = load_data()
    data[str(key)] = parse_value(value)
    save_data(data)

    return str(get_mortes_value(data))

# Endpoint para LER o valor atual de mortes
@app.route("/death/get", methods=["GET"])
@app.route("/death/read", methods=["GET"])
def read_text_file():
    data = load_data()
    return str(get_mortes_value(data))

# Endpoint para LER o valor atual de mortes em formato de observação (ex: "X mortes")
@app.route("/death/read/obs", methods=["GET"])
def read_text_observation():
    data = load_data()
    return f"{get_mortes_value(data)} MORTES"

# Endpoint opcional para limpar arquivo
@app.route("/death/clear", methods=["GET"])
def clear():
    save_data(dict(DEFAULT_DATA))
    return str(DEFAULT_DATA["mortes"])

# Endpoint para INCREMENTAR o contador de mortes
@app.route("/death/increment", methods=["GET", "POST"])
def increment():
    new_total = increment_deaths_in_file()
    return str(new_total)

# Endpoint para DECREMENTAR o contador de mortes
@app.route("/death/decrement", methods=["GET", "POST"])
def decrement():
    new_total = decrement_deaths_in_file()
    return str(new_total)

# Endpoint raiz para verificar se a API está respondendo
@app.route("/", methods=["GET", "HEAD"])
def root():
    return "OK", 200

# Endpoint para verificar a saúde da API, incluindo uptime (Defina raiz de Health Status Check como /healthz no Render)
@app.route("/healthz", methods=["GET"])
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": max(0, int(os.times().elapsed) - APP_BOOT_TIME),
    }, 200

@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204

# Endpoint para DEBUG: exibe o status das variáveis de ambiente relevantes para a publicação no GitHub
@app.route("/debug/env", methods=["GET"])
def debug_env():
    return {
        "status": "ok",
        "env": get_env_status(),
    }, 200

# Endpoint para callback do EventSub da Twitch.
@app.route("/twitch/eventsub", methods=["POST"])
def twitch_eventsub_webhook():
    raw_body = request.get_data() or b""
    message_type = (request.headers.get("Twitch-Eventsub-Message-Type", "") or "").strip().lower()

    if message_type == "webhook_callback_verification":
        payload = request.get_json(silent=True) or {}
        challenge = payload.get("challenge", "")
        return Response(challenge, status=200, mimetype="text/plain")

    if not verify_twitch_signature(raw_body):
        return {"error": "Assinatura Twitch invalida"}, 403

    if message_type == "notification":
        payload = request.get_json(silent=True) or {}
        event = payload.get("event", {}) if isinstance(payload.get("event", {}), dict) else {}
        reward = event.get("reward", {}) if isinstance(event.get("reward", {}), dict) else {}
        reward_title = str(reward.get("title", "")).strip()

        if reward_title.lower() == GOLEIRO_REWARD_TITLE:
            mark_powerup_trigger(reward_title)
            print(f"[TWITCH] Power-up recebido: {reward_title}")
        else:
            print(f"[TWITCH] Resgate ignorado: {reward_title}")

        return {"status": "ok"}, 200

    if message_type == "revocation":
        print("[TWITCH] EventSub revogado")
        return {"status": "revoked"}, 200

    return {"status": "ignored", "message_type": message_type}, 200

# Endpoint para consultar trigger consumível pela webpage do OBS.
@app.route("/twitch/powerup/state", methods=["GET"])
def twitch_powerup_state():
    return {
        "seq": POWERUP_EVENT_STATE["seq"],
        "last_reward": POWERUP_EVENT_STATE["last_reward"],
    }, 200

# Endpoint para registrar assinatura EventSub no startup/deploy.
@app.route("/twitch/eventsub/subscribe", methods=["POST", "GET"])
def twitch_eventsub_subscribe():
    base_url = get_public_base_url()
    if not base_url:
        return {"ok": False, "error": "Defina PUBLIC_BASE_URL no Render (ex: https://sua-api.onrender.com)"}, 400

    result = create_twitch_eventsub_subscription(base_url)
    status_code = 200 if result.get("ok") else 400
    return result, status_code

# Webpage para OBS: fica escutando estado de power-up e toca o audio quando houver novo trigger.
@app.route("/obs/powerup", methods=["GET"])
def obs_powerup_page():
    return send_from_directory(BASE_DIR, "obs_powerup.html")

# Arquivo de audio para a webpage do OBS.
@app.route("/obs/nossa.mp3", methods=["GET"])
def obs_powerup_audio():
    return send_from_directory(BASE_DIR, "nossa.mp3")

if __name__ == "__main__":
    log_env_status()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
