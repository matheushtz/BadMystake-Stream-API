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

**Twitch**
- `TWITCH_CHANNEL_ID`
- `TWITCH_DEV_ID`
- `TWITCH_SECRET`
- `TWITCH_TOKEN`
- `TWITCH_TTS_REWARD_IDS` (IDs dos rewards que acionam TTS)
- `TWITCH_TTS_REWARD_ID` (fallback para um ID unico de reward TTS)
- `TWITCH_TTS_LANG` (idioma TTS, padrao: `pt-BR`)

**Steam**
- `STEAM_WEB_API_KEY` (ou `STEAM_API_KEY`)
- `STEAM_TARGET_STEAMID64`

**PIPER TTS** (sintese de fala local)
- `PIPER_TTS_MODEL_PATH` (caminho para o arquivo `.onnx`, ex: `/tts-model/pt_BR-cadu-medium.onnx`)
- `PIPER_TTS_CONFIG_PATH` (caminho para o arquivo `.json` do modelo)

**GitHub** (publicacao de dados)
- `PUBLIC_BASE_URL` (exemplo: `https://seu-servico.onrender.com`)
- `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPO`
- `GITHUB_FILE_PATH` para publicar `dados.json`
- `GITHUB_STEAM_GAMES_FILE_PATH` para publicar `steam_games.json`

### TTS rewards

Para fazer um reward da Twitch falar no overlay do OBS, configure:

- `TWITCH_TTS_REWARD_IDS`
- `TWITCH_TTS_REWARD_ID` (single reward ID fallback)
- `TWITCH_TTS_LANG` (opcional, padrao `pt-BR`)
- `PIPER_TTS_MODEL_PATH` e `PIPER_TTS_CONFIG_PATH` para apontar para o modelo `pt_BR-cadu-medium`

Quando um reward configurado e resgatado:

1. O backend gera um arquivo de audio WAV usando Piper TTS com a voz `pt_BR-cadu-medium`.
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
- Piper trabalha com modelo local; se o modelo nao estiver disponivel, o backend pode cair no fallback legacy.

### Mecanismo de velocidade TTS com PIPER

A velocidade da fala sintetizada pode ser configurada dinamicamente atraves do arquivo `json/tts_config.json`, sem necessidade de reiniciar o servico.

#### Configuracao de velocidade

O arquivo `tts_config.json` segue este padrao:

**Configuracao global (aplica a todos os modelos):**
```json
{
  "tts_speed": 1.0
}
```

**Configuracao por modelo (sobrescreve global):**
```json
{
  "pt_BR-cadu-medium": {
    "tts_speed": 0.9
  },
  "pt_BR-jeff-medium": {
    "tts_speed": 1.1
  },
  "tts_speed": 1.0
}
```

#### Parametros de velocidade

- **Intervalo valido**: `0.5` a `2.0`
- **Padrao**: `1.0` (velocidade normal)
- **Minimo**: `0.5` (mais lento, 50% da velocidade original)
- **Maximo**: `2.0` (mais rapido, 200% da velocidade original)
- **Fora do intervalo**: valores invalidos sao automaticamente ajustados para o limite mais proximo

#### Como funciona

Internamente, o PIPER usa o parametro `length_scale` para ajustar a velocidade:

- Velocidade `< 1.0` → `length_scale` **maior** → fala **mais lenta**
- Velocidade `1.0` → `length_scale = 1.0` → fala **normal**
- Velocidade `> 1.0` → `length_scale` **menor** → fala **mais rapida**

A relacao matematica: `length_scale = 1.0 / velocity`

#### Exemplo de uso

Para fazer a voz `pt_BR-cadu-medium` falar 20% mais rapido:

```json
{
  "pt_BR-cadu-medium": {
    "tts_speed": 1.2
  }
}
```

O backend valida a configuracao a cada geracao de audio. Se houver erro na leitura do arquivo ou valor invalido, o sistema usa o padrao `1.0`.

#### Direitos reservados - PIPER TTS

> **PIPER** é um sintetizador de fala de texto local de codigo aberto sob a licenca **MIT**.
> 
> Copyright (c) 2023 Rhasspy Project
> 
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> - The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
> - Os modelos de voz (ONNX) estao sob licencas especificas por voz, incluindo licencas CC0 1.0 Universal.
>
> Para mais informacoes, consulte: https://github.com/rhasspy/piper

#### Integracao com rewards TTS

Quando um reward TTS é resgatado na Twitch:

