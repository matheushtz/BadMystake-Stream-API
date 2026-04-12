from flask import Flask, request, Response, send_from_directory
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from urllib import error, parse, request as urllib_request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "dados.json")
OGG_DIR = os.path.join(BASE_DIR, "ogg")
MP3_DIR = os.path.join(BASE_DIR, "mp3")
DEFAULT_DATA = {}

APP_BOOT_TIME = int(os.times().elapsed)

def send_file_no_cache(directory, filename):
    response = send_from_directory(directory, filename)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.before_request
def log_incoming_request():
    query_string = request.query_string.decode("utf-8") if request.query_string else ""
    query_suffix = f"?{query_string}" if query_string else ""
    print(
        f"[HTTP] {request.method} {request.path}{query_suffix} from={request.remote_addr}",
        flush=True,
    )

# Estado em memória para notificar a webpage do OBS quando houver resgate.
POWERUP_EVENT_STATE = {
    "seq": 0,
    "last_reward": None,
    "last_event": None,
}

# Controle simples de deduplicacao de mensagens do EventSub.
LAST_EVENT_IDS = set()
MAX_EVENT_IDS = 5000

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
        "TWITCH_WEBHOOK_SECRET": env_present("TWITCH_WEBHOOK_SECRET"),
        "TWITCH_CLIENT_ID": env_present("TWITCH_CLIENT_ID"),
        "TWITCH_CLIENT_SECRET": env_present("TWITCH_CLIENT_SECRET"),
        "PORT": env_present("PORT"),
    }

def get_public_base_url():
    return (os.environ.get("PUBLIC_BASE_URL", "") or "").strip().rstrip("/")

def get_first_env(*names):
    for name in names:
        value = (os.environ.get(name, "") or "").strip()
        if value:
            return value
    return ""

def twitch_webhook_secret():
    # Segredo do webhook EventSub (assinatura HMAC).
    return get_first_env("TWITCH_WEBHOOK_SECRET", "TWITCH_SECRET")

def twitch_client_id():
    return get_first_env("TWITCH_DEV_ID", "TWITCH_CLIENT_ID")

def twitch_client_secret():
    return get_first_env("TWITCH_SECRET", "TWITCH_CLIENT_SECRET")

def twitch_access_token():
    client_id = twitch_client_id()
    client_secret = twitch_client_secret()

    if not client_id or not client_secret:
        return ""

    return get_twitch_app_access_token(client_id, client_secret)

def normalize_game_name(game_name):
    """Normaliza o nome do jogo para usar como chave no JSON.
    Ex: 'Outer Wilds' -> 'outer-wilds'
    """
    if not game_name:
        return "unknown"
    
    # Remove espaços extras e converte para minúsculas
    normalized = game_name.strip().lower()
    
    # Substitui múltiplos espaços por hífen único
    normalized = "-".join(normalized.split())
    
    # Remove caracteres especiais, mantendo apenas alfanuméricos e hífens
    normalized = "".join(c if c.isalnum() or c == "-" else "" for c in normalized)
    
    # Remove hífens duplicados
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    
    # Remove hífens nas extremidades
    normalized = normalized.strip("-")
    
    return normalized or "unknown"

def get_current_game_from_twitch():
    """Busca o jogo atual do canal na Twitch.
    Retorna o nome do jogo ou None se não conseguir buscar.
    """
    channel_id = (os.environ.get("TWITCH_CHANNEL_ID", "") or "").strip()
    client_id = twitch_client_id()
    
    if not channel_id or not client_id:
        print("[TWITCH] Não foi possível buscar jogo: TWITCH_CHANNEL_ID ou TWITCH_CLIENT_ID não configurados", flush=True)
        return None
    
    try:
        access_token = twitch_access_token()
        if not access_token:
            print("[TWITCH] Não foi possível obter access token para buscar jogo atual", flush=True)
            return None
        
        api_url = f"https://api.twitch.tv/helix/channels?broadcaster_id={channel_id}"
        headers = {
            "Client-Id": client_id,
            "Authorization": f"Bearer {access_token}",
        }
        
        req = urllib_request.Request(api_url, headers=headers, method="GET")
        with urllib_request.urlopen(req, timeout=10) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            data = response_data.get("data", [])
            if data and len(data) > 0:
                game_name = data[0].get("game_name")
                if game_name:
                    print(f"[TWITCH] Jogo atual encontrado: {game_name}", flush=True)
                    return game_name
    except error.HTTPError as http_err:
        try:
            body = http_err.read().decode("utf-8")
        except Exception:
            body = "<sem corpo>"
        print(f"[TWITCH] Erro ao buscar jogo atual: HTTP {http_err.code} - {body}", flush=True)
    except Exception as exc:
        print(f"[TWITCH] Erro ao buscar jogo atual: {exc}", flush=True)
    
    return None

