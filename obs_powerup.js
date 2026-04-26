var audioCache = {};
var DEFAULT_AUDIO_PATH = "/ogg/nossa.ogg";
var DEFAULT_TTS_LANG = "pt-BR";
var TTS_VOICES_TIMEOUT_MS = 1800;
var activeAudio = null;
var activeAudioPath = null;

var listaPedidos = [];
var stateUrl = "/twitch/powerup/state";
var pollIntervalMs = 1200;
var lastSeq = null;

var REWARD_AUDIO_MAP = {
    "death-increment": "/ogg/morreu.ogg",
    "death-decrement": "/ogg/morreu.ogg",
    "manual-test": "/ogg/nossa.ogg",
    "goleiro": "/ogg/nossa.ogg",
    "plol": "/ogg/plol.ogg",
    "69a918e0-6ed7-461a-b76e-e8f4324cb66a": "/ogg/nossa.ogg",
    "60863459-5e25-42d2-a49d-7a79fd13bf78": "/ogg/plol.ogg",
    "77cbd32c-ba20-4896-822b-cfedfdb729cb": "/mp3/gamedle.mp3",
    "831c90b0-038d-4046-82dc-3be905701c66": "/mp3/3h-runescape.mp3",
    "a7978bbc-1a5e-4c11-a194-d60a70a6e63a": "/mp3/3h-rocket-league.mp3",
    "b001e303-c1fd-4d7a-a1db-5235eec9ede9": "/mp3/aram-ate-perder.mp3",
    "c820aa0b-e4dd-4e48-9558-36ec0a51d512": "/mp3/3h-algum-game.mp3"
};

// Mapeamento de volume para cada arquivo de áudio (0.0 a 1.0)
var AUDIO_VOLUME_MAP = {
    // OGG files
    "/ogg/joker.ogg": 1.0,
    "/ogg/morreu.ogg": 1.0,
    "/ogg/nossa.ogg": 1.0,
    "/ogg/plol.ogg": 0.5,
    // MP3 files
    "/mp3/3h-algum-game.mp3": 1.0,
    "/mp3/3h-rocket-league.mp3": 1.0,
    "/mp3/3h-runescape.mp3": 1.0,
    "/mp3/aram-ate-perder.mp3": 1.0,
    "/mp3/gamedle.mp3": 1.0,
    "/mp3/live-sem-camisa.mp3": 1.0
};

function normalizeId(value) {
    return String(value || "").trim().toLowerCase();
}

function normalizeSpeechText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
}

function getAudioDirectory(path) {
    var normalizedPath = normalizeId(path).split("?")[0];

    if (normalizedPath.indexOf("/mp3/") === 0 || normalizedPath.slice(-4) === ".mp3") {
        return "/mp3/";
    }

    if (normalizedPath.indexOf("/ogg/") === 0 || normalizedPath.slice(-4) === ".ogg") {
        return "/ogg/";
    }

    return "/ogg/";
}

function getAudioByPath(path) {
    var normalizedPath = normalizeId(path).split("?")[0] || DEFAULT_AUDIO_PATH;

    if (!audioCache[normalizedPath]) {
        var audio = new Audio(normalizedPath);
        audio.volume = AUDIO_VOLUME_MAP[normalizedPath] !== undefined ? AUDIO_VOLUME_MAP[normalizedPath] : 1;
        audio.preload = "auto";
        audioCache[normalizedPath] = audio;
    }

    return audioCache[normalizedPath];
}

function getRewardLookupKeys(pedido) {
    var keys = [];

    if (!pedido || typeof pedido !== "object") {
        return keys;
    }

    if (pedido.reward && typeof pedido.reward === "object") {
        if (pedido.reward.id) {
            keys.push(normalizeId(pedido.reward.id));
        }
        if (pedido.reward.title) {
            keys.push(normalizeId(pedido.reward.title));
        }
    }

    if (pedido.source) {
        keys.push(normalizeId(pedido.source));
    }

    return keys;
}

function buildSoundPath(pedido) {
    if (!pedido || typeof pedido !== "object") {
        console.log("[DEBUG] buildSoundPath - pedido inválido, ignorando");
        return null;
    }

    var lookupKeys = getRewardLookupKeys(pedido);
    console.log("[DEBUG] buildSoundPath - lookupKeys:", lookupKeys);

    for (var i = 0; i < lookupKeys.length; i++) {
        var audioPath = REWARD_AUDIO_MAP[lookupKeys[i]];
        if (audioPath) {
            console.log("[DEBUG] -> retorna áudio configurado:", audioPath, "(key:", lookupKeys[i] + ")");
            return audioPath;
        }
    }

    if (pedido.sound_file) {
        var fileName = String(pedido.sound_file).split("/").pop();
        if (fileName) {
            var fallbackPath = getAudioDirectory(fileName) + fileName;
            console.log("[DEBUG] -> fallback por sound_file:", fallbackPath);
            return fallbackPath;
        }
    }

    console.log("[DEBUG] buildSoundPath - reward desconhecida, ignorando");
    return null;
}

function buildTtsText(pedido) {
    if (!pedido || typeof pedido !== "object") {
        return "";
    }

    var text = normalizeSpeechText(pedido.tts_text);
    if (text) {
        return text;
    }

    return "";
}

