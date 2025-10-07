# Use uma imagem oficial do Python
FROM python:3.11-slim

# Instala o Google Chrome e suas dependências
RUN apt-get update && apt-get install -y wget gnupg --no-install-recommends     && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg     && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list     && apt-get update && apt-get install -y google-chrome-stable --no-install-recommends     && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho no contêiner
WORKDIR /app

# Copia o arquivo de dependências e instala as dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código da aplicação para o diretório de trabalho
COPY . .

# Expõe a porta que o Gunicorn irá rodar
EXPOSE 8000

# Comando para rodar a aplicação com Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]