def is_valid_twitch_timestamp(timestamp_raw):
    if not timestamp_raw:
        return False

    try:
        parsed = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    except ValueError:
        return False

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    delta = abs(time.time() - parsed.timestamp())
    return delta <= 600

def should_process_reward(reward):
    # Processa todos os resgates sem filtro por variavel de ambiente.
    return True

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

def mark_powerup_trigger(event_payload):
    POWERUP_EVENT_STATE["seq"] += 1
    POWERUP_EVENT_STATE["last_reward"] = event_payload.get("reward", {}).get("title")
    
    POWERUP_EVENT_STATE["last_event"] = event_payload

def trigger_powerup_test(label="TESTE"):
    mark_powerup_trigger({
        "reward": {
            "title": label,
        },
        "source": "powerup-test",
        "sound_file": "nossa.ogg",
    })

def trigger_death_increment_event(total_value):
    mark_powerup_trigger({
        "reward": {
            "id": "death-increment",
            "title": "Morreu",
            "background_color": "#b30000",
        },
        "user_name": "Contador",
        "user_input": str(total_value),
        "sound_file": "morreu.ogg",
        "source": "death-increment",
    })

def trigger_death_decrement_event(total_value):
    mark_powerup_trigger({
        "reward": {
            "id": "death-decrement",
            "title": "Morreu",
            "background_color": "#b30000",
        },
        "user_name": "Contador",
        "user_input": str(total_value),
        "sound_file": "morreu.ogg",
        "source": "death-decrement",
    })

