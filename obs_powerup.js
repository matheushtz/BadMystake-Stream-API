var audio = new Audio("/ogg/nossa.ogg");
audio.volume = 0.6;
audio.preload = "auto";

var stateUrl = "/twitch/powerup/state";
var pollIntervalMs = 1200;
var lastSeq = null;

function sleepTime(timeMs) {
    return new Promise(function (resolve) {
        setTimeout(function () {
            resolve();
        }, timeMs);
    });
}

async function tryPlayAudio() {
    try {
        audio.currentTime = 0;
        await audio.play();
        return true;
    } catch (err) {
        console.log("[OBS] Falha ao tocar audio, tentando recarregar:", err);
        try {
            audio.load();
            await sleepTime(100);
            audio.currentTime = 0;
            await audio.play();
            return true;
        } catch (err2) {
            console.log("[OBS] Reproducao bloqueada:", err2);
            return false;
        }
    }
}

function showDebugMessage(text) {
    var debugMessage = document.getElementById("debugMessage");
    var debugText = document.getElementById("debugText");

    debugText.textContent = text;
    debugMessage.style.display = "block";
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
            showDebugMessage("Listener recebeu um evento");
            await tryPlayAudio();
        }

        lastSeq = seq;
    }
    catch (error) {
        console.log("[OBS] Erro no polling:", error);
    }
}

function iniciar() {
    setInterval(pollState, pollIntervalMs);
    pollState();
}

window.addEventListener("load", function () {
    document.getElementById("debugMessage").style.display = "none";
    iniciar();
});
