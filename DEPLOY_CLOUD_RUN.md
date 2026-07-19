# Cloud Run Deploy Guide

Este arquivo guarda os dados e comandos usados para publicar novas imagens no Cloud Run deste projeto.

## Dados do ambiente

- Project ID: `stream-badmystake`
- Region: `southamerica-east1`
- Cloud Run service: `streambadmystake`
- Artifact Registry repository: `cloud-run-source-deploy`
- Public URL: `https://streambadmystake-1027092599122.southamerica-east1.run.app`

## Regras de seguranca

- Nao salvar tokens, chaves ou credenciais neste arquivo.
- Usar apenas nomes de projeto, regiao, servico e repositorio.
- Se algum valor mudar no console do Google Cloud, atualizar este arquivo manualmente.

## Comandos uteis

### Ver a imagem atualmente em uso no Cloud Run

```powershell
gcloud run services describe streambadmystake --region southamerica-east1 --format="value(spec.template.spec.containers[0].image)"
```

### Ver o projeto atual configurado no gcloud

```powershell
gcloud config get-value project
```

### Listar servicos do Cloud Run no projeto atual

```powershell
gcloud run services list
```

### Listar repositorios do Artifact Registry na regiao

```powershell
gcloud artifacts repositories list --location=southamerica-east1
```

### Buildar uma nova imagem com tag nova

```powershell
gcloud builds submit --tag southamerica-east1-docker.pkg.dev/stream-badmystake/cloud-run-source-deploy/streambadmystake:v4-act-man .
```

### Publicar a nova imagem no Cloud Run

```powershell
gcloud run deploy streambadmystake --image southamerica-east1-docker.pkg.dev/stream-badmystake/cloud-run-source-deploy/streambadmystake:v4-act-man --region southamerica-east1 --platform managed
```

### Ver logs do servico depois do deploy

```powershell
gcloud run services logs read streambadmystake --region southamerica-east1
```

## Passo a passo rapido

1. Abrir o terminal na pasta do projeto.
2. Verificar o projeto atual com `gcloud config get-value project`.
3. Rodar o build da imagem com uma nova tag.
4. Fazer o deploy da imagem no Cloud Run.
5. Conferir a URL publica e os logs do servico.

## Observacao tecnica

O fluxo de TTS foi ajustado para usar arquivos temporarios locais durante a execucao, entao o Cloud Run nao precisa de bucket extra para esse caso.