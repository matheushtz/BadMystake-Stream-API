from flask import Flask, request, Response, send_from_directory
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from html import unescape
from urllib import error, parse, request as urllib_request

try:
    from gtts import gTTS
except Exception:
    gTTS = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "dados.json")
STEAM_GAMES_FILE = os.path.join(BASE_DIR, "steam_games.json")
OGG_DIR = os.path.join(BASE_DIR, "ogg")
MP3_DIR = os.path.join(BASE_DIR, "mp3")
GENERATED_TTS_DIR = os.path.join(MP3_DIR, "tts-generated")
DEFAULT_DATA = {}
DEFAULT_TTS_REWARD_IDENTIFIERS = {
    "965c119b-f6c7-4418-a407-dd6084e6c591",
    "toca mensagem (tts)",
}

APP_BOOT_TIME = int(os.times().elapsed)

DEFAULT_BACKEND_TTS_LANG = "pt"
MAX_TTS_FILE_AGE_SECONDS = 20 * 60
MAX_TTS_FILE_COUNT = 200

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
        "STEAM_WEB_API_KEY": env_present("STEAM_WEB_API_KEY"),
        "STEAM_API_KEY": env_present("STEAM_API_KEY"),
        "STEAM_TARGET_STEAMID64": env_present("STEAM_TARGET_STEAMID64"),
        "TWITCH_CHANNEL_ID": env_present("TWITCH_CHANNEL_ID"),
        "TWITCH_DEV_ID": env_present("TWITCH_DEV_ID"),
        "TWITCH_SECRET": env_present("TWITCH_SECRET"),
        "TWITCH_TOKEN": env_present("TWITCH_TOKEN"),
        "TWITCH_WEBHOOK_SECRET": env_present("TWITCH_WEBHOOK_SECRET"),
        "TWITCH_CLIENT_ID": env_present("TWITCH_CLIENT_ID"),
        "TWITCH_CLIENT_SECRET": env_present("TWITCH_CLIENT_SECRET"),
        "TWITCH_TTS_REWARD_IDS": env_present("TWITCH_TTS_REWARD_IDS"),
        "TWITCH_TTS_REWARD_ID": env_present("TWITCH_TTS_REWARD_ID"),
        "TWITCH_TTS_LANG": env_present("TWITCH_TTS_LANG"),
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

def get_env_identifiers(*names):
    identifiers = set()

    for name in names:
        raw_value = (os.environ.get(name, "") or "").strip()
        if not raw_value:
            continue

        for part in re.split(r"[,;\n]+", raw_value):
            normalized = part.strip().lower()
            if normalized:
                identifiers.add(normalized)

    return identifiers

def normalize_tts_text(text, max_length=240):
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip() + "..."
    return normalized

def get_tts_reward_identifiers():
    configured_identifiers = set(DEFAULT_TTS_REWARD_IDENTIFIERS)
    configured_identifiers.update(get_env_identifiers("TWITCH_TTS_REWARD_IDS", "TWITCH_TTS_REWARD_ID"))
    return configured_identifiers

def is_tts_reward(reward):
    if not isinstance(reward, dict):
        return False

    configured_identifiers = get_tts_reward_identifiers()
    if not configured_identifiers:
        return False

    reward_id = str(reward.get("id", "") or "").strip().lower()
    reward_title = str(reward.get("title", "") or "").strip().lower()
    return reward_id in configured_identifiers or reward_title in configured_identifiers

def build_tts_text(event_payload):
    if not isinstance(event_payload, dict):
        return ""

    user_input = normalize_tts_text(event_payload.get("user_input", ""))
    if user_input:
        return user_input

    user_name = normalize_tts_text(event_payload.get("user_name", ""))
    reward = event_payload.get("reward", {}) if isinstance(event_payload.get("reward", {}), dict) else {}
    reward_title = normalize_tts_text(reward.get("title", ""))

    parts = []
    if user_name:
        parts.append(user_name)

    if reward_title:
        if parts:
            parts.append("resgatou")
        parts.append(reward_title)

    return normalize_tts_text(" ".join(parts))

def normalize_backend_tts_lang(tts_lang):
    normalized = str(tts_lang or "").strip().lower()
    if not normalized:
        return DEFAULT_BACKEND_TTS_LANG

    if normalized.startswith("pt"):
        return "pt"

    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]

    if len(normalized) < 2:
        return DEFAULT_BACKEND_TTS_LANG

    return normalized

