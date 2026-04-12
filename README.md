# BadMystake Stream API

API em Flask para controlar um contador de mortes para livestream/OBS (em tempo real utilizando comandos de chat Ex: Nightbot !morreu).

## Ambiente alvo

Esta aplicacao foi pensada para rodar no host do Render.

- Em producao, o Render define automaticamente a porta via variavel `PORT`.
- O endpoint publico esperado e o do proprio servico Render.

## O que o programa faz

1. Mantem um contador de mortes em `dados.json`.
2. Incrementa o contador via endpoint HTTP.
3. Retorna o valor para uso em overlay no OBS.
4. Expoe rotas de health check para manter o servico online no Render.

## Feature em desenvolvimento: Twitch Power-ups & Rewards

Foi iniciada a integracao com resgates de pontos do canal da Twitch (EventSub), focada no reward `Goleiro`.

Objetivo atual:

1. Receber notificacao de resgate via webhook da Twitch.
2. Detectar quando o reward recebido for `Goleiro`.
3. Notificar uma webpage no OBS para tocar um audio (`nossa.ogg` ou arquivos em `/mp3/`).

Status:

- Em desenvolvimento.
- Fluxo basico ja implementado na API e na webpage do OBS.

### Variaveis de ambiente (Render)

- `TWITCH_CHANNEL_ID`
- `TWITCH_DEV_ID`
- `TWITCH_SECRET`
- `TWITCH_TOKEN`
- `PUBLIC_BASE_URL` (exemplo: `https://seu-servico.onrender.com`)

### Endpoints da feature Twitch

- `POST /twitch/eventsub`
	- Callback da Twitch EventSub

- `GET|POST /twitch/eventsub/subscribe`
	- Cria assinatura EventSub para `channel.channel_points_custom_reward_redemption.add`

- `GET /twitch/powerup/state`
	- Estado simples (seq/ultimo reward) para polling da webpage

- `GET /obs/powerup`
	- Webpage blank para Browser Source do OBS

- `GET /obs/nossa.mp3`
	- Audio tocado quando houver novo trigger do reward `Goleiro`

- `GET /mp3/<arquivo>.mp3`
	- Arquivos novos usados pelos rewards mapeados no overlay

### Como usar no OBS (estado atual)

1. Adicione uma Browser Source apontando para `https://seu-servico.onrender.com/obs/powerup`.
2. Garanta que os arquivos de audio existam nas pastas `ogg/` e `mp3/` conforme o mapeamento do JavaScript.
3. Dispare a criacao da assinatura em `/twitch/eventsub/subscribe`.
4. Ao ocorrer um novo resgate `Goleiro`, a pagina deve tocar o audio.

## Arquivos principais

- `app.py`: API principal.
- `dados.json`: arquivo com o valor atual do contador.
- `obs_browser_refresh.lua`: script para ser adicionado dentro do proprio OBS (Tools > Scripts) e forcar o refresh da Browser Source.
- `obs_powerup.html`: webpage para Browser Source que escuta trigger de power-up e toca audio.

## OBS sem plugin WebSocket

O arquivo `obs_browser_refresh.lua` existe para atualizar o Browser Source diretamente dentro do OBS, evitando dependencia do plugin/WebSocket para esse refresh.

## Como rodar

1. Instale dependencias:

```bash
pip install -r requirements.txt
```

2. Execute a API:

```bash
python app.py
```

## Endpoints

### Leitura

- `GET /death/get`
- `GET /death/read`
	- Retorno: apenas o numero de mortes (exemplo: `16`)

- `GET /death/read/obs`
	- Retorno: texto para overlay (exemplo: `16 mortes`)

- `GET /death/current-game`
- `GET /stream/current-game`
	- Retorno: JSON com o jogo atual da stream, a chave normalizada e o contador de mortes do jogo atual

### Escrita

- `GET|POST /death/increment`
	- Soma 1 no contador

- `GET /death/clear`
	- Reseta o contador para `0`

- `GET|POST /death/save`
	- Salva chave/valor no JSON

### Operacional

- `GET /`
- `GET /health`
- `GET /healthz`

Todas retornam status `200` quando o servico esta saudavel.
