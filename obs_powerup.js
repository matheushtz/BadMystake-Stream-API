var nossa = new Audio("/ogg/nossa.ogg");
var morreu = new Audio("/ogg/morreu.ogg");
var plol = new Audio("/ogg/plol.ogg");
var activeAudio = nossa;

nossa.volume = 1;
nossa.preload = "auto";

morreu.volume = 1;
morreu.preload = "auto";

plol.volume = 1;
plol.preload = "auto";

var listaPedidos = [];
var stateUrl = "/twitch/powerup/state";
var pollIntervalMs = 1200;
var lastSeq = null;

var REWARD_ID_PLOL = "60863459-5e25-42d2-a49d-7a79fd13bf78";
var REWARD_ID_GOLEIRO = "69a918e0-6ed7-461a-b76e-e8f4324cb66a";
var REWARD_AUDIO_MAP = {
    "death-increment": "/ogg/morreu.ogg",
    "death-decrement": "/ogg/morreu.ogg",
    "manual-test": "/ogg/nossa.ogg",
    "69a918e0-6ed7-461a-b76e-e8f4324cb66a": "/ogg/nossa.ogg",
    "60863459-5e25-42d2-a49d-7a79fd13bf78": "/ogg/plol.ogg"
};

function normalizeId(value) {
    return String(value || "").trim().toLowerCase();
}

function registerRewardAudio(rewardId, audioPath) {
    var normalizedRewardId = normalizeId(rewardId);

    if (!normalizedRewardId || !audioPath) {
        return;
    }

    REWARD_AUDIO_MAP[normalizedRewardId] = audioPath;
}

registerRewardAudio(REWARD_ID_PLOL, "/ogg/plol.ogg");
registerRewardAudio(REWARD_ID_GOLEIRO, "/ogg/nossa.ogg");

function buildSoundPath(pedido) {
    if (!pedido || typeof pedido !== "object") {
        console.log("[DEBUG] buildSoundPath - pedido inválido, ignorando");
        return null;
    }

    if (!pedido.reward || typeof pedido.reward !== "object" || !pedido.reward.id) {
        console.log("[DEBUG] buildSoundPath - reward.id ausente, ignorando");
        return null;
    }

    var rewardId = normalizeId(pedido.reward.id);

    console.log("[DEBUG] buildSoundPath - rewardId:", rewardId);

    var audioPath = REWARD_AUDIO_MAP[rewardId];

    if (audioPath) {
        console.log("[DEBUG] -> retorna áudio configurado:", audioPath);
        return audioPath;
    }

    console.log("[DEBUG] buildSoundPath - reward desconhecida, ignorando");
    return null;
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
        console.log("[DEBUG] tryPlayAudio - tocando:", activeAudio === morreu ? "morreu" : (activeAudio === plol ? "plol" : "nossa"));
        activeAudio.currentTime = 0;
        await activeAudio.play();
        return true;
    } catch (err) {
        console.log("[OBS] Falha ao tocar audio, tentando recarregar:", err);
        try {
            activeAudio.load();
            await sleepTime(100);
            activeAudio.currentTime = 0;
            await activeAudio.play();
            return true;
        } catch (err2) {
            console.log("[OBS] Reproducao bloqueada:", err2);
            return false;
        }
    }
}

function setAudioSource(path) {
    var isMorreu = path.indexOf("/ogg/morreu.ogg") !== -1;
    var isPlol = path.indexOf("/ogg/plol.ogg") !== -1;
    activeAudio = isMorreu ? morreu : (isPlol ? plol : nossa);

    console.log("[DEBUG] setAudioSource - path:", path, "-> usando:", isMorreu ? "morreu" : (isPlol ? "plol" : "nossa"));

    if (activeAudio.src.indexOf(path) !== -1) {
        console.log("[DEBUG] Audio já carregado, retornando");
        return;
    }
    activeAudio.src = path;
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
