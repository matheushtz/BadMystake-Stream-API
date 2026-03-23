# BadMystake Stream API

API em Flask para controlar um contador de mortes para live/OBS.

## Ambiente alvo

Esta aplicacao foi pensada para rodar no host do Render.

- Em producao, o Render define automaticamente a porta via variavel `PORT`.
- O endpoint publico esperado e o do proprio servico Render.

## O que o programa faz

1. Mantem um contador de mortes em `dados.json`.
2. Incrementa o contador via endpoint HTTP.
3. Retorna o valor para uso em overlay no OBS.
4. Expoe rotas de health check para manter o servico online no Render.

## Arquivos principais

- `app.py`: API principal.
- `dados.json`: arquivo com o valor atual do contador.
- `obs_browser_refresh.lua`: script para ser adicionado dentro do proprio OBS (Tools > Scripts) e forcar o refresh da Browser Source.

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