def cleanup_generated_tts_files():
    if not os.path.isdir(GENERATED_TTS_DIR):
        return

    now = time.time()
    file_entries = []

    for name in os.listdir(GENERATED_TTS_DIR):
        if not name.lower().endswith(".mp3"):
            continue

        full_path = os.path.join(GENERATED_TTS_DIR, name)
        if not os.path.isfile(full_path):
            continue

        try:
            stat = os.stat(full_path)
        except OSError:
            continue

        age_seconds = now - stat.st_mtime
        if age_seconds > MAX_TTS_FILE_AGE_SECONDS:
            try:
                os.remove(full_path)
            except OSError:
                pass
            continue

        file_entries.append((stat.st_mtime, full_path))

    if len(file_entries) <= MAX_TTS_FILE_COUNT:
        return

    file_entries.sort(key=lambda entry: entry[0])
    extra_count = len(file_entries) - MAX_TTS_FILE_COUNT

    for _, full_path in file_entries[:extra_count]:
        try:
            os.remove(full_path)
        except OSError:
            pass

def generate_tts_audio_url(tts_text, tts_lang):
    text = normalize_tts_text(tts_text)
    if not text:
        return ""

    if gTTS is None:
        print("[TTS] gTTS indisponivel. Adicione a dependencia no ambiente.", flush=True)
        return ""

    os.makedirs(GENERATED_TTS_DIR, exist_ok=True)
    cleanup_generated_tts_files()

    lang = normalize_backend_tts_lang(tts_lang)
    filename = f"tts-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.mp3"
    output_path = os.path.join(GENERATED_TTS_DIR, filename)

    try:
        gTTS(text=text, lang=lang).save(output_path)
    except Exception as exc:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass

        print(f"[TTS] Falha ao gerar audio ({lang}): {exc}", flush=True)
        return ""

    return f"/mp3/tts-generated/{filename}"

def attach_backend_tts_audio(event_payload):
    if not isinstance(event_payload, dict):
        return

    tts_text = normalize_tts_text(event_payload.get("tts_text", ""))
    if not tts_text:
        return

    tts_lang = event_payload.get("tts_lang") or get_first_env("TWITCH_TTS_LANG") or "pt-BR"
    event_payload["tts_text"] = tts_text
    event_payload["tts_lang"] = tts_lang

    tts_audio_url = generate_tts_audio_url(tts_text, tts_lang)
    if tts_audio_url:
        event_payload["tts_audio_url"] = tts_audio_url
        event_payload["tts_engine"] = "gtts"

def steam_target_steamid64():
    return get_first_env("STEAM_TARGET_STEAMID64")

def steam_web_api_key():
    return get_first_env("STEAM_WEB_API_KEY", "STEAM_API_KEY")

def is_valid_steam_web_api_key(api_key):
    if not api_key:
        return False

    if len(api_key) != 32:
        return False

    return all(ch in "0123456789abcdefABCDEF" for ch in api_key)

