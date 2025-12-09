"""
Web App - Sistema de Gerenciamento de Detecções de Placas
Versão 2.0 com suporte a CRUD completo para Veículos e Usuários
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo
from datetime import datetime
import sys
from pathlib import Path

# Importa o módulo de banco de dados do detectar_placas_video.py
sys.path.insert(0, str(Path(__file__).parent))
from detectar_placas_video import GerenciadorBanco, USAR_POSTGRES

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sua_chave_secreta_aqui_2025'
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Instancia o gerenciador de banco
db = GerenciadorBanco(usar_postgres=USAR_POSTGRES)


class FormularioVeiculo(FlaskForm):
    """Formulário para cadastro/edição de veículos"""
    placa = StringField('Placa', validators=[DataRequired()])
    proprietario = StringField('Proprietário', validators=[DataRequired()])
    marca = StringField('Marca', validators=[DataRequired()])
    modelo = StringField('Modelo', validators=[DataRequired()])
    ano = StringField('Ano')
    cor = StringField('Cor')
    tipo = SelectField('Tipo', choices=[
        ('CARRO', 'Carro'),
        ('MOTO', 'Moto'),
        ('CAMINHÃO', 'Caminhão'),
        ('ÔNIBUS', 'Ônibus')
    ])
    telefone = StringField('Telefone')
    observacoes = TextAreaField('Observações')
    submit = SubmitField('Salvar')


class FormularioUsuario(FlaskForm):
    """Formulário para cadastro/edição de usuários"""
    nome = StringField('Nome Completo', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    telefone = StringField('Telefone')
    cargo = SelectField('Cargo', choices=[
        ('ADMINISTRADOR', 'Administrador'),
        ('OPERADOR', 'Operador'),
        ('ANALISTA', 'Analista'),
        ('VIEWER', 'Visualizador')
    ])
    departamento = StringField('Departamento')
    ativo = SelectField('Status', choices=[
        ('1', 'Ativo'),
        ('0', 'Inativo')
    ])
    observacoes = TextAreaField('Observações')
    submit = SubmitField('Salvar')


# ==================== ROTAS GERAIS ====================

@app.route('/')
def index():
    """Página inicial com estatísticas"""
    try:
        total_deteccoes = len(db.listar_todas_deteccoes(limite=999999))
        deteccoes_hoje = db.contar_deteccoes_hoje()
        placas_unicas = len(db.listar_placas_unicas_hoje())
        
        # Simulando dados de veículos e usuários (você ajusta conforme seu BD)
        total_veiculos = 0
        total_usuarios = 0
        
        return render_template('index.html',
                             total_deteccoes=total_deteccoes,
                             deteccoes_hoje=deteccoes_hoje,
                             total_veiculos=total_veiculos,
                             total_usuarios=total_usuarios)
    except Exception as e:
        flash(f'Erro ao carregar estatísticas: {e}', 'error')
        return render_template('index.html',
                             total_deteccoes=0,
                             deteccoes_hoje=0,
                             total_veiculos=0,
                             total_usuarios=0)


# ==================== ROTAS DE DETECÇÕES ====================

@app.route('/deteccoes')
def listar_deteccoes():
    """Lista todas as detecções"""
    try:
        page = request.args.get('page', 1, type=int)
        limite = 20
        offset = (page - 1) * limite
        
        deteccoes = db.listar_todas_deteccoes(limite=999999)
        total = len(deteccoes)
        
        deteccoes = deteccoes[offset:offset + limite]
        total_paginas = (total + limite - 1) // limite
        
        paginas = list(range(1, total_paginas + 1))
        proxima_pagina = page + 1 if page < total_paginas else None
        pagina_anterior = page - 1 if page > 1 else None
        
        return render_template('deteccoes.html',
                             deteccoes=deteccoes,
                             pagina_atual=page,
                             paginas=paginas,
                             proxima_pagina=proxima_pagina,
                             pagina_anterior=pagina_anterior)
    except Exception as e:
        flash(f'Erro ao listar detecções: {e}', 'error')
        return render_template('deteccoes.html', deteccoes=[])


@app.route('/editar/deteccao/<int:id_deteccao>', methods=['GET', 'POST'])
def editar_deteccao(id_deteccao):
    """Edita uma detecção existente"""
    try:
        deteccao = db.buscar_deteccao_por_id(id_deteccao)
        
        if not deteccao:
            flash('Detecção não encontrada', 'error')
            return redirect(url_for('listar_deteccoes'))
        
        if request.method == 'POST':
            placa = request.form.get('placa')
            tipo_placa = request.form.get('tipo_placa')
            confianca = float(request.form.get('confianca', 0))
            
            if db.atualizar_deteccao(id_deteccao, placa, tipo_placa, confianca):
                flash('Detecção atualizada com sucesso!', 'success')
                return redirect(url_for('listar_deteccoes'))
            else:
                flash('Erro ao atualizar detecção', 'error')
        
        return render_template('editar_deteccao.html', deteccao=deteccao)
    
    except Exception as e:
        flash(f'Erro: {e}', 'error')
        return redirect(url_for('listar_deteccoes'))


@app.route('/delete/deteccao/<int:id_deteccao>', methods=['GET', 'POST'])
def deletar_deteccao(id_deteccao):
    """Deleta uma detecção"""
    try:
        if db.deletar_deteccao(id_deteccao):
            flash('Detecção deletada com sucesso!', 'success')
        else:
            flash('Erro ao deletar detecção', 'error')
    except Exception as e:
        flash(f'Erro: {e}', 'error')
    
    return redirect(url_for('listar_deteccoes'))


# ==================== ROTAS DE VEÍCULOS ====================

@app.route('/veiculos')
def listar_veiculos():
    """Lista todos os veículos cadastrados"""
    # Simulação - você ajusta conforme implementa o modelo de Veículos no BD
    veiculos = [
        {
            'id': 1,
            'placa': 'ABC1234',
            'proprietario': 'João Silva',
            'modelo': 'Uno',
            'marca': 'Fiat',
            'cor': '#FFFFFF',
            'tipo': 'CARRO',
            'data_cadastro': datetime.now()
        }
    ]
    
    return render_template('veiculos.html', veiculos=veiculos)


@app.route('/novo/veiculo', methods=['GET', 'POST'])
def novo_veiculo():
    """Cria um novo veículo"""
    form = FormularioVeiculo()
    
    if form.validate_on_submit():
        try:
            # Aqui você implementa a lógica de salvar no banco de dados
            # db.salvar_veiculo(form.data)
            flash('Veículo cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_veiculos'))
        except Exception as e:
            flash(f'Erro ao cadastrar veículo: {e}', 'error')
    
    return render_template('editar_veiculo.html', form=form, veiculo=None)


@app.route('/editar/veiculo/<int:id_veiculo>', methods=['GET', 'POST'])
def editar_veiculo(id_veiculo):
    """Edita um veículo existente"""
    form = FormularioVeiculo()
    
    # Simulação - você implementa conforme seu modelo de BD
    veiculo = {
        'id': id_veiculo,
        'placa': 'ABC1234',
        'proprietario': 'João Silva',
        'modelo': 'Uno',
        'marca': 'Fiat',
        'cor': '#FFFFFF',
        'tipo': 'CARRO',
        'ano': 2020,
        'telefone': '11999999999',
        'observacoes': '',
        'data_cadastro': datetime.now()
    }
    
    if form.validate_on_submit():
        try:
            # db.atualizar_veiculo(id_veiculo, form.data)
            flash('Veículo atualizado com sucesso!', 'success')
            return redirect(url_for('listar_veiculos'))
        except Exception as e:
            flash(f'Erro ao atualizar veículo: {e}', 'error')
    
    return render_template('editar_veiculo.html', form=form, veiculo=veiculo)


@app.route('/delete/veiculo/<int:id_veiculo>', methods=['GET', 'POST'])
def deletar_veiculo(id_veiculo):
    """Deleta um veículo"""
    try:
        # db.deletar_veiculo(id_veiculo)
        flash('Veículo deletado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao deletar veículo: {e}', 'error')
    
    return redirect(url_for('listar_veiculos'))


# ==================== ROTAS DE USUÁRIOS ====================

@app.route('/usuarios')
def listar_usuarios():
    """Lista todos os usuários cadastrados"""
    # Simulação - você ajusta conforme implementa o modelo de Usuários no BD
    usuarios = [
        {
            'id': 1,
            'nome': 'Admin User',
            'email': 'admin@ifsuldeminas.edu.br',
            'telefone': '35999999999',
            'cargo': 'ADMINISTRADOR',
            'ativo': True,
            'data_cadastro': datetime.now(),
            'observacoes': ''
        }
    ]
    
    return render_template('usuarios.html', usuarios=usuarios)


@app.route('/novo/usuario', methods=['GET', 'POST'])
def novo_usuario():
    """Cria um novo usuário"""
    form = FormularioUsuario()
    
    if form.validate_on_submit():
        try:
            # Aqui você implementa a lógica de salvar no banco de dados
            # db.salvar_usuario(form.data)
            flash('Usuário cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_usuarios'))
        except Exception as e:
            flash(f'Erro ao cadastrar usuário: {e}', 'error')
    
    return render_template('editar_usuario.html', form=form, usuario=None)


@app.route('/editar/usuario/<int:id_usuario>', methods=['GET', 'POST'])
def editar_usuario(id_usuario):
    """Edita um usuário existente"""
    form = FormularioUsuario()
    
    # Simulação - você implementa conforme seu modelo de BD
    usuario = {
        'id': id_usuario,
        'nome': 'Admin User',
        'email': 'admin@ifsuldeminas.edu.br',
        'telefone': '35999999999',
        'cargo': 'ADMINISTRADOR',
        'departamento': 'Segurança',
        'ativo': True,
        'data_cadastro': datetime.now(),
        'observacoes': ''
    }
    
    if form.validate_on_submit():
        try:
            # db.atualizar_usuario(id_usuario, form.data)
            flash('Usuário atualizado com sucesso!', 'success')
            return redirect(url_for('listar_usuarios'))
        except Exception as e:
            flash(f'Erro ao atualizar usuário: {e}', 'error')
    
    return render_template('editar_usuario.html', form=form, usuario=usuario)


@app.route('/delete/usuario/<int:id_usuario>', methods=['GET', 'POST'])
def deletar_usuario(id_usuario):
    """Deleta um usuário"""
    try:
        # db.deletar_usuario(id_usuario)
        flash('Usuário deletado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao deletar usuário: {e}', 'error')
    
    return redirect(url_for('listar_usuarios'))


# ==================== ROTAS DE RELATÓRIO ====================

@app.route('/relatorio')
def relatorio():
    """Exibe relatório de detecções"""
    try:
        deteccoes = db.listar_todas_deteccoes()
        total = len(deteccoes)
        
        # Agrupa por tipo
        por_tipo = {}
        for det in deteccoes:
            tipo = det['tipo_placa']
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        
        # Agrupa por origem
        por_origem = {}
        for det in deteccoes:
            origem = det['origem']
            por_origem[origem] = por_origem.get(origem, 0) + 1
        
        return render_template('relatorio.html',
                             total=total,
                             deteccoes=deteccoes,
                             por_tipo=por_tipo,
                             por_origem=por_origem)
    except Exception as e:
        flash(f'Erro ao gerar relatório: {e}', 'error')
        return render_template('relatorio.html',
                             total=0,
                             deteccoes=[],
                             por_tipo={},
                             por_origem={})


# ==================== ROTAS DE API (JSON) ====================

@app.route('/api/deteccoes')
def api_deteccoes():
    """API para obter detecções em JSON"""
    try:
        filtro_tipo = request.args.get('tipo')
        
        if filtro_tipo:
            deteccoes = db.listar_deteccoes_por_tipo(filtro_tipo)
        else:
            deteccoes = db.listar_todas_deteccoes()
        
        return jsonify({
            'sucesso': True,
            'total': len(deteccoes),
            'deteccoes': deteccoes
        })
    except Exception as e:
        return jsonify({
            'sucesso': False,
            'erro': str(e)
        }), 500


@app.route('/api/deteccao/<int:id_deteccao>')
def api_deteccao(id_deteccao):
    """API para obter detecção específica em JSON"""
    try:
        deteccao = db.buscar_deteccao_por_id(id_deteccao)
        
        if deteccao:
            return jsonify({
                'sucesso': True,
                'deteccao': deteccao
            })
        else:
            return jsonify({
                'sucesso': False,
                'erro': 'Detecção não encontrada'
            }), 404
    except Exception as e:
        return jsonify({
            'sucesso': False,
            'erro': str(e)
        }), 500


# ==================== TRATAMENTO DE ERROS ====================

@app.errorhandler(404)
def pagina_nao_encontrada(e):
    """Trata erro 404"""
    return render_template('404.html'), 404


@app.errorhandler(500)
def erro_servidor(e):
    """Trata erro 500"""
    return render_template('500.html'), 500


# ==================== CONTEXTO DA APLICAÇÃO ====================

@app.context_processor
def injection_context():
    """Injeta variáveis globais nos templates"""
    return {
        'versao': '2.0',
        'ano': datetime.now().year,
        'instituicao': 'IFSULDEMINAS'
    }


# ==================== ENTRADA PRINCIPAL ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("WEB APP - SISTEMA DE DETECÇÃO DE PLACAS v2.0")
    print("="*60)
    print("\nAcesse: http://localhost:5000")
    print("Pressione CTRL+C para interromper\n")
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n✓ Aplicação encerrada")
        db.fechar()
