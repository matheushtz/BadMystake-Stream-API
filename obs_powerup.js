var tempoAniPadrao = 2000;
var audio = new Audio("/ogg/nossa.ogg");
audio.volume = 0.6;
audio.preload = "auto";

var listaPedidos = [];
var stateUrl = "/twitch/powerup/state";
var pollIntervalMs = 1200;
var lastSeq = null;
var cdPadrao = 10;
var cdUser = {};

function parseImageUrl(reward) {
    if (reward && reward.image && reward.image.url_4x) {
        return reward.image.url_4x;
    }

    if (reward && reward.default_image && reward.default_image.url_4x) {
        return reward.default_image.url_4x;
    }

    return "https://static-cdn.jtvnw.net/community-goal-images/default-2.png";
}

function hexIsLightColor(hex) {
    if (!hex || typeof hex !== "string" || hex.charAt(0) !== "#" || hex.length < 7) {
        return false;
    }

    var gray = parseInt(hex.substring(1, 3), 16) * 0.2126 + parseInt(hex.substring(3, 5), 16) * 0.7152 + parseInt(hex.substring(5, 7), 16) * 0.0722;
    document.getElementById("box").style.backgroundColor = hex;
    return gray > 127;
}

function loadImage(elen, img) {
    return new Promise(function (resolve) {
        elen.onload = function () {
            resolve();
        };
        elen.src = img;
    });
}

function sleepTime(timeMs) {
    return new Promise(function (resolve) {
        setTimeout(function () {
            resolve();
        }, timeMs);
    });
}

function playAnimation(direc) {
    var anchor = document.getElementById("anchor");
    var box = document.getElementById("box");

    anchor.removeAttribute("style");
    anchor.className = "";
    box.className = "";

    void box.offsetWidth;

    if (direc === 0) {
        anchor.classList.add("anchorAniIn");
        box.classList.add("boxAniIn");
    } else {
        anchor.classList.add("anchorAniOut");
        box.classList.add("boxAniOut");
    }
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
            var reward = pedido.reward || {};
            var userName = pedido.user_name || pedido.user_login || "Power-up";
            var title = reward.title || "Goleiro";
            var userInput = String(pedido.user_input || "").trim();
            var imageUrl = parseImageUrl(reward);
            var backgroundColor = reward.background_color || "#9146FF";

            document.getElementById("nome").textContent = userName;
            document.getElementById("acao").textContent = title;

            if (userInput) {
                document.getElementById("acao").textContent = title + " - " + userInput;
            }

            await loadImage(document.getElementById("img"), imageUrl);

            if (hexIsLightColor(backgroundColor)) {
                document.getElementById("nome").style.color = "#112";
                document.getElementById("acao").style.color = "#112";
            } else {
                document.getElementById("nome").style.color = "#fff";
                document.getElementById("acao").style.color = "#fff";
            }

            var sleepT = tempoAniPadrao + 1200;
            if (audio.duration && !isNaN(audio.duration) && audio.duration > 0) {
                var audioMs = audio.duration * 1000;
                if (audioMs > sleepT) {
                    sleepT = audioMs - 300;
                }
            }

            document.getElementById("anchor").style.display = "block";
            playAnimation(0);
            await tryPlayAudio();
            await sleepTime(sleepT);
            playAnimation(1);
            await sleepTime(900);

            document.getElementById("anchor").style.display = "none";
        } else {
            await sleepTime(700);
        }
    }
}

function iniciar() {
    var animation = document.getElementById("animation");
    if (animation) {
        animation.style.display = "block";
    }

    setInterval(pollState, pollIntervalMs);
    pollState();
    lista();
}

window.addEventListener("load", function () {
    iniciar();
});
