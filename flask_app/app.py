from flask import Flask, render_template, request, redirect, url_for, send_file
import requests
import pandas as pd
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
import io

app = Flask(__name__)

data_e_hora_em_texto = datetime.now().strftime('%d-%m-%Y_%Hh%Mmin')

# Criação das listas vazias
lista_resultados = []
lista_erros = []
lista_inconclusivos = []

def encontra_processos(linha_de_texto):
    """Encontra os números de processos (CNJ) únicos nas linhas de texto examinadas."""
    return re.findall(r'[0-9]{7}[-][0-9]{2}[.][0-9]{4}[.][8][.][2][6][.][0-9]{4}', linha_de_texto)

def consultar_processo_1_grau(numero_processo):
    """Retorna o html (content) da pesquisa de 1ª instância"""
    params = {
        'conversationId': '',
        'cbPesquisa': 'NUMPROC',
        'numeroDigitoAnoUnificado': numero_processo[:15],
        'foroNumeroUnificado': numero_processo[-4:],
        'dadosConsulta.valorConsultaNuUnificado': numero_processo,
        'dadosConsulta.valorConsulta': '',
        'dadosConsulta.tipoNuProcesso': 'UNIFICADO'
    }
    return requests.get('https://esaj.tjsp.jus.br/cpopg/search.do', params=params).content

def consultar_processo_2_grau(numero_processo):
    """Retorna o html (content) da pesquisa de 2ª instância"""
    params = {
        'conversationId': '',
        'paginaConsulta': '0',
        'cbPesquisa': 'NUMPROC',
        'numeroDigitoAnoUnificado': numero_processo[:15],
        'foroNumeroUnificado': numero_processo[-4:],
        'dePesquisaNuUnificado': numero_processo,
        'dePesquisa': '',
        'tipoNuProcesso': 'UNIFICADO'
    }
    return requests.get('https://esaj.tjsp.jus.br/cposg/search.do', params=params).content

def separa_dados(resultado):
    lista = []
    for n in resultado:
        lista.append(n.text.strip())
    return lista

def extrair_dados_1_grau(soup):
    try:
        numero = soup.find(id='numeroProcesso')
        numero = numero.text.strip()

        foro = soup.find(id='foroProcesso')
        foro = foro.text.strip() if foro else 'Não disponível'
        
        vara = soup.find(id='varaProcesso')
        vara = vara.text.strip() if vara else 'Não disponível'
        foro_vara = f'{foro} - {vara}'
        
        juiz = soup.find(id='juizProcesso')
        juiz = juiz.text.strip() if juiz else 'Não disponível'
        
        classe = soup.find(id='classeProcesso')
        classe = classe.text.strip() if classe else 'Não disponível'
        
        assunto = soup.find(id='assuntoProcesso')
        assunto = assunto.text.strip() if assunto else 'Não disponível'
        
        valor = soup.find(id='valorAcaoProcesso')
        valor = valor.text.strip() if valor else 'Não disponível'
        
        situacao = soup.find(id='labelSituacaoProcesso')
        situacao = situacao.text.strip() if situacao else 'Não disponível'
        
        parte = soup.find(class_='nomeParteEAdvogado')
        parte = parte.text.strip() if parte else 'Não disponível'
        parte = parte.replace('\n', '').replace('\t', '').replace('  ', '')
        
        resultado = soup.find_all(class_='containerMovimentacao')
        resultado = resultado[0].find_all('td') if resultado else []

        return [numero, foro_vara, juiz, classe, assunto, situacao, parte, valor, separa_dados(resultado)]
    except AttributeError as e:
        print(f"Erro ao extrair dados do processo 1º grau: {e}")
        return None

def extrair_dados_2_grau(soup):
    try:
        numero = soup.find(id='numeroProcesso')
        numero = numero.text.strip()
        
        orgao = soup.find(id='orgaoJulgadorProcesso')
        orgao = orgao.text.strip() if orgao else 'Não disponível'
        
        relator = soup.find(id='relatorProcesso')
        relator = relator.text.strip() if relator else 'Não disponível'
        
        classe = soup.find(id='classeProcesso')
        classe = classe.text.strip() if classe else 'Não disponível'
        
        assunto = soup.find(id='assuntoProcesso')
        assunto = assunto.text.strip() if assunto else 'Não disponível'
        
        valor = soup.find(id='valorAcaoProcesso')
        valor = valor.text.strip() if valor else 'Não disponível'
        
        situacao = soup.find(id='situacaoProcesso')
        situacao = situacao.text.strip() if situacao else 'Não disponível'
        
        parte = soup.find(class_='nomeParteEAdvogado')
        parte = parte.text.strip() if parte else 'Não disponível'
        parte = parte.replace('\n', '').replace('\t', '').replace('  ', '')
        
        resultado = soup.find_all(class_='movimentacaoProcesso')
        resultado = resultado[0].find_all('td') if resultado else []

        return [numero, orgao, relator, classe, assunto, situacao, parte, valor, separa_dados(resultado)]
    except AttributeError as e:
        print(f"Erro ao extrair dados do processo 2º grau: {e}")
        return None