1. O backend le `tts_config.json` para obter a velocidade configurada.
2. A velocidade é aplicada ao modelo PIPER especificado (ex: `pt_BR-cadu-medium`).
3. O audio sintetizado é gerado com a velocidade definida.
4. O arquivo WAV é salvo em `/mp3/tts-generated/` com um hash unique.
5. A URL do audio é enviada ao overlay para reproducao.

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

### Roleta de Torchlight

Novo overlay para Torchlight com roleta interativa que gira quando um reward específico é resgatado na Twitch.

#### Fluxo de execução

1. Usuario resgata o reward "Roleta de FE (Torchlight)" na Twitch.
2. A Twitch envia o evento para o webhook em `/twitch/eventsub`.
3. O backend atualiza `POWERUP_EVENT_STATE` com `seq`, `last_reward` e `last_event`.
4. A pagina OBS em `/torchlight/roleta/obs` faz polling a cada 1 segundo em `/twitch/powerup/state`.
5. Ao detectar mudanca no `seq`, a pagina identifica que é um novo evento.
6. A roleta gira por 4 segundos com animacao suave (cubic easeOut).
7. Ao final da animacao, o centro exibe o valor sorteado (50, 75, 100, 125, 200 ou 300).
8. A roleta fica visivel por 30 segundos e desaparece automaticamente.

#### Configuração do reward

No painel de Creator Dashboard da Twitch, crie um reward customizado com:

- **Titulo**: `Roleta de FE (Torchlight)`
- **ID do reward**: `28bce937-6821-426c-a186-713398767e9c` (ou outro, configuravel)
- **Custo**: à sua escolha (recomendado 1000-5000 pontos)
- **Imagem**: opcional, logo de Torchlight

#### Endpoints da roleta

- `GET /torchlight/roleta/obs`
	- Retorna a pagina HTML com estrutura da roleta (pointer, wheel, labels, center display)

- `GET /torchlight/roleta/obs.js`
	- JavaScript com logica de polling, animacao, som e matching de valores

- `GET /torchlight/roleta/obs.css`
	- CSS com estilo do wheel (conic-gradient), labels posicionadas via trigonometria, pointer (triangulo vermelho no topo)

- `GET /twitch/powerup/state`
	- Retorna JSON com `seq` (contador de atualizacoes), `last_reward` (ID do ultimo reward) e `last_event` (timestamp)
	- Exemplo: `{"seq": 42, "last_reward": "28bce937...", "last_event": 1704067200}`

- `GET|POST /twitch/powerup/test`
	- Testa manualmente o trigger da roleta sem precisar resgatar o reward na Twitch
	- Parametros opcionais:
		- `?label=Roleta%20de%20FE%20%28Torchlight%29` - filtra por titulo do reward (case-insensitive)
		- `?id=28bce937-6821-426c-a186-713398767e9c` - filtra por ID do reward
	- Exemplo: `http://localhost:5000/twitch/powerup/test?label=Roleta%20de%20FE`

#### Características da roleta

- **Valores**: 6 fatias com numeros [50, 75, 100, 125, 200, 300]
- **Peso**: Distribuicao em porcentagem 22% / 22% / 22% / 22% / 8% / 4%, mantendo a fatia de 300 menor
- **Cores**: Cada fatia tem cor distinta (vermelho, azul, verde, amarelo, roxo, laranja)
- **Animacao**: Gira 6+ voltas completas + angulo aleatorio extra, desacelerando suavemente
- **Som**: Tom de 1kHz tocado durante a rotacao a cada 10 graus
- **Precision**: O valor exato apontado pelo triangulo vermelho (topo) e calculado usando trigonometria e conic-gradient com `from -90deg`

#### Como usar no OBS

1. Crie uma Browser Source e aponte para `https://seu-servico.onrender.com/torchlight/roleta/obs`.
2. Configure as dimensoes: largura e altura `420px` (quadrado para o wheel).
3. Habilite `Atualizar pagina quando cena fica inativa` para evitar cache.
4. Coloque a source em uma cena dedicada ou sobreposição da cena de Torchlight.
5. A roleta ficara invisivel ate que o reward seja resgatado.
6. Para testar sem resgatar, chame: `curl http://localhost:5000/twitch/powerup/test?label=Roleta%20de%20FE%20%28Torchlight%29`

#### Personalizacao

Dentro da pagina HTML (`/torchlight/roleta/obs`), o atributo `data-default-reward` define qual reward ativa a roleta:

```html
<div id="wrapper" data-default-reward="28bce937-6821-426c-a186-713398767e9c,Roleta de FE (Torchlight)">
```

Pode-se filtrar por ID, titulo ou ambos (separados por virgula). A filtragem e case-insensitive.

