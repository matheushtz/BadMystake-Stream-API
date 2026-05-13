from flask import Flask, request, Response, send_from_directory
import base64
import importlib
import hashlib
import hmac
import json
import os
import sys
import threading
import ctypes
from collections import OrderedDict
# Prevent ONNXRuntime from probing GPU devices in environments without drivers.
# This suppresses warnings like: Failed to detect devices under "/sys/class/drm/card0"
# and forces CPU-only execution unless explicit GPU providers are used.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("ROCM_VISIBLE_DEVICES", "")
os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
import re
import random
import time
import uuid
import wave
import io
import struct
from functools import lru_cache
from datetime import datetime, timezone
from html import unescape
from urllib import error, parse, request as urllib_request

# Piper TTS synthesis config (imported on demand to avoid import errors if piper not installed)
_synthesis_config = None
def get_synthesis_config():
    global _synthesis_config
    if _synthesis_config is not None:
        return _synthesis_config
    try:
        from piper.config import SynthesisConfig
        _synthesis_config = SynthesisConfig()
        return _synthesis_config
    except ImportError:
        return None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
JSON_DIR = os.path.join(PROJECT_ROOT, "json")
HTML_DIR = os.path.join(PROJECT_ROOT, "html")
CSS_DIR = os.path.join(PROJECT_ROOT, "css")
JS_DIR = os.path.join(PROJECT_ROOT, "js")
OGG_DIR = os.path.join(PROJECT_ROOT, "ogg")
MP3_DIR = os.path.join(PROJECT_ROOT, "mp3")
FILE_PATH = os.path.join(JSON_DIR, "dados.json")
STEAM_GAMES_FILE = os.path.join(JSON_DIR, "steam_games.json")
GENERATED_TTS_DIR = os.path.join(MP3_DIR, "tts-generated")
DEFAULT_DATA = {}
DEFAULT_TTS_REWARD_IDENTIFIERS = {
    "965c119b-f6c7-4418-a407-dd6084e6c591",
    "toca mensagem (tts)",
}

APP_BOOT_TIME = int(os.times().elapsed)

DEFAULT_BACKEND_TTS_LANG = "pt"
DEFAULT_PIPER_TTS_LANG = "pt-BR"
DEFAULT_PIPER_VOICE_NAME = "pt_BR-cadu-medium"
PIPER_MODEL_DIR = os.path.join(PROJECT_ROOT, "tts-model")
PIPER_JSON_DIR = os.path.join(PROJECT_ROOT, "tts-json")
TTS_CONFIG_FILE = os.path.join(JSON_DIR, "tts_config.json")
DEFAULT_TTS_SPEED = 1.0
MIN_TTS_SPEED = 0.5
MAX_TTS_SPEED = 2.0
MAX_TTS_FILE_AGE_SECONDS = 20 * 60
MAX_TTS_FILE_COUNT = 5

# TTS Audio Cache em memória (sem disco para compatibilidade com Render/serverless)
# Estrutura: {cache_id: (audio_bytes, engine, timestamp)}
TTS_AUDIO_CACHE = OrderedDict()
TTS_AUDIO_CACHE_MAX_SIZE_MB = 100
TTS_AUDIO_CACHE_TTL_SECONDS = 60  # 1 minuto
TTS_AUDIO_CACHE_LOCK = threading.Lock()
MAX_SINGLE_TTS_BYTES = 50 * 1024 * 1024  # 50 MB per item safety cap
# Track last-used voices to avoid repeating the same voice consecutively
TTS_LAST_VOICE = {
    "piper": None,
    "gtts": None,
}
TTS_CACHE_MONITOR_LOCK = threading.Lock()
TTS_CACHE_MONITOR_ACTIVE = False