def load_steam_games():
    if not os.path.exists(STEAM_GAMES_FILE):
        return {}

    try:
        with open(STEAM_GAMES_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()

        if not content:
            return {}

        raw_data = json.loads(content)
        if not isinstance(raw_data, dict):
            return {}

        normalized_data = {}
        for game_name, appid in raw_data.items():
            try:
                normalized_data[str(game_name)] = int(appid)
            except (TypeError, ValueError):
                continue

        return normalized_data
    except Exception as exc:
        print(f"[STEAM] Falha ao ler {STEAM_GAMES_FILE}: {exc}", flush=True)
        return {}

def save_steam_games(games):
    serialized = json.dumps(games, ensure_ascii=False, indent=2, sort_keys=True)
    with open(STEAM_GAMES_FILE, "w", encoding="utf-8") as f:
        f.write(serialized)

    publish_file_to_github(
        serialized,
        default_file_path="steam_games.json",
        commit_message="chore: update steam_games.json",
        file_path_env="GITHUB_STEAM_GAMES_FILE_PATH",
    )

def find_cached_steam_game(game_name, games):
    requested_name = normalize_game_name(game_name)

    for mapped_name, appid in games.items():
        if normalize_game_name(mapped_name) == requested_name:
            try:
                return mapped_name, int(appid)
            except (TypeError, ValueError):
                return mapped_name, None

    return None, None

def search_steam_store_game(game_name):
    search_url = (
        "https://store.steampowered.com/search/results/"
        f"?term={parse.quote(game_name)}&format=json&count=10&category1=998&ndl=1"
    )

    req = urllib_request.Request(
        search_url,
        headers={"User-Agent": "death-counter-api"},
        method="GET",
    )

    with urllib_request.urlopen(req, timeout=15) as response:
        html = response.read().decode("utf-8", errors="replace")

    row_pattern = re.compile(
        r'<a[^>]*class="search_result_row[^\"]*"[^>]*>.*?</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in row_pattern.finditer(html):
        row_html = match.group(0)

        appid_match = re.search(r'store\.steampowered\.com/app/(\d+)/', row_html, re.IGNORECASE)
        if not appid_match:
            continue

        appid = appid_match.group(1)

        title_match = re.search(r'<span class="title">([^<]+)</span>', row_html, re.IGNORECASE)
        if title_match:
            title = unescape(title_match.group(1)).strip()
        else:
            title = game_name.strip()

        try:
            return title, int(appid)
        except (TypeError, ValueError):
            continue

    appid_match = re.search(r'store\.steampowered\.com/app/(\d+)/', html, re.IGNORECASE)
    if appid_match:
        try:
            return game_name.strip(), int(appid_match.group(1))
        except (TypeError, ValueError):
            return None, None

    return None, None

def get_steam_game_entry(game_name):
    if not game_name:
        return None, None

    games = load_steam_games()
    cached_name, appid = find_cached_steam_game(game_name, games)
    if cached_name and appid:
        return cached_name, appid

    store_name, store_appid = search_steam_store_game(game_name)
    if store_name and store_appid:
        games[store_name] = store_appid
        save_steam_games(games)
        return store_name, store_appid

    return None, None

def steam_api_get_json(url, timeout=15):
    req = urllib_request.Request(
        url,
        headers={"User-Agent": "death-counter-api"},
        method="GET",
    )

    with urllib_request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def get_steam_player_achievement_count(steamid64, appid, api_key):
    api_url = (
        "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/"
        f"?key={parse.quote(api_key)}&steamid={steamid64}&appid={appid}"
    )

    payload = steam_api_get_json(api_url)
    player_stats = payload.get("playerstats", {})
    achievements = player_stats.get("achievements", [])

    if not isinstance(achievements, list):
        return 0

    unlocked = 0
    for achievement in achievements:
        if not isinstance(achievement, dict):
            continue

        raw_value = achievement.get("achieved", 0)
        try:
            achieved = int(raw_value)
        except (TypeError, ValueError):
            achieved = 1 if str(raw_value).strip().lower() in ["true", "yes"] else 0

        if achieved == 1:
            unlocked += 1

    return unlocked

def get_steam_total_achievement_count(appid, api_key):
    api_url = (
        "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"
        f"?key={parse.quote(api_key)}&appid={appid}"
    )

    payload = steam_api_get_json(api_url)
    game = payload.get("game", {})
    available_stats = game.get("availableGameStats", {}) if isinstance(game, dict) else {}
    achievements = available_stats.get("achievements", []) if isinstance(available_stats, dict) else []

    if not isinstance(achievements, list):
        return 0

    return len(achievements)

def format_steam_achievement_summary(game_name, unlocked, total):
    percentage = 0.0
    if total > 0:
        percentage = (unlocked / total) * 100

    percentage_text = f"{percentage:.2f}".replace(".", ",")
    return f"{game_name}: {unlocked} de {total} ({percentage_text}% concluído)"

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

def trigger_powerup_test(label="TESTE", tts_text=None):
    event_payload = {
        "reward": {
            "title": label,
        },
        "source": "powerup-test",
    }

    if tts_text:
        event_payload["tts_text"] = normalize_tts_text(tts_text)
        event_payload["tts_lang"] = get_first_env("TWITCH_TTS_LANG") or "pt-BR"
        attach_backend_tts_audio(event_payload)
    else:
        event_payload["sound_file"] = "nossa.ogg"

    mark_powerup_trigger(event_payload)

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
def get_github_publish_config(default_file_path="dados.json", file_path_env="GITHUB_FILE_PATH"):
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
        "file_path": (os.environ.get(file_path_env, "") or "").strip() or default_file_path,
    }

# Publica o conteúdo no GitHub usando a API. O conteúdo deve ser uma string já formatada (ex: JSON).
def publish_file_to_github(content, default_file_path="dados.json", commit_message=None, file_path_env="GITHUB_FILE_PATH"):
    config = get_github_publish_config(default_file_path=default_file_path, file_path_env=file_path_env)
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
        "message": commit_message or f"chore: update {file_path}",
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
        print(f"Falha ao publicar {file_path} no GitHub: HTTP {http_err.code} - {body}")
    except Exception as exc:
        print(f"Falha ao publicar {file_path} no GitHub: {exc}")

def publish_data_to_github(content):
    publish_file_to_github(content, default_file_path="dados.json", commit_message="chore: update dados.json", file_path_env="GITHUB_FILE_PATH")

# Salva os dados no arquivo local e publica no GitHub (se configurado)
def save_data(data):
    serialized_data = json.dumps(data, ensure_ascii=False, indent=2)

    with open(FILE_PATH, "w", encoding="utf-8") as f:
        f.write(serialized_data)

    publish_data_to_github(serialized_data)

def resolve_steam_achievement_game_name():
    requested_game = (request.args.get("game") or "").strip()
    if requested_game:
        return requested_game

    current_game = get_current_game_from_twitch()
    if current_game:
        return current_game.strip()

    return "Outer Wilds"

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
    game_name = (
        request.args.get("jogo")
        or request.form.get("jogo")
        or payload.get("jogo")
        or request.args.get("game")
        or request.form.get("game")
        or payload.get("game")
        or request.args.get("key")
        or request.form.get("key")
        or payload.get("key")
    )
    mortes_value = (
        request.args.get("mortes")
        or request.form.get("mortes")
        or payload.get("mortes")
        or request.args.get("value")
        or request.form.get("value")
        or payload.get("value")
    )

    if not game_name:
        return {"error": "Nenhum jogo enviado"}, 400

    if mortes_value is None:
        return {"error": "Nenhum valor de mortes enviado"}, 400

    try:
        mortes = int(parse_value(mortes_value))
    except (TypeError, ValueError):
        return {"error": "Valor de mortes invalido"}, 400

    game_key = normalize_game_name(str(game_name))
    data = load_data()

    if game_key not in data or not isinstance(data[game_key], dict):
        data[game_key] = {"mortes": 0}

    data[game_key]["mortes"] = mortes
    save_data(data)

    return str(mortes)

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


# Endpoint para retornar conquistas da Steam de um jogo mapeado.
@app.route("/steam/achievements", methods=["GET"])
@app.route("/steam/achievements/", methods=["GET"])
def steam_achievements():
    game_name = resolve_steam_achievement_game_name()
    mapped_name, appid = get_steam_game_entry(game_name)

    if not mapped_name or not appid:
        available_games = sorted(load_steam_games().keys())
        return {
            "error": f"Jogo nao mapeado: {game_name}",
            "available_games": available_games,
        }, 404

    api_key = steam_web_api_key()
    steamid64 = steam_target_steamid64()
    if not api_key:
        return {
            "error": "Defina STEAM_WEB_API_KEY (ou STEAM_API_KEY) no ambiente para consultar as conquistas da Steam",
        }, 400

    if not is_valid_steam_web_api_key(api_key):
        return {
            "error": "Steam API key invalida. Verifique se a chave possui 32 caracteres hexadecimais.",
        }, 400

    if not steamid64:
        return {
            "error": "Defina STEAM_TARGET_STEAMID64 no ambiente para consultar as conquistas da Steam",
        }, 400

    try:
        unlocked = get_steam_player_achievement_count(steamid64, appid, api_key)
        total = get_steam_total_achievement_count(appid, api_key)
    except error.HTTPError as http_err:
        try:
            body = http_err.read().decode("utf-8")
        except Exception:
            body = "<sem corpo>"

        if http_err.code == 403:
            return {
                "error": "Steam recusou a API key (HTTP 403). Gere/valide sua chave em steamcommunity.com/dev/apikey e confirme a variavel STEAM_WEB_API_KEY no Render.",
            }, 502

        return {
            "error": f"Steam HTTP {http_err.code} - {body}",
        }, 502
    except Exception as exc:
        return {
            "error": f"Falha ao consultar Steam: {exc}",
        }, 500

    summary = format_steam_achievement_summary(mapped_name, unlocked, total)
    return Response(summary, status=200, mimetype="text/plain; charset=utf-8")


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
        event_payload = dict(event)

        if should_process_reward(reward):
            if is_tts_reward(reward):
                tts_text = build_tts_text(event_payload)
                if tts_text:
                    event_payload["tts_text"] = tts_text
                    event_payload["tts_lang"] = get_first_env("TWITCH_TTS_LANG") or "pt-BR"
                    attach_backend_tts_audio(event_payload)

            mark_powerup_trigger(event_payload)
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
    text = request.args.get("text") or request.form.get("text") or ""
    trigger_powerup_test(label, text)
    return {
        "status": "ok",
        "message": "powerup test triggered",
        "label": label,
        "text": text,
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

# Webpage para OBS: roleta/torchlight
@app.route("/torchlight/roleta/obs", methods=["GET"])
def obs_roleta_page():
    return send_file_no_cache(BASE_DIR, "torchlight_roleta_obs.html")

@app.route("/torchlight/roleta/obs.js", methods=["GET"])
def obs_roleta_script():
    return send_file_no_cache(BASE_DIR, "torchlight_roleta_obs.js")

@app.route("/torchlight/roleta/obs.css", methods=["GET"])
def obs_roleta_styles():
    return send_file_no_cache(BASE_DIR, "torchlight_roleta_obs.css")
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