def extrai_dados(lista_consulta):
    for n_processo in lista_consulta:
        print(f"Processando o processo {n_processo}...")

        erro_1_grau = False
        erro_2_grau = False
        dados = None

        html = consultar_processo_1_grau(n_processo)
        soup = BeautifulSoup(html, 'html.parser')
        time.sleep(0.8)

        try:
            msg = soup.find(id='mensagemRetorno')
            if msg and msg.text.strip():
                erro_1_grau = True
        except:
            pass

        if not erro_1_grau:
            dados = extrair_dados_1_grau(soup)

        if not dados or dados[0] == 'Não disponível':
            html = consultar_processo_2_grau(n_processo)
            soup = BeautifulSoup(html, 'html.parser')
            time.sleep(0.8)

            try:
                msg = soup.find(id='mensagemRetorno')
                if msg and msg.text.strip():
                    erro_2_grau = True
            except:
                pass

            if not erro_2_grau:
                dados = extrair_dados_2_grau(soup)

        if dados:
            lista_resultados.append(dados)
        else:
            try:
                paginacao = soup.find(class_='resultadoPaginacao').text.strip()
                lista_inconclusivos.append([n_processo, paginacao])
            except:
                lista_erros.append([n_processo, msg])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/processar', methods=['POST'])
def processar():
    processos = request.form['processos']
    lista_consulta = [proc.strip() for proc in processos.split(',') if re.match(r'[0-9]{7}[-][0-9]{2}[.][0-9]{4}[.][8][.][2][6][.][0-9]{4}', proc.strip())]
    
    if not lista_consulta:
        return 'Nenhum número de processo válido encontrado.', 400
    
    extrai_dados(lista_consulta)
    return redirect(url_for('resultados'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            file_contents = file.read().decode('latin-1')
            lista_consulta = []
            for line in file_contents.split('\n'):
                lista_consulta.extend(encontra_processos(line))
            extrai_dados(lista_consulta)
            return redirect(url_for('resultados'))

@app.route('/resultados')
def resultados():
    columns = ['Número do Processo', 'Foro e Vara / Órgão Julgador', 'Juiz / Relator', 'Classe', 'Assunto', 'Situação', 'Partes e Advogados', 'Valor', 'Movimentação']
    df_resultados = pd.DataFrame([resultado for resultado in lista_resultados if len(resultado) == 9], columns=columns)
    df_resultados['Data'] = df_resultados['Movimentação'].str[0]
    df_resultados['Movimento'] = df_resultados['Movimentação'].str[2]
    df_resultados = df_resultados.drop(columns='Movimentação')
    
    df_erros = pd.DataFrame(lista_erros, columns=['Número do processo', 'Informação'])
    df_inconclusivos = pd.DataFrame(lista_inconclusivos, columns=['Número do processo', 'Observações'])
    
    results_html = df_resultados.to_html(classes='table table-striped')
    errors_html = df_erros.to_html(classes='table table-striped')
    inconclusives_html = df_inconclusivos.to_html(classes='table table-striped')
    
    return render_template('resultados.html', results_table=results_html, errors_table=errors_html, inconclusivos_table=inconclusives_html)

@app.route('/download_excel')
def download_excel():
    columns = ['Número do Processo', 'Foro e Vara / Órgão Julgador', 'Juiz / Relator', 'Classe', 'Assunto', 'Situação', 'Partes e Advogados', 'Valor', 'Movimentação']
    df_resultados = pd.DataFrame([resultado for resultado in lista_resultados if len(resultado) == 9], columns=columns)
    df_resultados['Data'] = df_resultados['Movimentação'].str[0]
    df_resultados['Movimento'] = df_resultados['Movimentação'].str[2]
    df_resultados = df_resultados.drop(columns='Movimentação')
    
    df_erros = pd.DataFrame(lista_erros, columns=['Número do processo', 'Informação'])
    df_inconclusivos = pd.DataFrame(lista_inconclusivos, columns=['Número do processo', 'Observações'])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_resultados.to_excel(writer, sheet_name='Resultados', index=False)
        df_erros.to_excel(writer, sheet_name='Erros ou não processados', index=False)
        df_inconclusivos.to_excel(writer, sheet_name='Inconclusivos', index=False)
    
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'Resultados_{data_e_hora_em_texto}.xlsx')

@app.route('/download_txt')
def download_txt():
    output = io.StringIO()
    
    output.write(f'Resultado dos processos recebidos:\n\n')
    
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
            output.write('*' * 40 + '\n')
        except:
            output.write('*' * 40 + '\n')
    
    output.write('\n\nRelatório emitido em: ' + data_e_hora_em_texto)
    
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/plain', as_attachment=True, download_name=f'Resultados_{data_e_hora_em_texto}.txt')
    
if __name__ == '__main__':
    app.run(debug=True)