def get_process_memory_stats():
    """Return process memory stats in MB when possible."""
    stats = {
        "rss_mb": None,
        "vms_mb": None,
        "source": "unknown",
    }

    try:
        psutil_module = importlib.import_module("psutil")
        process = psutil_module.Process(os.getpid())
        mem_info = process.memory_info()
        stats["rss_mb"] = round(mem_info.rss / (1024 * 1024), 2)
        stats["vms_mb"] = round(mem_info.vms / (1024 * 1024), 2) if hasattr(mem_info, "vms") else None
        stats["source"] = "psutil"
        return stats
    except Exception:
        pass

    if os.name == "nt":
        try:
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)

            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                ctypes.c_ulong,
            ]
            psapi.GetProcessMemoryInfo.restype = ctypes.c_bool

            handle = kernel32.GetCurrentProcess()
            result = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            if result:
                stats["rss_mb"] = round(counters.WorkingSetSize / (1024 * 1024), 2)
                stats["vms_mb"] = round(counters.PagefileUsage / (1024 * 1024), 2)
                stats["source"] = "ctypes-windows"
                return stats
        except Exception:
            pass

    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_kb = getattr(usage, "ru_maxrss", 0)
        if rss_kb:
            # On Linux this is KB, on macOS it is bytes. Convert conservatively.
            rss_mb = rss_kb / 1024.0
            if rss_mb > 1024 * 1024:
                rss_mb = rss_kb / (1024.0 * 1024.0)
            stats["rss_mb"] = round(rss_mb, 2)
            stats["source"] = "resource"
    except Exception:
        pass

    return stats

def get_tts_cache_stats():
    with TTS_AUDIO_CACHE_LOCK:
        total_size_bytes = sum(len(audio_bytes) for audio_bytes, _, _ in TTS_AUDIO_CACHE.values())
        return {
            "items": len(TTS_AUDIO_CACHE),
            "size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "ttl_seconds": TTS_AUDIO_CACHE_TTL_SECONDS,
            "max_single_bytes": MAX_SINGLE_TTS_BYTES,
        }

def log_tts_cache_stats(prefix="[TTS-CACHE]"):
    stats = get_tts_cache_stats()
    print(
        f"{prefix} items={stats['items']} size_mb={stats['size_mb']:.2f} ttl_seconds={stats['ttl_seconds']} max_single_bytes={stats['max_single_bytes']}",
        flush=True,
    )

def get_all_memory_stats():
    """Return comprehensive memory metrics for all API components."""
    import sys
    
    memory_stats = get_process_memory_stats()
    
    # TTS Audio Cache
    with TTS_AUDIO_CACHE_LOCK:
        tts_cache_bytes = sum(len(audio_bytes) for audio_bytes, _, _ in TTS_AUDIO_CACHE.values())
        tts_cache_items = len(TTS_AUDIO_CACHE)
    
    # POWERUP_EVENT_STATE
    powerup_state_bytes = len(json.dumps(POWERUP_EVENT_STATE, ensure_ascii=False).encode('utf-8'))
    
    # LAST_EVENT_IDS (set of strings)
    last_event_ids_bytes = sum(sys.getsizeof(event_id) for event_id in LAST_EVENT_IDS) + sys.getsizeof(LAST_EVENT_IDS)
    last_event_ids_count = len(LAST_EVENT_IDS)
    
    # TTS_LAST_VOICE
    tts_voice_bytes = sys.getsizeof(TTS_LAST_VOICE) + sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in TTS_LAST_VOICE.items())
    
    # Total in-memory data
    total_managed_bytes = tts_cache_bytes + powerup_state_bytes + last_event_ids_bytes + tts_voice_bytes
    
    return {
        "process": memory_stats,
        "components": {
            "tts_cache": {
                "items": tts_cache_items,
                "bytes": tts_cache_bytes,
                "mb": round(tts_cache_bytes / (1024 * 1024), 2),
                "ttl_seconds": TTS_AUDIO_CACHE_TTL_SECONDS,
                "max_single_bytes": MAX_SINGLE_TTS_BYTES,
                "max_total_mb": TTS_AUDIO_CACHE_MAX_SIZE_MB,
            },
            "powerup_event_state": {
                "bytes": powerup_state_bytes,
                "kb": round(powerup_state_bytes / 1024, 2),
                "seq": POWERUP_EVENT_STATE["seq"],
                "last_reward": POWERUP_EVENT_STATE["last_reward"],
            },
            "last_event_ids": {
                "count": last_event_ids_count,
                "bytes": last_event_ids_bytes,
                "kb": round(last_event_ids_bytes / 1024, 2),
                "max_count": MAX_EVENT_IDS,
            },
            "tts_last_voice": {
                "bytes": tts_voice_bytes,
                "kb": round(tts_voice_bytes / 1024, 2),
                "data": TTS_LAST_VOICE,
            },
        },
        "summary": {
            "total_managed_mb": round(total_managed_bytes / (1024 * 1024), 2),
            "total_managed_bytes": total_managed_bytes,
            "process_rss_mb": memory_stats.get("rss_mb"),
        },
    }