def get_twitch_app_access_token(client_id, client_secret):
    token_url = "https://id.twitch.tv/oauth2/token"
    form_data = parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }).encode("utf-8")

    req = urllib_request.Request(
        token_url,
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urllib_request.urlopen(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return payload.get("access_token")

def create_twitch_eventsub_subscription(base_url):
    client_id = twitch_client_id()
    client_secret = twitch_client_secret()
    channel_id = (os.environ.get("TWITCH_CHANNEL_ID", "") or "").strip()
    webhook_secret = twitch_webhook_secret()

    missing = []
    if not channel_id:
        missing.append("TWITCH_CHANNEL_ID")
    if not client_id:
        missing.append("TWITCH_DEV_ID/TWITCH_CLIENT_ID")
    if not client_secret:
        missing.append("TWITCH_SECRET/TWITCH_CLIENT_SECRET")
    if not webhook_secret:
        missing.append("TWITCH_WEBHOOK_SECRET (ou TWITCH_SECRET)")

    if missing:
        return {
            "ok": False,
            "error": "Configure variaveis: " + ", ".join(missing),
        }

    try:
        access_token = twitch_access_token()
    except error.HTTPError as http_err:
        try:
            body_text = http_err.read().decode("utf-8")
        except Exception:
            body_text = "<sem corpo>"
        return {"ok": False, "error": f"Token app HTTP {http_err.code} - {body_text}"}
    except Exception as exc:
        return {"ok": False, "error": f"Falha ao gerar token app: {exc}"}

    if not access_token:
        return {
            "ok": False,
            "error": "Nao foi possivel obter app access token (verifique TWITCH_DEV_ID e TWITCH_SECRET)",
        }

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
            "secret": webhook_secret,
        },
    }

    req = urllib_request.Request(
        "https://api.twitch.tv/helix/eventsub/subscriptions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Client-Id": client_id,
            "Authorization": f"Bearer {access_token}",
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
            # Detecta formato antigo: {"mortes": X} e faz migração
            if "mortes" in data and len(data) == 1 and isinstance(data.get("mortes"), (int, str)):
                # Formato antigo - migrar para novo formato com jogo "unknown"
                try:
                    mortes_count = int(data["mortes"])
                except (TypeError, ValueError):
                    mortes_count = 0
                print("[MIGRAÇÃO] Detectado formato antigo de dados. Migrando para novo formato por jogo.", flush=True)
                return {"unknown": {"mortes": mortes_count}}
            return data
    except json.JSONDecodeError:
        pass

    # Compatibilidade com formato antigo: MORTES: X
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if first_line.upper().startswith("MORTES:"):
        raw_value = first_line.split(":", 1)[1].strip()
        try:
            mortes = int(raw_value)
        except ValueError:
            mortes = 0
        print("[MIGRAÇÃO] Detectado formato muito antigo (MORTES: X). Migrando para novo formato por jogo.", flush=True)
        return {"unknown": {"mortes": mortes}}

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

# Incrementa o contador de mortes no arquivo para o jogo atual e retorna o novo total.
def increment_deaths_in_file():
    game_name = get_current_game_from_twitch()
    if not game_name:
        print("[WARNING] Não foi possível obter o jogo atual. Usando 'unknown'.", flush=True)
        game_name = "unknown"
    
    game_key = normalize_game_name(game_name)
    data = load_data()
    
    # Garante que o jogo existe no dicionário
    if game_key not in data or not isinstance(data[game_key], dict):
        data[game_key] = {"mortes": 0}
    
    # Incrementa o contador de mortes para o jogo
    raw_current = data[game_key].get("mortes", 0)
    try:
        current_total = int(raw_current)
    except (TypeError, ValueError):
        current_total = 0
    
    new_total = current_total + 1
    data[game_key]["mortes"] = new_total
    save_data(data)
    
    print(f"[MORTE] Incrementado: {game_key} agora tem {new_total} mortes", flush=True)
    return new_total

# Decrementa o contador de mortes no arquivo para o jogo atual e retorna o novo total.
def decrement_deaths_in_file():
    game_name = get_current_game_from_twitch()
    if not game_name:
        print("[WARNING] Não foi possível obter o jogo atual. Usando 'unknown'.", flush=True)
        game_name = "unknown"
    
    game_key = normalize_game_name(game_name)
    data = load_data()
    
    # Garante que o jogo existe no dicionário  
    if game_key not in data or not isinstance(data[game_key], dict):
        data[game_key] = {"mortes": 0}
    
    # Decrementa o contador de mortes para o jogo
    raw_current = data[game_key].get("mortes", 0)
    try:
        current_total = int(raw_current)
    except (TypeError, ValueError):
        current_total = 0
    
    new_total = current_total - 1
    data[game_key]["mortes"] = new_total
    save_data(data)
    
    print(f"[MORTE] Decrementado: {game_key} agora tem {new_total} mortes", flush=True)
    return new_total

# Lê o valor atual de mortes do jogo atual do arquivo, tentando garantir que seja um inteiro. Se não for possível, retorna 0.
def get_mortes_value(data):
    game_name = get_current_game_from_twitch()
    if not game_name:
        game_name = "unknown"
    
    game_key = normalize_game_name(game_name)
    
    if game_key not in data or not isinstance(data[game_key], dict):
        return 0
    
    raw_value = data[game_key].get("mortes", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0

# Retorna o total global de mortes (soma de todos os jogos)
def get_total_mortes_all_games(data):
    total = 0
    for game_key, game_data in data.items():
        if isinstance(game_data, dict):
            raw_value = game_data.get("mortes", 0)
            try:
                total += int(raw_value)
            except (TypeError, ValueError):
                pass
    return total

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
    all_games = request.args.get("all", "").lower() in ["true", "1", "yes"]
    
    if all_games:
        return str(get_total_mortes_all_games(data))
    else:
        return str(get_mortes_value(data))

# Endpoint para LER o valor atual de mortes em formato de observação (ex: "X mortes")
@app.route("/death/read/obs", methods=["GET"])
def read_text_observation():
    data = load_data()
    all_games = request.args.get("all", "").lower() in ["true", "1", "yes"]
    
    if all_games:
        mortes = get_total_mortes_all_games(data)
    else:
        mortes = get_mortes_value(data)
    
    return f"{mortes} MORTES"

# Endpoint opcional para limpar arquivo
@app.route("/death/clear", methods=["GET"])
def clear():
    save_data(dict(DEFAULT_DATA))
    return "0"

# Endpoint para INCREMENTAR o contador de mortes
@app.route("/death/increment", methods=["GET", "POST"])
def increment():
    new_total = increment_deaths_in_file()
    trigger_death_increment_event(new_total)
    return str(new_total)

# Endpoint para DECREMENTAR o contador de mortes
@app.route("/death/decrement", methods=["GET", "POST"])
def decrement():
    new_total = decrement_deaths_in_file()
    trigger_death_decrement_event(new_total)
    return str(new_total)

# Endpoint para obter informações do jogo atual
@app.route("/death/current-game", methods=["GET"])
def get_current_game():
    game_name = get_current_game_from_twitch()
    if not game_name:
        game_name = "unknown"
    
    game_key = normalize_game_name(game_name)
    data = load_data()
    mortes = 0
    
    if game_key in data and isinstance(data[game_key], dict):
        raw_value = data[game_key].get("mortes", 0)
        try:
            mortes = int(raw_value)
        except (TypeError, ValueError):
            mortes = 0
    
    return {
        "game_name": game_name,
        "game_key": game_key,
        "mortes": mortes,
    }, 200


# Endpoint para a stream: retorna apenas o nome do jogo atual.
@app.route("/stream/current-game", methods=["GET"])
def get_stream_current_game():
    game_name = get_current_game_from_twitch()
    if not game_name:
        game_name = "unknown"

    return game_name, 200

# Endpoint para retornar todos os dados de mortes por jogo
@app.route("/death/all", methods=["GET"])
def get_all_deaths():
    data = load_data()
    total = get_total_mortes_all_games(data)
    
    return {
        "total": total,
        "games": data,
    }, 200

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
    payload = request.get_json(silent=True) or {}
    message_id = (request.headers.get("Twitch-Eventsub-Message-Id", "") or "").strip()
    message_timestamp = (request.headers.get("Twitch-Eventsub-Message-Timestamp", "") or "").strip()
    message_type = (request.headers.get("Twitch-Eventsub-Message-Type", "") or "").strip().lower()

    # Responde o challenge imediatamente para nao bloquear a verificacao inicial do webhook.
    if message_type == "webhook_callback_verification":
        challenge = payload.get("challenge", "")
        return Response(challenge, status=200, mimetype="text/plain")

    if not is_valid_twitch_timestamp(message_timestamp):
        print(f"[TWITCH] Timestamp invalido: {message_timestamp}", flush=True)
        return {"error": "Timestamp Twitch invalido/expirado"}, 403

    if not verify_twitch_signature(raw_body):
        return {"error": "Assinatura Twitch invalida"}, 403

    if message_id in LAST_EVENT_IDS:
        print(f"[TWITCH] Evento duplicado ignorado: {message_id}", flush=True)
        return {"status": "duplicate"}, 200

    LAST_EVENT_IDS.add(message_id)
    if len(LAST_EVENT_IDS) > MAX_EVENT_IDS:
        LAST_EVENT_IDS.clear()
        LAST_EVENT_IDS.add(message_id)

    if message_type == "notification":
        event = payload.get("event", {}) if isinstance(payload.get("event", {}), dict) else {}
        reward = event.get("reward", {}) if isinstance(event.get("reward", {}), dict) else {}
        reward_title = str(reward.get("title", "")).strip()
        reward_id = str(reward.get("id", "")).strip()

        if should_process_reward(reward):
            mark_powerup_trigger(event)
            print(f"[TWITCH] Resgate processado id={reward_id} title={reward_title}", flush=True)
        else:
            print(f"[TWITCH] Resgate ignorado id={reward_id} title={reward_title}", flush=True)

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
        "last_event": POWERUP_EVENT_STATE["last_event"],
    }, 200

# Endpoint de teste manual para validar o listener sem depender da Twitch.
@app.route("/twitch/powerup/test", methods=["GET", "POST"])
def twitch_powerup_test():
    label = request.args.get("label") or request.form.get("label") or "TESTE"
    trigger_powerup_test(label)
    return {
        "status": "ok",
        "message": "powerup test triggered",
        "label": label,
        "seq": POWERUP_EVENT_STATE["seq"],
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
    return send_file_no_cache(BASE_DIR, "obs_powerup.html")

@app.route("/obs/powerup.js", methods=["GET"])
def obs_powerup_script():
    return send_file_no_cache(BASE_DIR, "obs_powerup.js")

@app.route("/obs/powerup.css", methods=["GET"])
def obs_powerup_styles():
    return send_file_no_cache(BASE_DIR, "obs_powerup.css")

# Arquivo de audio para a webpage do OBS.
@app.route("/obs/nossa.mp3", methods=["GET"])
def obs_powerup_audio():
    # Compatibilidade: se nao houver mp3, usa o ogg padrao.
    if os.path.exists(os.path.join(BASE_DIR, "nossa.mp3")):
        return send_file_no_cache(BASE_DIR, "nossa.mp3")
    return send_file_no_cache(OGG_DIR, "nossa.ogg")

@app.route("/ogg/nossa.ogg", methods=["GET"])
def obs_powerup_audio_ogg():
    return send_file_no_cache(OGG_DIR, "nossa.ogg")

@app.route("/ogg/morreu.ogg", methods=["GET"])
def obs_powerup_audio_morreu_ogg():
    return send_file_no_cache(OGG_DIR, "morreu.ogg")

@app.route("/ogg/plol.ogg", methods=["GET"])
def obs_powerup_audio_plol_ogg():
    return send_file_no_cache(OGG_DIR, "plol.ogg")

@app.route("/mp3/<path:filename>", methods=["GET"])
def mp3_assets(filename):
    return send_file_no_cache(MP3_DIR, filename)

if __name__ == "__main__":
    log_env_status()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
