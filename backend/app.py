
import os
import io
import re
import time
import uuid
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Importa nosso módulo de autenticação
import auth

app = Flask(__name__)
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
# A chave secreta é carregada a partir do arquivo .env para manter a sessão estável.
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# A URL do frontend é carregada da variável de ambiente para flexibilidade.
FRONTEND_URL = os.getenv("FRONTEND_URL")
if FRONTEND_URL:
    CORS(app, origins=[FRONTEND_URL], supports_credentials=True)

# --- Armazenamento de Tarefas em Memória ---
tasks = {}

# --- ROTAS DE AUTENTICAÇÃO ---

@app.route("/login")
def login():
    """Redireciona o usuário para a página de login da Microsoft."""
    session["state"] = str(uuid.uuid4()) # Proteção CSRF
    auth_url = auth._build_auth_url(state=session["state"])
    return redirect(auth_url)

@app.route(auth.REDIRECT_PATH) # Rota definida no .env (/get-token)
def authorized():
    """Callback da Microsoft após o login. Troca o código pelo token."""
    if request.args.get('state') != session.get("state"):
        return redirect(url_for("index")) # Redireciona para a home se o state não bater
    
    token = auth._get_token_from_code()
    if "error" in token:
        return jsonify(token), 400

    # Login bem-sucedido, redireciona para a página de resultados do frontend
    return redirect(f"{FRONTEND_URL}/resultados.html")

@app.route("/logout")
def logout():
    """Faz o logout do usuário limpando a sessão."""
    session.clear()
    # Redireciona para a URL de logout da Microsoft e depois volta para a home do app
    logout_redirect_uri = f"{FRONTEND_URL}/index.html"
    return redirect(
        auth.AUTHORITY + "/oauth2/v2.0/logout?" + f"post_logout_redirect_uri={logout_redirect_uri}")

@app.route("/")
def index():
    """Página inicial. Redireciona para o frontend."""
    if not session.get("user"):
        return redirect(url_for("login"))
    return redirect(f"{FRONTEND_URL}/index.html")

# --- Endpoints da API (AGORA PROTEGIDOS) ---

@app.before_request
def check_authentication():
    """Verifica a autenticação antes de cada request para a API."""
    if request.path.startswith('/api/'):
        if "user" not in session:
            return jsonify({"erro": "Acesso não autorizado. Faça o login."}), 401

@app.route('/api/me')
def me():
    """Endpoint para o frontend verificar se o usuário está logado e pegar seus dados."""
    user = session.get("user")
    if not user:
        return jsonify({"logged_in": False}), 401
    return jsonify({"logged_in": True, "user": user})

@app.route('/api/processar', methods=['POST'])
def processar_api():
    # A verificação de login já foi feita pelo @app.before_request
    dados = request.get_json()
    if not dados:
        return jsonify({"erro": "Corpo da requisição precisa ser um JSON."}),

    processos_texto = dados.get('processos')
    file_contents = dados.get('file_contents')

    lista_consulta = []
    if processos_texto:
        lista_consulta = [proc.strip() for proc in processos_texto.split(',') if re.match(r'[0-9]{7}[-][0-9]{2}[.][0-9]{4}[.][8][.][2][6][.][0-9]{4}', proc.strip())]
    elif file_contents:
        for line in file_contents.split('\n'):
            lista_consulta.extend(encontra_processos(line))
    
    if not lista_consulta:
        return jsonify({"erro": "Nenhum número de processo válido encontrado."}),

    task_id = str(uuid.uuid4())
    tasks[task_id] = {'status': 'iniciando', 'progress': {'current': 0, 'total': len(lista_consulta)}, 'user_id': session["user"]["oid"]}
    
    thread = threading.Thread(target=extrai_dados_e_atualiza_tarefa, args=(task_id, lista_consulta))
    thread.start()
    
    return jsonify({"task_id": task_id}), 202