def start_tts_cache_monitor():
    global TTS_CACHE_MONITOR_ACTIVE

    with TTS_CACHE_MONITOR_LOCK:
        if TTS_CACHE_MONITOR_ACTIVE:
            return
        TTS_CACHE_MONITOR_ACTIVE = True

    def _monitor():
        global TTS_CACHE_MONITOR_ACTIVE
        try:
            log_tts_cache_stats("[TTS-CACHE][MONITOR] start")

            while True:
                cleanup_expired_tts_cache()
                stats = get_tts_cache_stats()
                print(
                    f"[TTS-CACHE][MONITOR] items={stats['items']} size_mb={stats['size_mb']:.2f} ttl_seconds={stats['ttl_seconds']} max_single_bytes={stats['max_single_bytes']}",
                    flush=True,
                )

                if stats["items"] <= 0:
                    break

                time.sleep(1)
        finally:
            with TTS_CACHE_MONITOR_LOCK:
                TTS_CACHE_MONITOR_ACTIVE = False
            print("[TTS-CACHE][MONITOR] stopped", flush=True)

    thread = threading.Thread(target=_monitor, name="tts-cache-monitor", daemon=True)
    thread.start()

def get_configured_tts_speed(model_name=None):
    speed = DEFAULT_TTS_SPEED

    try:
        if os.path.isfile(TTS_CONFIG_FILE):
            with open(TTS_CONFIG_FILE, "r", encoding="utf-8") as config_file:
                config_data = json.load(config_file)

            if isinstance(config_data, dict):
                # Se há nome de modelo, busca configuração específica
                if model_name and model_name in config_data:
                    model_config = config_data.get(model_name)
                    if isinstance(model_config, dict) and "tts_speed" in model_config:
                        speed = float(model_config.get("tts_speed"))
                # Fallback: busca chave legada "tts_speed" no root
                elif "tts_speed" in config_data:
                    speed = float(config_data.get("tts_speed"))
    except Exception as exc:
        print(f"[TTS] Falha ao ler config de velocidade ({TTS_CONFIG_FILE}): {exc}", flush=True)

    if speed < MIN_TTS_SPEED:
        speed = MIN_TTS_SPEED
    if speed > MAX_TTS_SPEED:
        speed = MAX_TTS_SPEED

    return speed

def apply_piper_tts_speed(syn_config, model_name=None):
    if syn_config is None:
        return DEFAULT_TTS_SPEED

    speed = get_configured_tts_speed(model_name)

    # Piper versions differ in field names; try common direct speed fields first.
    for attr_name in ("speed", "rate", "speaking_rate", "tempo", "pace"):
        if hasattr(syn_config, attr_name):
            try:
                setattr(syn_config, attr_name, speed)
                return speed
            except Exception:
                pass

    # Piper commonly exposes length_scale: higher value = slower speech.
    if hasattr(syn_config, "length_scale"):
        try:
            setattr(syn_config, "length_scale", 1.0 / speed)
            return speed
        except Exception:
            pass

    return speed

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
        "PIPER_TTS_MODEL_DIR": env_present("PIPER_TTS_MODEL_DIR"),
        "PIPER_TTS_JSON_DIR": env_present("PIPER_TTS_JSON_DIR"),
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

def get_tts_cache_id(text, engine="piper", voice=None):
    """Gera ID único para cache de áudio TTS incluindo engine e voz"""
    v = voice or ""
    key = f"{text}_{engine}_{v}".encode('utf-8')
    return hashlib.sha256(key).hexdigest()

def cleanup_expired_tts_cache():
    """Remove áudios do cache que expiraram (TTL > 60s)"""
    now = time.time()
    expired_keys = []
    
    with TTS_AUDIO_CACHE_LOCK:
        for cache_id, (_, _, timestamp) in TTS_AUDIO_CACHE.items():
            if now - timestamp > TTS_AUDIO_CACHE_TTL_SECONDS:
                expired_keys.append(cache_id)
        
        for cache_id in expired_keys:
            del TTS_AUDIO_CACHE[cache_id]
            print(f"[TTS-CACHE] Expirado: {cache_id[:8]}...", flush=True)

