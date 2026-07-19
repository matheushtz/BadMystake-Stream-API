"""Centraliza o estado ACTIVE/IDLE da aplicacao.

ACTIVE somente quando: live da Twitch online E heartbeat recente do
Browser Source. Qualquer processamento periodico (workers, polling,
timers) deve consultar `activity_manager.is_active()` antes de rodar,
ou se registrar via `on_active`/`on_idle` para iniciar/parar sozinho.
"""

import threading
import time

HEARTBEAT_TIMEOUT_SECONDS = 60


class ActivityManager:
    def __init__(self, heartbeat_timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS):
        self._lock = threading.Lock()
        self._twitch_live = False
        self._last_heartbeat_at = None
        self._state = "IDLE"
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._watchdog_timer = None
        self._on_active_callbacks = []
        self._on_idle_callbacks = []

    def on_active(self, callback):
        self._on_active_callbacks.append(callback)

    def on_idle(self, callback):
        self._on_idle_callbacks.append(callback)

    def set_twitch_live(self, is_live):
        with self._lock:
            self._twitch_live = bool(is_live)
        self._recompute()

    def record_heartbeat(self):
        with self._lock:
            self._last_heartbeat_at = time.time()
        self._reschedule_watchdog()
        self._recompute()

    def is_active(self):
        self._recompute()
        with self._lock:
            return self._state == "ACTIVE"

    def get_status(self):
        self._recompute()
        with self._lock:
            return {
                "state": self._state,
                "twitch_live": self._twitch_live,
                "browser_connected": self._heartbeat_recent_locked(),
                "heartbeat_recent": self._heartbeat_recent_locked(),
                "last_heartbeat_at": self._last_heartbeat_at,
            }

    def _heartbeat_recent_locked(self):
        if self._last_heartbeat_at is None:
            return False
        return (time.time() - self._last_heartbeat_at) < self._heartbeat_timeout_seconds

    def _reschedule_watchdog(self):
        with self._lock:
            if self._watchdog_timer is not None:
                self._watchdog_timer.cancel()
            timer = threading.Timer(self._heartbeat_timeout_seconds, self._recompute)
            timer.daemon = True
            self._watchdog_timer = timer
            timer.start()

    def _recompute(self):
        with self._lock:
            should_be_active = self._twitch_live and self._heartbeat_recent_locked()
            transition = None
            if should_be_active and self._state != "ACTIVE":
                self._state = "ACTIVE"
                transition = "ACTIVE"
            elif not should_be_active and self._state != "IDLE":
                self._state = "IDLE"
                transition = "IDLE"

        if transition == "ACTIVE":
            print("[ACTIVITY] IDLE -> ACTIVE", flush=True)
            self._fire(self._on_active_callbacks)
        elif transition == "IDLE":
            print("[ACTIVITY] ACTIVE -> IDLE", flush=True)
            self._fire(self._on_idle_callbacks)

    def _fire(self, callbacks):
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                print(f"[ACTIVITY] Callback falhou: {type(exc).__name__}: {exc}", flush=True)


activity_manager = ActivityManager()