function waitForTtsVoices(timeoutMs) {
    return new Promise(function (resolve) {
        if (!window.speechSynthesis || typeof window.speechSynthesis.getVoices !== "function") {
            resolve(false);
            return;
        }

        try {
            var voicesNow = window.speechSynthesis.getVoices();
            if (Array.isArray(voicesNow) && voicesNow.length > 0) {
                resolve(true);
                return;
            }

            var done = false;
            var finish = function (hasVoices) {
                if (done) {
                    return;
                }

                done = true;
                window.speechSynthesis.removeEventListener("voiceschanged", onVoicesChanged);
                resolve(Boolean(hasVoices));
            };

            var onVoicesChanged = function () {
                try {
                    var voices = window.speechSynthesis.getVoices();
                    finish(Array.isArray(voices) && voices.length > 0);
                } catch (err) {
                    finish(false);
                }
            };

            window.speechSynthesis.addEventListener("voiceschanged", onVoicesChanged);
            window.setTimeout(function () {
                onVoicesChanged();
            }, timeoutMs);
        } catch (error) {
            resolve(false);
        }
    });
}

function speakText(text, lang) {
    return new Promise(function (resolve) {
        if (!window.speechSynthesis || typeof window.SpeechSynthesisUtterance === "undefined") {
            console.log("[OBS][TTS] Speech API indisponível no Browser Source");
            resolve(false);
            return;
        }

        waitForTtsVoices(TTS_VOICES_TIMEOUT_MS).then(function (hasVoices) {
            if (!hasVoices) {
                console.log("[OBS][TTS] Nenhuma voz carregada no navegador do OBS");
            }

            var utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = lang || DEFAULT_TTS_LANG;
            utterance.rate = 1;
            utterance.pitch = 1;
            utterance.volume = 1;

            var done = false;
            var spoken = false;
            var finish = function () {
                if (done) {
                    return;
                }

                done = true;
                resolve(spoken);
            };

            var timeoutId = window.setTimeout(function () {
                console.log("[OBS][TTS] Timeout ao aguardar fim da fala");
                finish();
            }, Math.max(2500, text.length * 80));

            utterance.onstart = function () {
                spoken = true;
            };

            utterance.onend = function () {
                window.clearTimeout(timeoutId);
                finish();
            };

            utterance.onerror = function (event) {
                console.log("[OBS][TTS] Erro ao falar:", event && event.error ? event.error : event);
                window.clearTimeout(timeoutId);
                finish();
            };

            try {
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(utterance);
            } catch (error) {
                console.log("[OBS][TTS] Exceção ao chamar speak():", error);
                window.clearTimeout(timeoutId);
                finish();
            }
        });
    });
}

function sleepTime(timeMs) {
    return new Promise(function (resolve) {
        setTimeout(function () {
            resolve();
        }, timeMs);
    });
}

async function tryPlayAudio() {
    try {
        var audioLabel = activeAudioPath ? activeAudioPath.split("/").pop() : "audio";
        console.log("[DEBUG] tryPlayAudio - tocando:", audioLabel);
        activeAudio.currentTime = 0;
        await activeAudio.play();
    } catch (err) {
        console.log("[OBS] Falha ao tocar audio, tentando recarregar:", err);
        try {
            activeAudio.load();
            await sleepTime(100);
            activeAudio.currentTime = 0;
            await activeAudio.play();
        } catch (err2) {
            console.log("[OBS] Reproducao bloqueada:", err2);
        }
    }
}

function setAudioSource(path) {
    var normalizedPath = normalizeId(path).split("?")[0];

    if (activeAudioPath === normalizedPath && activeAudio) {
        console.log("[DEBUG] Audio já carregado, retornando");
        return;
    }

    activeAudio = getAudioByPath(normalizedPath);
    activeAudioPath = normalizedPath;
    var audioName = activeAudioPath.split("/").pop() || "audio";

    console.log("[DEBUG] setAudioSource - path:", path, "-> usando:", audioName);
    activeAudio.src = activeAudioPath;
    activeAudio.load();
    console.log("[DEBUG] Audio carregado");
}

async function pollState() {
    try {
        var response = await fetch(stateUrl, { cache: "no-store" });
        if (!response.ok) {
            return;
        }

        var data = await response.json();
        var seq = Number(data.seq || 0);
        var eventData = data.last_event || null;

        if (lastSeq === null) {
            lastSeq = seq;
            return;
        }

        if (seq > lastSeq) {
            for (var i = 0; i < seq - lastSeq; i++) {
                if (eventData) {
                    listaPedidos.push(eventData);
                }
            }
        }

        lastSeq = seq;
    } catch (error) {
        console.log("[OBS] Erro no polling:", error);
    }
}

async function lista() {
    while (true) {
        if (listaPedidos.length > 0) {
            var pedido = listaPedidos.shift();
            var ttsText = buildTtsText(pedido);

            if (ttsText) {
                var ttsPlayed = await speakText(ttsText, pedido.tts_lang || DEFAULT_TTS_LANG);

                if (!ttsPlayed) {
                    console.log("[OBS][TTS] Fallback para áudio por falha/bloqueio do TTS");
                    setAudioSource(DEFAULT_AUDIO_PATH);
                    await tryPlayAudio();
                }

                continue;
            }

            var soundPath = buildSoundPath(pedido);

            if (!soundPath) {
                continue;
            }

            setAudioSource(soundPath);
            await tryPlayAudio();

            if (activeAudio.duration && !isNaN(activeAudio.duration) && activeAudio.duration > 0) {
                var audioMs = activeAudio.duration * 1000;
                await sleepTime(audioMs);
            }
        } else {
            await sleepTime(700);
        }
    }
}

function iniciar() {
    setInterval(pollState, pollIntervalMs);
    pollState();
    lista();
}

window.addEventListener("load", function () {
    iniciar();
});