Se necessario, pode-se passar `?reward=ID` ou `?label=TITULO` como query string na URL da Browser Source para sobrescrever.

### Cronômetro Regressivo

Novo overlay para exibir um cronômetro que começa em **03:00:00** e realiza contagem regressiva até **00:00:00**.

#### Fluxo de execução

1. A pagina OBS em `/obs/cronometro` é carregada inicialmente **invisível**.
2. Ao fazer um **GET** para `/obs/cronometro?action=start`, o cronômetro fica **visível** e inicia a contagem regressiva de 3 horas.
3. O cronômetro decrementa 1 segundo a cada intervalo até chegar a **00:00:00**.
4. Após 3 segundos de finalização (00:00:00), o cronômetro desaparece automaticamente e reseta para 03:00:00.
5. A formatação segue o mesmo padrão do **death counter OBS** (Arial Black, branca, 72px, efeito glow).

#### Endpoints do cronômetro

- `GET /obs/cronometro`
	- Retorna a página HTML com o cronômetro (inicialmente invisível)
	- Query parameters:
		- `?action=start` - inicia a contagem regressiva automaticamente ao carregar a página
		- `?time=SEGUNDOS` - define um tempo inicial diferente de 10800 segundos (ex: `?time=600` começa em 00:10:00)
	- Exemplo: `https://seu-servico.onrender.com/obs/cronometro?action=start`

- `GET /obs/cronometro.js`
	- JavaScript com lógica de contagem regressiva, formatação HH:MM:SS e visibilidade

- `GET /obs/cronometro.css`
	- CSS com estilo idêntico ao death counter (fonte, sombra, alinhamento)

#### Características

- **Duração**: Começa em 03:00:00 (10800 segundos / 3 horas)
- **Formato**: HH:MM:SS (ex: 03:00:00, 02:45:30, 00:00:01, 00:00:00)
- **Visibilidade inicial**: Invisível até acionado
- **Estilo**: Arial Black, branca, 72px, text-shadow com efeito de glow
- **Auto-reset**: Após atingir 00:00:00, aguarda 3 segundos e desaparece, reseta para 03:00:00
- **API JavaScript**: Expõe `window.cronometroAPI` para controle manual

#### API JavaScript

O cronômetro expõe as seguintes funções via `window.cronometroAPI`:

```javascript
window.cronometroAPI.start()      // Inicia a contagem regressiva
window.cronometroAPI.pause()      // Pausa a contagem
window.cronometroAPI.resume()     // Retoma a contagem a partir do ponto pausado
window.cronometroAPI.reset()      // Para e reseta para 03:00:00
window.cronometroAPI.setTime(segundos)  // Define novo tempo (ex: 120 para 02:00:00)
window.cronometroAPI.getTime()    // Retorna tempo restante em segundos
```

#### Como usar no OBS

1. Crie uma Browser Source e aponte para `https://seu-servico.onrender.com/obs/cronometro`.
2. Configure as dimensões desejadas (sugerido: 800x200 ou similar, com a fonte em 72px o cronômetro fica grande).
3. Adicione a Browser Source em uma cena ou sobreposição dedicada.
4. Para iniciar o cronômetro **automaticamente** ao carregar a cena, altere a URL para:
	- `https://seu-servico.onrender.com/obs/cronometro?action=start`
5. Alternativamente, pode-se chamar via comando do Nightbot:
	- `curl https://seu-servico.onrender.com/obs/cronometro?action=start`
   - Ou usar o console do navegador (F12) para chamar `window.cronometroAPI.start()`

#### Personalizações

**Iniciar com tempo customizado:**

Use o parâmetro `?time=SEGUNDOS` para começar com um tempo diferente:

```
https://seu-servico.onrender.com/obs/cronometro?action=start&time=60
```

Isso iniciará com 00:01:00 (1 minuto) em vez de 03:00:00.

**Controle via OBS Lua Script ou Comando:**

Se integrado com automações externas, pode-se fazer GET para:

```bash
# Iniciar
curl "http://localhost:5000/obs/cronometro?action=start"

# Com tempo customizado
curl "http://localhost:5000/obs/cronometro?action=start&time=300"
```

E no console JS da página (F12):

```javascript
// Iniciar
window.cronometroAPI.start()

// Pausar
window.cronometroAPI.pause()

// Retomar
window.cronometroAPI.resume()

// Resetar
window.cronometroAPI.reset()

// Definir tempo (em segundos)
window.cronometroAPI.setTime(120)  // 2 minutos
```

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
5. Ao ocorrer um novo resgate na Twitch, a pagina deve tocar o audio gerado para TTS (ou audio mapeado quando nao for TTS).

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