def add_to_tts_cache(cache_id, audio_bytes, engine):
    """Adiciona áudio ao cache com proteção de tamanho máximo"""
    cleanup_expired_tts_cache()
    # Safety: refuse to cache absurdly large single items
    try:
        size_bytes = len(audio_bytes)
    except Exception:
        size_bytes = 0

    if size_bytes > MAX_SINGLE_TTS_BYTES:
        print(f"[TTS-CACHE] Arquivo muito grande para cache ({size_bytes} bytes), não armazenado: {cache_id[:8]}...", flush=True)
        return False

    with TTS_AUDIO_CACHE_LOCK:
        # Remove se já existe (reinsert no final da OrderedDict)
        if cache_id in TTS_AUDIO_CACHE:
            del TTS_AUDIO_CACHE[cache_id]
        
        TTS_AUDIO_CACHE[cache_id] = (audio_bytes, engine, time.time())
        
        # Calcula tamanho total do cache
        total_size_bytes = sum(len(data) for data, _, _ in TTS_AUDIO_CACHE.values())
        total_size_mb = total_size_bytes / (1024 * 1024)
        
        # Remove itens antigos se excede limite
        while total_size_mb > TTS_AUDIO_CACHE_MAX_SIZE_MB and len(TTS_AUDIO_CACHE) > 1:
            old_id, old_data = TTS_AUDIO_CACHE.popitem(last=False)
            total_size_bytes -= len(old_data[0])
            total_size_mb = total_size_bytes / (1024 * 1024)
            print(f"[TTS-CACHE] Removido (limite): {old_id[:8]}...", flush=True)
        
        print(f"[TTS-CACHE] Adicionado: {cache_id[:8]}... (tamanho={len(audio_bytes)/1024:.1f}KB, cache_total={total_size_mb:.1f}MB)", flush=True)
    return True

def get_from_tts_cache(cache_id):
    """Recupera áudio do cache"""
    with TTS_AUDIO_CACHE_LOCK:
        if cache_id in TTS_AUDIO_CACHE:
            audio_bytes, engine, timestamp = TTS_AUDIO_CACHE[cache_id]
            age = time.time() - timestamp
            if age > TTS_AUDIO_CACHE_TTL_SECONDS:
                del TTS_AUDIO_CACHE[cache_id]
                print(f"[TTS-CACHE] Expirado durante acesso: {cache_id[:8]}...", flush=True)
                return None, None
            
            print(f"[TTS-CACHE] Hit: {cache_id[:8]}... (idade={age:.1f}s, engine={engine})", flush=True)
            return audio_bytes, engine
    
    return None, None

