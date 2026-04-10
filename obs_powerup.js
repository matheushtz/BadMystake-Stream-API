var nossa = new Audio("/ogg/nossa.ogg");
var morreu = new Audio("/ogg/morreu.ogg");
var activeAudio = nossa;

nossa.volume = 0.6;
nossa.preload = "auto";

morreu.volume = 0.8;
morreu.preload = "auto";

var listaPedidos = [];
var stateUrl = "/twitch/powerup/state";
var pollIntervalMs = 1200;
var lastSeq = null;

var REWARD_ID_GOLEIRO = "69a918e0-6ed7-461a-b76e-e8f4324cb66a";

function normalizeId(value) {
    return String(value || "").trim().toLowerCase();
}

function buildSoundPath(pedido) {
    var source = normalizeId(pedido && pedido.source);
    var rewardId = normalizeId(pedido && pedido.reward && pedido.reward.id);

    console.log("[DEBUG] buildSoundPath - source:", source, "rewardId:", rewardId);

    if (source === "death-increment" || rewardId === "death-increment") {
        console.log("[DEBUG] -> retorna morreu.ogg");
        return "/ogg/morreu.ogg";
    }

    if (rewardId === normalizeId(REWARD_ID_GOLEIRO)) {
        console.log("[DEBUG] -> retorna nossa.ogg (goleiro)");
        return "/ogg/nossa.ogg";
    }

    console.log("[DEBUG] -> retorna nossa.ogg (fallback)");
    return "/ogg/nossa.ogg";
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
        console.log("[DEBUG] tryPlayAudio - tocando:", activeAudio === nossa ? "nossa" : "morreu");
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
    activeAudio = isMorreu ? morreu : nossa;

    console.log("[DEBUG] setAudioSource - path:", path, "-> usando:", isMorreu ? "morreu" : "nossa");

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

            setAudioSource(buildSoundPath(pedido));
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
