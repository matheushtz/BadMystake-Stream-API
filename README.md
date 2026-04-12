# BadMystake Stream API

API em Flask para integrar interacao do chat com a stream, com suporte a comandos, eventos da Twitch, feedback sonoro no OBS e consultas de progresso da Steam.

## Ambiente alvo

Esta aplicacao foi pensada para rodar no host do Render.

- Em producao, o Render define automaticamente a porta via variavel `PORT`.
- O endpoint publico esperado e o do proprio servico Render.

## O que o programa faz

1. Mantem dados por jogo em `dados.json`, usando chave com o nome do jogo.
2. Recebe comandos do chat via endpoints expostos para integrarem com Nightbot ou automacoes similares.
3. Recebe eventos da Twitch via listener/webhook e dispara feedback sonoro na stream.
4. Retorna informacoes de progresso de conquistas da Steam para o jogo atual da live.
5. Expoe rotas de health check para manter o servico online no Render.

## Twitch Power-ups & Rewards

Integracao finalizada com resgate de power-up na Twitch e feedback sonoro na stream.

Fluxo geral:

1. A Twitch envia o evento para o webhook da API.
2. O listener processa o payload e atualiza o estado em memoria.
3. A webpage do OBS consulta esse estado via JavaScript.
4. O JavaScript reage ao novo evento e toca o audio configurado.
5. O mesmo padrao permite acionar a API por comandos do chat, por exemplo via Nightbot, usando os endpoints HTTP expostos.

Esse fluxo permite unir comandos do chat, eventos da Twitch e resposta visual/sonora na stream sem depender de extensoes pesadas no OBS.

### Variaveis de ambiente (Render)

- `TWITCH_CHANNEL_ID`
- `TWITCH_DEV_ID`
- `TWITCH_SECRET`
- `TWITCH_TOKEN`
- `STEAM_WEB_API_KEY` (ou `STEAM_API_KEY`)
- `STEAM_TARGET_STEAMID64`
- `PUBLIC_BASE_URL` (exemplo: `https://seu-servico.onrender.com`)
- `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPO`
- `GITHUB_FILE_PATH` para publicar `dados.json`
- `GITHUB_STEAM_GAMES_FILE_PATH` para publicar `steam_games.json`

### Como funciona a integracao com o chat

O fluxo foi desenhado para ser simples de operar na live:

1. O chat dispara um comando do Nightbot.
2. O Nightbot chama um endpoint da API.
3. A API atualiza o estado interno ou os dados do jogo.
4. O listener JavaScript da pagina do OBS observa o estado ou consome o endpoint.
5. A stream recebe o feedback sonoro ou a atualizacao visual.

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
	- Audio tocado quando houver novo trigger do power-up na stream

- `GET /mp3/<arquivo>.mp3`
	- Arquivos novos usados pelos rewards mapeados no overlay

### Endpoint Steam

- `GET /steam/achievements/`
	- Retorna as conquistas desbloqueadas e o total de conquistas do jogo da stream usando o SteamID64 configurado no Render.
	- Se `?game=` nao for enviado, usa o jogo atual da live vindo da Twitch.
	- Resposta em texto puro no formato: `Outer Wilds: 2 de 31 (6,45% concluído)`
	- Atualmente o mapping inclui: `Outer Wilds -> 753640`
	- Quando um jogo novo precisa ser resolvido, o mapa local `steam_games.json` e atualizado e pode ser publicado automaticamente no GitHub se as variaveis de publish estiverem configuradas.

	- Requer as variaveis de ambiente `STEAM_WEB_API_KEY` (ou `STEAM_API_KEY`) e `STEAM_TARGET_STEAMID64`.

### Estrutura de dados

O arquivo `dados.json` guarda os contadores por jogo. Exemplo:

```json
{
  "outer-wilds": {
    "mortes": 20
  }
}
```

Isso permite manter o historico por jogo e usar a mesma base para futuras expansoes.

### Como usar no OBS (estado atual)

1. Adicione uma Browser Source apontando para `https://seu-servico.onrender.com/obs/powerup`.
2. Garanta que os arquivos de audio existam nas pastas `ogg/` e `mp3/` conforme o mapeamento do JavaScript.
3. Dispare a criacao da assinatura em `/twitch/eventsub/subscribe`.
4. Ao ocorrer um novo resgate na Twitch, a pagina deve tocar o audio.

## Arquivos principais

- `app.py`: API principal.
- `dados.json`: arquivo com os dados por jogo.
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
	- Retorno: apenas o `game_name` atual da stream em texto puro (ex: `Outer Wilds`)

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