@app.route('/api/status/<task_id>', methods=['GET'])
def status_api(task_id):
    task = tasks.get(task_id)
    if not task or task.get('user_id') != session["user"]["oid"]:
        return jsonify({"status": "nao_encontrado"}), 404
    
    # O resto da função continua igual...
    if task['status'] == 'concluido':
        columns = ['Número do Processo', 'Foro e Vara / Órgão Julgador', 'Juiz / Relator', 'Classe', 'Assunto', 'Situação', 'Partes e Advogados', 'Valor', 'Movimentação']
        df_resultados = pd.DataFrame([r for r in task.get('resultados', []) if len(r) == 9], columns=columns)
        if not df_resultados.empty:
            df_resultados['Data'] = df_resultados['Movimentação'].str[0]
            df_resultados['Movimento'] = df_resultados['Movimentação'].str[2]
            df_resultados = df_resultados.drop(columns='Movimentação')
        
        df_erros = pd.DataFrame(task.get('erros', []), columns=['Número do processo', 'Informação'])
        df_inconclusivos = pd.DataFrame(task.get('inconclusivos', []), columns=['Número do processo', 'Observações'])

        return jsonify({
            'status': 'concluido',
            'progress': task.get('progress'),
            'resultados': df_resultados.to_dict('records'),
            'erros': df_erros.to_dict('records'),
            'inconclusivos': df_inconclusivos.to_dict('records')
        })
    
    return jsonify({'status': task['status'], 'progress': task.get('progress')})

@app.route('/api/download_excel/<task_id>')
def download_excel_api(task_id):
    task = tasks.get(task_id)
    if not task or task['status'] != 'concluido' or task.get('user_id') != session["user"]["oid"]:
        return "Tarefa não encontrada ou não concluída.", 404

    # O resto da função continua igual...
    columns = ['Número do Processo', 'Foro e Vara / Órgão Julgador', 'Juiz / Relator', 'Classe', 'Assunto', 'Situação', 'Partes e Advogados', 'Valor', 'Movimentação']
    df_resultados = pd.DataFrame([r for r in task.get('resultados', []) if len(r) == 9], columns=columns)
    if not df_resultados.empty:
        df_resultados['Data'] = df_resultados['Movimentação'].str[0]
        df_resultados['Movimento'] = df_resultados['Movimentação'].str[2]
        df_resultados = df_resultados.drop(columns='Movimentação')
    
    df_erros = pd.DataFrame(task.get('erros', []), columns=['Número do processo', 'Informação'])
    df_inconclusivos = pd.DataFrame(task.get('inconclusivos', []), columns=['Número do processo', 'Observações'])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_resultados.to_excel(writer, sheet_name='Resultados', index=False)
        df_erros.to_excel(writer, sheet_name='Erros ou não processados', index=False)
        df_inconclusivos.to_excel(writer, sheet_name='Inconclusivos', index=False)
    
    output.seek(0)
    data_e_hora_em_texto = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime('%d-%m-%Y_%Hh%Mmin')
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'Resultados_{data_e_hora_em_texto}.xlsx')

@app.route('/api/download_txt/<task_id>')
def download_txt_api(task_id):
    task = tasks.get(task_id)
    if not task or task['status'] != 'concluido' or task.get('user_id') != session["user"]["oid"]:
        return "Tarefa não encontrada ou não concluída.", 404

    output = io.StringIO()
    output.write(f'Resultado dos processos recebidos:\n\n')
    
    lista_resultados = task.get('resultados', [])
    for l in lista_resultados:
        output.write(f'\nNúmero do processo: {l[0]}\n')
        output.write(f'Foro e Vara / Órgão Julgador: {l[1]}\n')
        output.write(f'Juiz / Relator: {l[2]}\n')
        output.write(f'Classe: {l[3]}\n')
        output.write(f'Assunto: {l[4]}\n')
        output.write(f'Situação: {l[5]}\n')
        output.write(f'Partes e Advogados: {l[6]}\n')
        output.write(f'Valor: {l[7]}\n')
        
        try:
            output.write(f'Data: {l[8][0]}\n')
            output.write(f'Movimentação: {l[8][2]}\n\n')
            output.write('*'.ljust(40, '*') + '\n')
        except:
            output.write('*'.ljust(40, '*') + '\n')
    
    data_e_hora_em_texto = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime('%d-%m-%Y_%Hh%Mmin')
    output.write('\n\nRelatório emitido em: ' + data_e_hora_em_texto)
    
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/plain', as_attachment=True, download_name=f'Resultados_{data_e_hora_em_texto}.txt')

