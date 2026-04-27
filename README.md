# BadMystake Stream API

API em Flask para integrar interacao do chat com a stream, com suporte a comandos, eventos da Twitch, feedback sonoro no OBS e consultas de progresso da Steam.

## Ambiente alvo

Esta aplicacao foi pensada para rodar no host do Render.

- Em producao, o Render define automaticamente a porta via variavel `PORT`.
- O endpoint publico esperado e o do proprio servico Render.

## O que o programa faz

1. Mantem dados por jogo em `dados.json`, usando chave normalizada do nome do jogo (ex: `torchlight-infinite`).
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

### TTS rewards

Para fazer um reward da Twitch falar no overlay do OBS, configure:

- `TWITCH_TTS_REWARD_IDS`
- `TWITCH_TTS_REWARD_ID` (single reward ID fallback)
- `TWITCH_TTS_LANG` (opcional, padrao `pt-BR`)

Quando um reward configurado e resgatado:

1. O backend gera um arquivo de audio MP3 usando `gTTS`.
2. O payload enviado para o overlay inclui `tts_audio_url`.
3. O JavaScript do OBS toca esse arquivo (em vez de depender apenas do `speechSynthesis` local).

O texto falado vem de `user_input`. Se vier vazio, o backend monta uma frase curta com `user_name` + reward title.

Teste rapido sem Twitch:

```bash
/twitch/powerup/test?text=Mensagem+de+teste
```

Se `text` for omitido, o teste segue o caminho legado de audio (`nossa.ogg`).

Observacoes:

- Os arquivos TTS gerados ficam em `/mp3/tts-generated/`.
- O backend remove arquivos antigos automaticamente para evitar crescimento infinito.
- Se a geracao de audio falhar, o overlay ainda tenta o fallback via `speechSynthesis`.
- O `gTTS` depende de acesso a internet para gerar os arquivos.

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
	- Arquivos MP3 estaticos e TTS gerado (`/mp3/tts-generated/...`)

- `GET|POST /twitch/powerup/test`
	- Endpoint de teste manual para disparar power-up
	- Com `?text=...` gera TTS em arquivo e envia para o overlay

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
2. Habilite `Control audio via OBS` na Browser Source para garantir saida no mixer.
3. Dispare a criacao da assinatura em `/twitch/eventsub/subscribe`.
4. Teste manual com `/twitch/powerup/test?text=Mensagem+de+teste`.
5. Ao ocorrer um novo resgate na Twitch, a pagina deve tocar o MP3 gerado para TTS (ou audio mapeado quando nao for TTS).

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
	- Retorno JSON com `game_name`, `game_key` e `mortes` do jogo atual

- `GET /death/all`
	- Retorno JSON com total geral e todos os jogos no formato salvo em `dados.json`

- `GET /stream/current-game`
	- Retorno: apenas o `game_name` atual da stream em texto puro (ex: `Outer Wilds`)

### Escrita

- `GET|POST /death/increment`
	- Soma 1 no contador do jogo atual da stream

- `GET|POST /death/decrement`
	- Subtrai 1 no contador do jogo atual da stream

- `GET /death/clear`
	- Limpa os dados e volta para o estado padrao

- `GET|POST /death/save`
	- Salva o contador por jogo no mesmo formato dos demais endpoints de mortes
	- Parametros aceitos (prioridade):
		- `jogo` (ou `game`)
		- `mortes`
	- Compatibilidade legada mantida:
		- `key` e `value`
	- Exemplo de body JSON recomendado:

```json
{
  "jogo": "torchlight infinite",
  "mortes": 860
}
```

	- Exemplo de persistencia em `dados.json`:

```json
{
  "torchlight-infinite": {
    "mortes": 860
  }
}
```

	- Retorno: numero salvo em texto puro (ex: `860`)

### Operacional

- `GET /`
- `GET /healthz`

Todas retornam status `200` quando o servico esta saudavel.
