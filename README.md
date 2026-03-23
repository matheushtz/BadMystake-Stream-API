# BadMystake Stream API

API em Flask para controlar um contador de mortes para livestream/OBS (em tempo real utilizando comandos de chat Ex: Nightbot !morreu).

## O que o programa faz

1. Mantem um contador de mortes em `dados.json`.
2. Incrementa o contador via endpoint HTTP.
3. Retorna o valor para uso em overlay no OBS.
4. Expoe rotas de health check para manter o servico online no Render.

## Arquivos principais

- `app.py`: API principal.
- `dados.json`: arquivo com o valor atual do contador.
- `obs_browser_refresh.lua`: script de refresh para Browser Source no OBS.

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