def extrai_dados_e_atualiza_tarefa(task_id, lista_consulta):
    # Listas locais para esta tarefa específica
    lista_resultados = []
    lista_erros = []
    lista_inconclusivos = []

    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver = None
    try:
        tasks[task_id]['status'] = 'processando'
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        for i, n_processo in enumerate(lista_consulta):
            try:
                tasks[task_id]['progress'] = {'current': i + 1, 'total': len(lista_consulta)}
                html_2_grau = consultar_processo_2_grau(driver, n_processo)
                soup_2_grau = BeautifulSoup(html_2_grau, 'html.parser')
                time.sleep(0.8)
                dados_2_grau = extrair_dados_2_grau(soup_2_grau)
                if dados_2_grau and dados_2_grau[0] != 'Não disponível':
                    lista_resultados.append(dados_2_grau)
                    continue

                html_1_grau = consultar_processo_1_grau(n_processo)
                soup_1_grau = BeautifulSoup(html_1_grau, 'html.parser')
                time.sleep(0.8)

                senha_tag = soup_1_grau.find('td', class_='modalTitulo', string='Senha do processo')
                cnj_tag = soup_1_grau.find('td', string=lambda text: text and "Atendendo a resolução 121 do CNJ" in text)
                partes_table = soup_1_grau.find(id='tablePartesPrincipais')
                movimentacoes_table = soup_1_grau.find(id='tabelaUltimasMovimentacoes')
                if (senha_tag or cnj_tag) and not (partes_table and movimentacoes_table):
                    lista_erros.append([n_processo, "Processo em segredo de justiça."])
                    continue

                dados_1_grau = extrair_dados_1_grau(soup_1_grau)
                if dados_1_grau:
                    lista_resultados.append(dados_1_grau)
                    continue
                
                dados_incidente = extrair_dados_1_grau_incidente(soup_1_grau, n_processo)
                if dados_incidente:
                    lista_resultados.append(dados_incidente)
                    continue

                try:
                    paginacao = soup_1_grau.find(class_='resultadoPaginacao').text.strip()
                    if paginacao:
                        lista_inconclusivos.append([n_processo, paginacao])
                        continue
                except AttributeError:
                    pass

                msg_retorno = soup_1_grau.find(id='mensagemRetorno')
                if msg_retorno and msg_retorno.text.strip():
                    lista_erros.append([n_processo, msg_retorno.text.strip()])
                    continue
                
                lista_erros.append([n_processo, "Não foi possível extrair os dados."])

            except Exception as e:
                lista_erros.append([n_processo, f"Erro inesperado durante o processamento."])

    except Exception as e:
        lista_erros.append(["Sistema", f"Falha ao iniciar o navegador: {e}"])
    finally:
        if driver:
            driver.quit()
        
        tasks[task_id]['status'] = 'concluido'
        tasks[task_id]['resultados'] = lista_resultados
        tasks[task_id]['erros'] = lista_erros
        tasks[task_id]['inconclusivos'] = lista_inconclusivos
        tasks[task_id]['timestamp_conclusao'] = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()

# --- Funções de apoio (O conteúdo permanece o mesmo) ---
def encontra_processos(linha_de_texto):
    return re.findall(r'[0-9]{7}[-][0-9]{2}[.][0-9]{4}[.][8][.][2][6][.][0-9]{4}', linha_de_texto)

def consultar_processo_1_grau(numero_processo):
    params = {'conversationId': '', 'cbPesquisa': 'NUMPROC', 'numeroDigitoAnoUnificado': numero_processo[:15], 'foroNumeroUnificado': numero_processo[-4:], 'dadosConsulta.valorConsultaNuUnificado': numero_processo, 'dadosConsulta.valorConsulta': '', 'dadosConsulta.tipoNuProcesso': 'UNIFICADO'}
    base_url = 'https://esaj.tjsp.jus.br'
    response = requests.get(f'{base_url}/cpopg/search.do', params=params)
    content = response.content
    soup = BeautifulSoup(content, 'html.parser')
    listagem = soup.find(id='listagemDeProcessos')
    if listagem:
        links = listagem.find_all('a', class_='linkProcesso')
        for link in links:
            if numero_processo in link.get_text(strip=True):
                return requests.get(f"{base_url}{link['href']}").content
        return content
    return content

def consultar_processo_2_grau(driver, numero_processo):
    base_url = "https://esaj.tjsp.jus.br"
    url = f"{base_url}/cposg/search.do?conversationId=&paginaConsulta=0&cbPesquisa=NUMPROC&numeroDigitoAnoUnificado={numero_processo[:15]}&foroNumeroUnificado={numero_processo[-4:]}&dePesquisaNuUnificado={numero_processo}&dePesquisa=&tipoNuProcesso=UNIFICADO"
    driver.get(url)
    time.sleep(1)
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    listagem = soup.find(id='listagemDeProcessos')
    if listagem:
        links = listagem.find_all('a', class_='linkProcesso')
        for link in links:
            if numero_processo in link.get_text(strip=True):
                driver.get(f"{base_url}{link['href']}")
                time.sleep(2)
                return driver.page_source
        return driver.page_source
    try:
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "modal-body")))
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.NAME, "processoSelecionado"))).click()
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "botaoEnviarIncidente"))).click()
        time.sleep(2)
    except TimeoutException:
        pass
    return driver.page_source

