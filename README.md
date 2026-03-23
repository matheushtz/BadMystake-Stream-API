# BadMystake Stream API

API em Flask para contador de mortes com foco em uso em live/OBS.

## O que esta aplicacao faz

- Mantem um contador de mortes em arquivo JSON (`dados.json`)
- Exibe o valor para Browser Source no OBS
- Incrementa o contador por endpoint HTTP
- Opcionalmente publica `dados.json` no GitHub a cada alteracao
- Possui endpoints de health check para Render

## Estrutura do projeto

- `app.py`: API principal
- `dados.json`: persistencia local do contador
- `obs_browser_refresh.lua`: script Lua para OBS (cache-buster de Browser Source)
- `requirements.txt`: dependencias Python
- `.env`: variaveis locais (arquivo ignorado no Git)

## Requisitos

- Python 3.10+
- pip
- (Opcional) Conta no Render para deploy
- (Opcional) Token GitHub para publish automatico

## Instalacao local

1. Instale dependencias:

```bash
pip install -r requirements.txt
```

2. Execute a API:

```bash
python app.py
```

3. A API sobe em:
- `http://127.0.0.1:5000` (local)
- No Render, usa automaticamente `PORT` do ambiente

## Endpoints

### Leituras

- `GET /death/get`
- `GET /death/read`

Retorno: apenas o valor de `mortes` (texto simples)

Exemplo de resposta:

```text
16
```

- `GET /death/read/obs`

Retorno: formato amigavel para overlay

```text
16 mortes
```

### Escritas

- `GET|POST /death/increment`

Incrementa `mortes` em +1.
Retorno: novo valor (texto simples)

- `GET /death/clear`

Reseta para valor padrao (`0`).
Retorno: `0`

- `GET|POST /death/save`

Salva qualquer chave/valor no JSON.
Aceita `key` e `value` por query string, form-data ou JSON body.

Exemplo:

```bash
curl "http://127.0.0.1:5000/death/save?key=fase&value=2"
```

Retorno: valor atual de `mortes` (texto simples).

### Health check

- `GET /`
- `GET /healthz`

Ambos retornam status `200`.

## Persistencia de dados

A API grava dados em `dados.json` localmente.

Importante para Render:
- Sem disco persistente, dados podem ser perdidos em restart/redeploy.
- Para persistencia real em Render, use Persistent Disk e aponte o arquivo para o volume montado (se desejar evoluir esse setup).

## Publicacao automatica no GitHub (opcional)

A cada alteracao no JSON, a API tenta publicar `dados.json` via GitHub API.

### Variaveis necessarias

Defina no ambiente (Render Environment ou local):

- `GITHUB_TOKEN`
- `GITHUB_OWNER` e `GITHUB_REPO`

ou, alternativamente:

- `GITHUB_REPOSITORY` no formato `owner/repo`

Opcional:

- `GITHUB_BRANCH` (padrao: `main`)
- `GITHUB_FILE_PATH` (padrao: `dados.json`)

### Permissao do token

Para token fine-grained, habilite:
- `Contents: Read and write`

### Mensagem de commit usada pela API

```text
chore: update dados.json
```

## Deploy no Render

### Configuracao minima

- Language: Python
- Build Command:

```bash
pip install -r requirements.txt
```

- Start Command:

```bash
python app.py
```

### Health check recomendado

- Health Check Path: `/healthz`

### Variaveis de ambiente recomendadas

- `GITHUB_TOKEN` (se usar publish GitHub)
- `GITHUB_OWNER` / `GITHUB_REPO` (ou `GITHUB_REPOSITORY`)
- `GITHUB_BRANCH=main`
- `GITHUB_FILE_PATH=dados.json`

## Integracao com OBS

Use Browser Source apontando para:

- `https://SEU-SERVICO.onrender.com/death/read/obs`

Ou para valor puro:

- `https://SEU-SERVICO.onrender.com/death/read`

Script Lua opcional para refresh periodico:
- arquivo `obs_browser_refresh.lua`

## Troubleshooting

### 1) `GET /health` retornando 404

Configure Health Check Path no Render para `/healthz`.

### 2) Reinicios inesperados

Verifique em Render > Events:
- restart por health check
- restart por alteracao de settings/env vars
- recycle de infraestrutura

### 3) Commit no GitHub nao acontece

Confira:
- token valido
- permissao `Contents: Read and write`
- owner/repo corretos
- branch existente
- logs da API (erros HTTP detalhados ja sao impressos)

### 4) `favicon.ico` 404

Normal em browser, pode ignorar.

## Seguranca

- Nao suba `.env` para o GitHub
- Nao exponha token em logs
- Se token vazar, revogue e gere outro imediatamente

## Licenca

Defina a licenca desejada (ex.: MIT) se for publicar o projeto publicamente.
