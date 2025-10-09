# Deploy do Backend (Flask) como Container

Este guia descreve como construir e deployar o backend (pasta `backend/`) como um container Docker para o Azure App Service ou ACR/GHCR.

Pré-requisitos
- Conta Azure e permissões para criar/atualizar um Web App (App Service) e/ou ACR.
- Secrets configurados no GitHub (Settings > Secrets):
  - `AZURE_CREDENTIALS` — JSON para `azure/login@v1` (obrigatório para deploy no Azure)
  - `WEBAPP_NAME` — nome do App Service (Web App) para receber a imagem
  - `RESOURCE_GROUP` — resource group do App Service
  - `REGISTRY_USERNAME` / `REGISTRY_PASSWORD` — credenciais do registry (se necessário)
  - `ACR_NAME` / `ACR_LOGIN_SERVER` — (opcional) para push para ACR
  - `GHCR_PAT` — (opcional) token para permitir App Service puxar da GHCR

O workflow criado
- `.github/workflows/backend-container-deploy.yml`:
  - Constrói a imagem Docker a partir de `backend/Dockerfile`.
  - Envia a imagem para GHCR (ghcr.io/.../pesquisaprocessual-backend:${{ github.sha }}).
  - Opcionalmente puxa essa imagem para ACR e envia para lá.
  - Atualiza a configuração do App Service para usar a imagem (via `az webapp config container set`) e reinicia o App Service.

Configurações de runtime
- O `Dockerfile` atual instala Google Chrome e dependências, e roda a aplicação com Gunicorn na porta 8000.
- No Azure App Service para Containers, configure a porta de entrada para `8000` (App Service detecta via WEBSITES_PORT ou através da configuração do container).

Autenticação (Entra ID / Azure AD)
- Você utiliza MSAL no Flask; certifique-se que no portal do Entra ID:
  - `Redirect URI` inclua a URL do seu backend, por exemplo `https://<WEBAPP_NAME>.azurewebsites.net/get-token` se `REDIRECT_PATH` = `/get-token`.
  - `Client Secret` esteja registrado e disponibilizado no App Service como `CLIENT_SECRET` (variável de ambiente).
  - `CLIENT_ID`, `AUTHORITY`, `SCOPE`, `REDIRECT_PATH` e `FRONTEND_URL` também devem estar configuradas como Application Settings no App Service.

CORS e Frontend
- Como o frontend está hospedado em Azure Static Web Apps, defina `FRONTEND_URL` com a URL do Static Web App (`https://<your-app>.azurestaticapps.net`) nas Application Settings do Web App.

Observações sobre Selenium
- Rodar Selenium com Chrome headless dentro de App Service funciona se o container incluir Chrome (seu Dockerfile já faz isso). Atenção a limites de recursos e tempo de execução.

Testes locais
- Para rodar localmente (buildar e testar):
```bash
cd backend
docker build -t pesquisaprocessual-backend:local .
docker run -e FRONTEND_URL=http://localhost:3000 -e FLASK_SECRET_KEY=secret -p 8000:8000 pesquisaprocessual-backend:local
```

Passos finais
- Adicione os secrets no repositório do GitHub e faça push para `main` para ativar o workflow.
- No portal Azure, verifique as Application Settings e Redirect URIs.