def separa_dados(resultado):
    return [' '.join(n.get_text(separator=' ').strip().split()) for n in resultado]

def extrair_dados_1_grau(soup):
    try:
        if not soup.find(id='numeroProcesso'): return None
        numero = soup.find(id='numeroProcesso').text.strip()
        foro_vara = f'{soup.find(id="foroProcesso").text.strip() if soup.find(id="foroProcesso") else "Não disponível"} - {soup.find(id="varaProcesso").text.strip() if soup.find(id="varaProcesso") else "Não disponível"}'
        juiz = soup.find(id='juizProcesso').text.strip() if soup.find(id='juizProcesso') else 'Não disponível'
        classe = soup.find(id='classeProcesso').text.strip() if soup.find(id='classeProcesso') else 'Não disponível'
        assunto = soup.find(id='assuntoProcesso').text.strip() if soup.find(id='assuntoProcesso') else 'Não disponível'
        valor = soup.find(id='valorAcaoProcesso').text.strip() if soup.find(id='valorAcaoProcesso') else 'Não disponível'
        situacao = soup.find(id='labelSituacaoProcesso').text.strip() if soup.find(id='labelSituacaoProcesso') else 'Não disponível'
        parte = soup.find(class_='nomeParteEAdvogado').text.strip().replace('\n', '').replace('\t', '').replace('  ', '') if soup.find(class_='nomeParteEAdvogado') else 'Não disponível'
        resultado = soup.find(class_='containerMovimentacao')
        movs = separa_dados(resultado.find_all('td') if resultado else [])
        return [numero, foro_vara, juiz, classe, assunto, situacao, parte, valor, movs]
    except Exception: return None

def extrair_dados_1_grau_incidente(soup, n_processo):
    try:
        header_span = soup.find('span', class_='unj-larger')
        if not header_span: return None
        classe = header_span.get_text(strip=True).split('(')[0].strip() if '(' in header_span.get_text() else 'Não disponível'
        foro_vara = f'{soup.find(id="foroProcesso").text.strip() if soup.find(id="foroProcesso") else "Não disponível"} - {soup.find(id="varaProcesso").text.strip() if soup.find(id="varaProcesso") else "Não disponível"}'
        assunto = soup.find(id='assuntoProcesso').text.strip() if soup.find(id='assuntoProcesso') else 'Não disponível'
        primeira_mov = soup.find(class_='descricaoMovimentacao')
        situacao = primeira_mov.get_text(strip=True).split('\n')[0].strip() if primeira_mov else 'Não disponível'
        parte = soup.find(class_='nomeParteEAdvogado').text.strip().replace('\n', '').replace('\t', '').replace('  ', '') if soup.find(class_='nomeParteEAdvogado') else 'Não disponível'
        resultado = soup.find(class_='containerMovimentacao')
        movs = separa_dados(resultado.find_all('td') if resultado else [])
        return [n_processo, foro_vara, 'Não disponível', classe, assunto, situacao, parte, 'Não disponível', movs]
    except Exception: return None

def extrair_dados_2_grau(soup):
    try:
        if not soup.find(id='numeroProcesso'): return None
        numero = soup.find(id='numeroProcesso').text.strip()
        orgao = soup.find(id='orgaoJulgadorProcesso').text.strip() if soup.find(id='orgaoJulgadorProcesso') else 'Não disponível'
        relator = soup.find(id='relatorProcesso').text.strip() if soup.find(id='relatorProcesso') else 'Não disponível'
        classe = soup.find(id='classeProcesso').text.strip() if soup.find(id='classeProcesso') else 'Não disponível'
        assunto = soup.find(id='assuntoProcesso').text.strip() if soup.find(id='assuntoProcesso') else 'Não disponível'
        valor = soup.find(id='valorAcaoProcesso').text.strip() if soup.find(id='valorAcaoProcesso') else 'Não disponível'
        situacao = soup.find(id='situacaoProcesso').text.strip() if soup.find(id='situacaoProcesso') else 'Não disponível'
        parte = soup.find(class_='nomeParteEAdvogado').text.strip().replace('\n', '').replace('\t', '').replace('  ', '') if soup.find(class_='nomeParteEAdvogado') else 'Não disponível'
        resultado = soup.find(class_='movimentacaoProcesso')
        movs = separa_dados(resultado.find_all('td') if resultado else [])
        return [numero, orgao, relator, classe, assunto, situacao, parte, valor, movs]
    except AttributeError: return None

if __name__ == '__main__':
    # A porta 5000 é comum para desenvolvimento Flask
    app.run(host='127.0.0.1', port=5000, debug=True)