@lru_cache(maxsize=1)
def get_piper_voice_class():
    for module_name in ("piper", "piper.voice"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        voice_class = getattr(module, "PiperVoice", None)
        if voice_class is not None:
            return voice_class

    return None

def get_piper_voice_pairs():
    model_dir = (os.environ.get("PIPER_TTS_MODEL_DIR", "") or "").strip() or PIPER_MODEL_DIR
    json_dir = (os.environ.get("PIPER_TTS_JSON_DIR", "") or "").strip() or PIPER_JSON_DIR

    if not os.path.isdir(model_dir) or not os.path.isdir(json_dir):
        return []

    model_files = []
    for name in os.listdir(model_dir):
        if name.lower().endswith(".onnx"):
            model_files.append(os.path.join(model_dir, name))

    pairs = []
    for model_path in model_files:
        model_name = os.path.basename(model_path)
        config_path = os.path.join(json_dir, f"{model_name}.json")
        if os.path.isfile(config_path):
            pairs.append((model_path, config_path))

    return pairs

def pick_random_piper_voice_pair():
    pairs = get_piper_voice_pairs()
    if not pairs:
        return None, None

    # Prefer a random voice that is not the one used last time (if possible)
    last = TTS_LAST_VOICE.get("piper")
    if last:
        others = [p for p in pairs if os.path.basename(p[0]) != last]
        if others:
            return random.choice(others)

    return random.choice(pairs)

@lru_cache(maxsize=2)
def load_piper_voice(model_path, config_path):
    piper_voice_class = get_piper_voice_class()
    if piper_voice_class is None:
        raise RuntimeError("Piper TTS indisponivel. Instale a dependencia piper-tts.")

    return piper_voice_class.load(model_path, config_path=config_path, use_cuda=False)

@lru_cache(maxsize=1)
def get_gtts_class():
    try:
        module = importlib.import_module("gtts")
    except Exception:
        return None

    return getattr(module, "gTTS", None)

def cleanup_generated_tts_files():
    if not os.path.isdir(GENERATED_TTS_DIR):
        return

    now = time.time()
    file_entries = []

    for name in os.listdir(GENERATED_TTS_DIR):
        if not name.lower().endswith((".mp3", ".wav")):
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


def validate_generated_wav_file(wav_path):
    try:
        if not os.path.isfile(wav_path):
            return False, "arquivo ausente"

        file_size = os.path.getsize(wav_path)
        if file_size <= 44:
            return False, f"arquivo muito pequeno ({file_size} bytes)"

        with wave.open(wav_path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()

        if channels <= 0:
            return False, "nchannels invalido"
        if sample_width <= 0:
            return False, "sampwidth invalido"
        if frame_rate <= 0:
            return False, "framerate invalido"
        if frame_count <= 0:
            return False, "nframes invalido"

        return True, "ok"
    except Exception as exc:
        return False, f"falha ao validar wav: {exc}"

def generate_tts_audio(tts_text, tts_lang):
    start_time = time.time()
    text = normalize_tts_text(tts_text)
    if not text:
        return "", ""

    print(f"[TTS] Texto normalizado para sintetiza: '{text}' (len={len(text)})", flush=True)

    piper_pairs = get_piper_voice_pairs()

    if get_piper_voice_class() is not None and piper_pairs:
        # Build prioritized list avoiding last-used voice when possible
        last = TTS_LAST_VOICE.get("piper")
        prioritized = [p for p in piper_pairs if os.path.basename(p[0]) != last]
        remaining = [p for p in piper_pairs if os.path.basename(p[0]) == last]
        random.shuffle(prioritized)
        random.shuffle(remaining)
        ordered_pairs = prioritized + remaining

        for model_path, config_path in ordered_pairs:
            model_name = os.path.splitext(os.path.basename(model_path))[0]
            # Check cache per text+engine+voice
            cache_id = get_tts_cache_id(text, engine="piper", voice=model_name)
            cached_bytes, cached_engine = get_from_tts_cache(cache_id)
            if cached_bytes:
                print(f"[TTS] Usando áudio em cache: {cache_id[:8]}... (voice={model_name})", flush=True)
                # record last-used
                TTS_LAST_VOICE["piper"] = os.path.basename(model_path)
                return cache_id, cached_engine

            try:
                print(f"[TTS] Tentando modelo: {os.path.basename(model_path)}", flush=True)
                voice = load_piper_voice(model_path, config_path)

                syn_config = get_synthesis_config()
                if syn_config is None:
                    raise RuntimeError("SynthesisConfig indisponivel")
                
                # extrai nome do modelo para log (re-assign to ensure correct value)
                model_name = os.path.splitext(os.path.basename(model_path))[0]
                configured_speed = apply_piper_tts_speed(syn_config, model_name)
                print(f"[TTS] Velocidade configurada (modelo={model_name}, tts_speed={configured_speed})", flush=True)
                
                # Síntese em memória via BytesIO
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(voice.config.sample_rate)
                    
                    print(f"[TTS] Iniciando síntese com voice.synthesize()...", flush=True)
                    chunk_count = 0
                    for chunk in voice.synthesize(text, syn_config):
                        chunk_count += 1
                        wav_file.writeframes(chunk.audio_int16_bytes)
                    
                    print(f"[TTS] Síntese completa: {chunk_count} chunks escritos", flush=True)

                wav_bytes = wav_buffer.getvalue()
                wav_size = len(wav_bytes)
                print(f"[TTS] Áudio WAV em memória: {wav_size} bytes", flush=True)

                # Valida bytes em memória
                buf = io.BytesIO(wav_bytes)
                try:
                    with wave.open(buf, "rb") as wav_check:
                        channels = wav_check.getnchannels()
                        sample_width = wav_check.getsampwidth()
                        frame_rate = wav_check.getframerate()
                        frame_count = wav_check.getnframes()
                    
                    if channels <= 0 or sample_width <= 0 or frame_rate <= 0 or frame_count <= 0:
                        raise RuntimeError("wav invalido")
                except Exception as exc:
                    raise RuntimeError(f"wav invalido: {exc}")

                print(f"[TTS] Piper selecionado: {os.path.basename(model_path)}", flush=True)
                end_time = time.time()
                print(f"[TTS] Síntese concluída (engine=piper) tempo={(end_time - start_time):.3f}s cache_id={cache_id[:8]}...", flush=True)
                
                # Armazena em cache
                if add_to_tts_cache(cache_id, wav_bytes, "piper"):
                    start_tts_cache_monitor()
                # mark last-used voice
                TTS_LAST_VOICE["piper"] = os.path.basename(model_path)
                return cache_id, "piper"
            except Exception as exc:
                print(f"[TTS] Exceção durante síntese: {type(exc).__name__}: {exc}", flush=True)
                print(f"[TTS] Falha ao gerar audio com Piper ({model_path}): {exc}", flush=True)

        print("[TTS] Nenhum par modelo/json do Piper conseguiu sintetizar audio.", flush=True)

    gtts_class = get_gtts_class()
    if gtts_class is None:
        print("[TTS] Piper indisponivel e gTTS nao esta instalado. Adicione piper-tts ou gTTS no ambiente.", flush=True)
        return "", ""

    lang = normalize_backend_tts_lang(tts_lang)
    
    try:
        mp3_buffer = io.BytesIO()
        gtts_class(text=text, lang=lang).write_to_fp(mp3_buffer)
        mp3_bytes = mp3_buffer.getvalue()
    except Exception as exc:
        try:
            print(f"[TTS] Falha ao gerar audio com fallback legacy ({lang}): {exc}", flush=True)
        except:
            pass
        return "", ""

    end_time = time.time()
    print(f"[TTS] Síntese concluída (engine=gtts) tempo={(end_time - start_time):.3f}s cache_id={cache_id[:8]}...", flush=True)
    
    # Armazena em cache
    if add_to_tts_cache(cache_id, mp3_bytes, "gtts"):
        start_tts_cache_monitor()
    return cache_id, "gtts"

def attach_backend_tts_audio(event_payload):
    if not isinstance(event_payload, dict):
        return
    # Compose TTS text, prefixing with the redeemer's username if available
    tts_text = normalize_tts_text(event_payload.get("tts_text", ""))
    user_name = normalize_tts_text(event_payload.get("user_name", ""))
    if not tts_text and not user_name:
        return

    if user_name:
        # Format: "usuario123 disse: mensagem"
        composed = f"{user_name} disse: {tts_text}" if tts_text else f"{user_name} disse:"
    else:
        composed = tts_text

    # Re-normalize to enforce length limits
    composed = normalize_tts_text(composed)

    tts_lang = event_payload.get("tts_lang") or get_first_env("TWITCH_TTS_LANG") or "pt-BR"
    event_payload["tts_text"] = composed
    event_payload["tts_lang"] = tts_lang

    cache_id, tts_engine = generate_tts_audio(composed, tts_lang)
    if cache_id:
        event_payload["tts_audio_url"] = f"/mp3/tts-cache/{cache_id}"
        event_payload["tts_engine"] = tts_engine

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
        default_file_path="json/steam_games.json",
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

def trigger_powerup_test(label="TESTE", tts_text=None, user_name=None):
    event_payload = {
        "reward": {
            "title": label,
        },
        "source": "powerup-test",
    }

    if user_name:
        event_payload["user_name"] = user_name

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
def get_github_publish_config(default_file_path="json/dados.json", file_path_env="GITHUB_FILE_PATH"):
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
def publish_file_to_github(content, default_file_path="json/dados.json", commit_message=None, file_path_env="GITHUB_FILE_PATH"):
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
    publish_file_to_github(content, default_file_path="json/dados.json", commit_message="chore: update dados.json", file_path_env="GITHUB_FILE_PATH")

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

@app.route("/debug/memory", methods=["GET"])
def debug_memory():
    """Return comprehensive backend memory metrics for all API components."""
    return get_all_memory_stats(), 200

# Endpoint de teste manual para validar o listener sem depender da Twitch.
@app.route("/twitch/powerup/test", methods=["GET", "POST"])
def twitch_powerup_test():
    label = request.args.get("label") or request.form.get("label") or "TESTE"
    text = request.args.get("text") or request.form.get("text") or ""
    # For manual testing, pretend the redeemer username is 'torneirinha'
    trigger_powerup_test(label, text, user_name="torneirinha")
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
    return send_file_no_cache(HTML_DIR, "obs_powerup.html")

@app.route("/obs/powerup.js", methods=["GET"])
def obs_powerup_script():
    return send_file_no_cache(JS_DIR, "obs_powerup.js")

@app.route("/obs/powerup.css", methods=["GET"])
def obs_powerup_styles():
    return send_file_no_cache(CSS_DIR, "obs_powerup.css")

# Webpage para OBS: roleta/torchlight
TORCHLIGHT_ROULETTE_ENABLED = False

def _torchlight_roleta_disabled_response():
    return {
        "ok": False,
        "error": "torchlight roleta desativada temporariamente",
    }, 410

@app.route("/torchlight/roleta/obs", methods=["GET"])
def obs_roleta_page():
    if not TORCHLIGHT_ROULETTE_ENABLED:
        return _torchlight_roleta_disabled_response()
    return send_file_no_cache(HTML_DIR, "torchlight_roleta_obs.html")

@app.route("/torchlight/roleta/obs.js", methods=["GET"])
def obs_roleta_script():
    if not TORCHLIGHT_ROULETTE_ENABLED:
        return _torchlight_roleta_disabled_response()
    return send_file_no_cache(JS_DIR, "torchlight_roleta_obs.js")

@app.route("/torchlight/roleta/obs.css", methods=["GET"])
def obs_roleta_styles():
    if not TORCHLIGHT_ROULETTE_ENABLED:
        return _torchlight_roleta_disabled_response()
    return send_file_no_cache(CSS_DIR, "torchlight_roleta_obs.css")
# Arquivo de audio para a webpage do OBS.
@app.route("/obs/nossa.mp3", methods=["GET"])
def obs_powerup_audio():
    # Compatibilidade: se nao houver mp3, usa o ogg padrao.
    if os.path.exists(os.path.join(MP3_DIR, "nossa.mp3")):
        return send_file_no_cache(MP3_DIR, "nossa.mp3")
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

@app.route("/mp3/tts-cache/<cache_id>", methods=["GET"])
def serve_tts_audio(cache_id):
    """Serve TTS audio from in-memory cache"""
    # Pop the entry so it's removed after being served (one-time play)
    with TTS_AUDIO_CACHE_LOCK:
        entry = TTS_AUDIO_CACHE.pop(cache_id, None)

    if not entry:
        print(f"[TTS-SERVE] Audio não encontrado ou expirado: {cache_id[:8]}...", flush=True)
        return Response("Audio expired or not found", status=404)

    audio_bytes, engine, timestamp = entry
    age = time.time() - timestamp
    if age > TTS_AUDIO_CACHE_TTL_SECONDS:
        print(f"[TTS-SERVE] Audio expirado antes de servir: {cache_id[:8]}... (age={age:.1f}s)", flush=True)
        return Response("Audio expired or not found", status=404)

    # Detecta tipo de arquivo baseado no engine
    mimetype = "audio/mpeg" if engine == "gtts" else "audio/wav"
    extension = ".mp3" if engine == "gtts" else ".wav"

    print(f"[TTS-SERVE] Servindo (one-time): {cache_id[:8]}... ({engine}, {len(audio_bytes)} bytes)", flush=True)
    return Response(
        audio_bytes,
        mimetype=mimetype,
        headers={
            "Content-Disposition": f'inline; filename="audio{extension}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.route("/mp3/<path:filename>", methods=["GET"])
def mp3_assets(filename):
    return send_file_no_cache(MP3_DIR, filename)

if __name__ == "__main__":
    log_env_status()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
