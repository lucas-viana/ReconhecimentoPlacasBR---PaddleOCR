"""
Sistema Web de Reconhecimento de Placas
Detecta placas em tempo real e salva capturas de placas desconhecidas
"""

import paddle
from paddleocr import PaddleOCR
import cv2
import numpy as np
import re
from datetime import datetime
import psycopg2
import os
import threading
from flask import Flask, Response, render_template_string, request, redirect, url_for
import glob

# --- CONFIGURAÇÕES ---
USAR_WEBCAM = False  # True para webcam, False para arquivo de vídeo
ARQUIVO_VIDEO = "video_entrada.mp4"
INDICE_CAMERA = 0  # Índice da webcam (0 = primeira câmera)

# Configuração do Banco de Dados PostgreSQL
POSTGRES_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'ifsuldeminas',
    'user': 'postgres',
    'password': '353742Ap$'
}

# OCR e Processamento
PROCESSAR_A_CADA_N_FRAMES = 1  # Processar 1 a cada 2 frames
CONFIANCA_MINIMA = 0.94
CONFIANCA_MINIMA_MOTO = 0.97
COOLDOWN_SEGUNDOS = 120  # Tempo para não salvar a mesma placa novamente

# Pastas para salvar imagens
PASTA_PLACAS_DESCONHECIDAS = "placas_desconhecidas"
PASTA_PLACAS_CONHECIDAS = "placas_conhecidas"
# --------------------

# Cria pastas se não existirem
os.makedirs(PASTA_PLACAS_DESCONHECIDAS, exist_ok=True)
os.makedirs(PASTA_PLACAS_CONHECIDAS, exist_ok=True)

# Padrões de placas brasileiras
PADRAO_MERCOSUL_CARRO = re.compile(r'^[A-Z]{3}\d[A-Z]\d{2}$')
PADRAO_MERCOSUL_MOTO = re.compile(r'^[A-Z]{3}\d[A-Z]\d{2}$')
PADRAO_ANTIGO_CARRO = re.compile(r'^[A-Z]{3}\d{4}$')
PADRAO_ANTIGO_MOTO = re.compile(r'^[A-Z]{3}\d{4}$')

# --- INICIALIZAÇÃO DO SERVIDOR WEB (Flask) ---
app = Flask(__name__)

# Variáveis globais
ocr = None
conn_db = None
placas_cache = {}  # Cache de placas já processadas
frame_atual = None
ultima_deteccao = None


class GerenciadorBanco:
    """Gerencia conexão e operações com PostgreSQL"""
    
    def __init__(self):
        self.conn = None
        self.conectar()
        self.criar_tabelas()
    
    def conectar(self):
        """Estabelece conexão com o banco de dados"""
        try:
            self.conn = psycopg2.connect(**POSTGRES_CONFIG)
            print(f"✓ Conectado ao PostgreSQL: {POSTGRES_CONFIG['database']}")
        except Exception as e:
            print(f"❌ Erro ao conectar no banco: {e}")
            print("⚠️  A aplicação funcionará sem banco de dados")
            self.conn = None
    
    def criar_tabelas(self):
        """Cria todas as tabelas necessárias"""
        if not self.conn:
            return
        
        cursor = self.conn.cursor()
        
        # Tabela de usuários
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                cpf VARCHAR(14) UNIQUE,
                telefone VARCHAR(20),
                tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('PARTICULAR', 'OFICIAL')),
                autorizado BOOLEAN DEFAULT TRUE,
                observacoes TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de veículos vinculados a usuários
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS veiculos (
                id SERIAL PRIMARY KEY,
                placa VARCHAR(10) UNIQUE NOT NULL,
                tipo_placa VARCHAR(20) NOT NULL,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                modelo VARCHAR(100),
                cor VARCHAR(50),
                tipo_veiculo VARCHAR(20) CHECK (tipo_veiculo IN ('CARRO', 'MOTO', 'CAMINHAO', 'OUTRO')),
                marcado BOOLEAN DEFAULT FALSE,
                motivo_marcacao TEXT,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de acessos (log de entradas/saídas)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS acessos (
                id SERIAL PRIMARY KEY,
                veiculo_id INTEGER REFERENCES veiculos(id) ON DELETE CASCADE,
                placa VARCHAR(10) NOT NULL,
                tipo_evento VARCHAR(20) CHECK (tipo_evento IN ('ENTRADA', 'SAIDA', 'DETECTADO')),
                confianca DECIMAL(5, 4),
                imagem_path VARCHAR(255),
                data_acesso TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabela de alertas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alertas (
                id SERIAL PRIMARY KEY,
                veiculo_id INTEGER REFERENCES veiculos(id) ON DELETE CASCADE,
                placa VARCHAR(10) NOT NULL,
                tipo_alerta VARCHAR(50) NOT NULL,
                mensagem TEXT NOT NULL,
                resolvido BOOLEAN DEFAULT FALSE,
                data_alerta TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Índices para otimização
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_veiculos_placa ON veiculos(placa)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_acessos_data ON acessos(data_acesso)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alertas_resolvido ON alertas(resolvido)")
        
        self.conn.commit()
        print("✓ Tabelas criadas/verificadas")
    
    def placa_existe(self, placa: str) -> bool:
        """Verifica se uma placa existe no banco de dados"""
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM veiculos
                WHERE placa = %s
            """, (placa,))
            
            count = cursor.fetchone()[0]
            return count > 0
        except Exception as e:
            print(f"❌ Erro ao consultar banco: {e}")
            return False
    
    def buscar_veiculo(self, placa: str):
        """Busca informações completas de um veículo"""
        if not self.conn:
            return None
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT v.id, v.placa, v.tipo_placa, v.modelo, v.cor, v.tipo_veiculo,
                       v.marcado, v.motivo_marcacao,
                       u.id, u.nome, u.cpf, u.telefone, u.tipo, u.autorizado
                FROM veiculos v
                LEFT JOIN usuarios u ON v.usuario_id = u.id
                WHERE v.placa = %s
            """, (placa,))
            
            resultado = cursor.fetchone()
            
            if resultado:
                return {
                    'veiculo_id': resultado[0],
                    'placa': resultado[1],
                    'tipo_placa': resultado[2],
                    'modelo': resultado[3],
                    'cor': resultado[4],
                    'tipo_veiculo': resultado[5],
                    'marcado': resultado[6],
                    'motivo_marcacao': resultado[7],
                    'usuario_id': resultado[8],
                    'usuario_nome': resultado[9],
                    'usuario_cpf': resultado[10],
                    'usuario_telefone': resultado[11],
                    'usuario_tipo': resultado[12],
                    'usuario_autorizado': resultado[13]
                }
            return None
        except Exception as e:
            print(f"❌ Erro ao buscar veículo: {e}")
            return None
    
    def registrar_acesso(self, placa: str, confianca: float, imagem_path: str = None) -> bool:
        """Registra um acesso (detecção) de veículo"""
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            
            # Busca o veiculo_id se existir
            cursor.execute("SELECT id FROM veiculos WHERE placa = %s", (placa,))
            resultado = cursor.fetchone()
            veiculo_id = resultado[0] if resultado else None
            
            cursor.execute("""
                INSERT INTO acessos 
                (veiculo_id, placa, tipo_evento, confianca, imagem_path)
                VALUES (%s, %s, %s, %s, %s)
            """, (veiculo_id, placa, 'DETECTADO', confianca, imagem_path))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao registrar acesso: {e}")
            self.conn.rollback()
            return False
    
    def cadastrar_usuario(self, nome: str, cpf: str, telefone: str, tipo: str, autorizado: bool = True) -> int:
        """Cadastra um novo usuário"""
        if not self.conn:
            return None
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO usuarios (nome, cpf, telefone, tipo, autorizado)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (nome, cpf, telefone, tipo, autorizado))
            
            usuario_id = cursor.fetchone()[0]
            self.conn.commit()
            return usuario_id
        except Exception as e:
            print(f"❌ Erro ao cadastrar usuário: {e}")
            self.conn.rollback()
            return None
    
    def cadastrar_veiculo(self, placa: str, tipo_placa: str, usuario_id: int, 
                         modelo: str = None, cor: str = None, tipo_veiculo: str = 'CARRO') -> bool:
        """Cadastra um novo veículo vinculado a um usuário"""
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO veiculos 
                (placa, tipo_placa, usuario_id, modelo, cor, tipo_veiculo)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (placa, tipo_placa, usuario_id, modelo, cor, tipo_veiculo))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao cadastrar veículo: {e}")
            self.conn.rollback()
            return False
    
    def marcar_veiculo(self, placa: str, motivo: str) -> bool:
        """Marca um veículo para controle específico"""
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE veiculos 
                SET marcado = TRUE, motivo_marcacao = %s
                WHERE placa = %s
            """, (motivo, placa))
            
            # Cria alerta
            cursor.execute("""
                INSERT INTO alertas (veiculo_id, placa, tipo_alerta, mensagem)
                SELECT id, placa, 'VEICULO_MARCADO', %s
                FROM veiculos WHERE placa = %s
            """, (motivo, placa))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao marcar veículo: {e}")
            self.conn.rollback()
            return False
    
    def gerar_alerta(self, placa: str, tipo_alerta: str, mensagem: str) -> bool:
        """Gera um alerta para um veículo"""
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO alertas (veiculo_id, placa, tipo_alerta, mensagem)
                SELECT id, %s, %s, %s FROM veiculos WHERE placa = %s
            """, (placa, tipo_alerta, mensagem, placa))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao gerar alerta: {e}")
            self.conn.rollback()
            return False
    
    def listar_veiculos(self, limite=100):
        """Lista todos os veículos cadastrados"""
        if not self.conn:
            return []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT v.id, v.placa, v.tipo_placa, v.modelo, v.cor, v.tipo_veiculo,
                       v.marcado, u.nome, u.tipo, u.autorizado, v.data_cadastro
                FROM veiculos v
                LEFT JOIN usuarios u ON v.usuario_id = u.id
                ORDER BY v.data_cadastro DESC
                LIMIT %s
            """, (limite,))
            
            return [{
                'id': row[0],
                'placa': row[1],
                'tipo_placa': row[2],
                'modelo': row[3],
                'cor': row[4],
                'tipo_veiculo': row[5],
                'marcado': row[6],
                'usuario_nome': row[7],
                'usuario_tipo': row[8],
                'usuario_autorizado': row[9],
                'data_cadastro': row[10]
            } for row in cursor.fetchall()]
        except Exception as e:
            print(f"❌ Erro ao listar veículos: {e}")
            return []
    
    def listar_usuarios(self, limite=100):
        """Lista todos os usuários"""
        if not self.conn:
            return []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, nome, cpf, telefone, tipo, autorizado, data_cadastro
                FROM usuarios
                ORDER BY nome
                LIMIT %s
            """, (limite,))
            
            return [{
                'id': row[0],
                'nome': row[1],
                'cpf': row[2],
                'telefone': row[3],
                'tipo': row[4],
                'autorizado': row[5],
                'data_cadastro': row[6]
            } for row in cursor.fetchall()]
        except Exception as e:
            print(f"❌ Erro ao listar usuários: {e}")
            return []
    
    def listar_alertas(self, apenas_nao_resolvidos=True, limite=50):
        """Lista alertas do sistema"""
        if not self.conn:
            return []
        
        try:
            cursor = self.conn.cursor()
            
            query = """
                SELECT a.id, a.placa, a.tipo_alerta, a.mensagem, 
                       a.resolvido, a.data_alerta, v.modelo, u.nome
                FROM alertas a
                LEFT JOIN veiculos v ON a.veiculo_id = v.id
                LEFT JOIN usuarios u ON v.usuario_id = u.id
            """
            
            if apenas_nao_resolvidos:
                query += " WHERE a.resolvido = FALSE"
            
            query += " ORDER BY a.data_alerta DESC LIMIT %s"
            
            cursor.execute(query, (limite,))
            
            return [{
                'id': row[0],
                'placa': row[1],
                'tipo_alerta': row[2],
                'mensagem': row[3],
                'resolvido': row[4],
                'data_alerta': row[5],
                'modelo': row[6],
                'usuario_nome': row[7]
            } for row in cursor.fetchall()]
        except Exception as e:
            print(f"❌ Erro ao listar alertas: {e}")
            return []
    
    def listar_acessos_recentes(self, limite=50):
        """Lista acessos recentes"""
        if not self.conn:
            return []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT a.placa, a.tipo_evento, a.confianca, a.data_acesso,
                       v.modelo, u.nome, u.tipo
                FROM acessos a
                LEFT JOIN veiculos v ON a.veiculo_id = v.id
                LEFT JOIN usuarios u ON v.usuario_id = u.id
                ORDER BY a.data_acesso DESC
                LIMIT %s
            """, (limite,))
            
            return [{
                'placa': row[0],
                'tipo_evento': row[1],
                'confianca': float(row[2]) if row[2] else 0,
                'data_acesso': row[3],
                'modelo': row[4],
                'usuario_nome': row[5],
                'usuario_tipo': row[6]
            } for row in cursor.fetchall()]
        except Exception as e:
            print(f"❌ Erro ao listar acessos: {e}")
            return []
    
    def fechar(self):
        """Fecha conexão com o banco"""
        if self.conn:
            self.conn.close()
            print("✓ Conexão com banco fechada")


def inicializar_ocr():
    """Inicializa o modelo OCR"""
    global ocr
    print("\nCarregando modelo OCR...")
    
    gpu_disponivel = paddle.device.is_compiled_with_cuda()
    
    if gpu_disponivel:
        try:
            paddle.set_device('gpu')
            print("✓ GPU ATIVADA (CUDA)")
        except:
            paddle.set_device('cpu')
            print("⚠ Usando CPU")
    else:
        paddle.set_device('cpu')
        print("⚠ Usando CPU (CUDA não disponível)")
    
    ocr = PaddleOCR(use_angle_cls=True, lang='en')
    print("✓ Modelo OCR carregado")


def validar_placa(texto: str, eh_combinacao: bool = False):
    """
    Valida se o texto é uma placa brasileira válida
    
    Returns:
        (placa, tipo) ou (None, None)
    """
    texto_limpo = texto.upper()
    texto_limpo = re.sub(r'[^A-Z0-9]', '', texto_limpo)
    
    texto_corrigido = texto_limpo.replace('O', '0').replace('I', '1').replace('S', '5')
    
    for texto_teste in [texto_limpo, texto_corrigido]:
        if PADRAO_MERCOSUL_CARRO.match(texto_teste):
            return texto_teste, "MERCOSUL_MOTO" if eh_combinacao else "MERCOSUL_CARRO"
        elif PADRAO_ANTIGO_CARRO.match(texto_teste):
            return texto_teste, "ANTIGA_MOTO" if eh_combinacao else "ANTIGA_CARRO"
    
    return None, None


def pode_processar_placa(placa: str) -> bool:
    """Verifica se pode processar a placa (cooldown)"""
    if placa in placas_cache:
        tempo_decorrido = (datetime.now() - placas_cache[placa]).seconds
        if tempo_decorrido < COOLDOWN_SEGUNDOS:
            return False
    
    return True


def salvar_imagem_placa(frame, coords, placa, eh_conhecida=False):
    """Salva imagem da placa detectada"""
    try:
        # Define a pasta de destino
        pasta = PASTA_PLACAS_CONHECIDAS if eh_conhecida else PASTA_PLACAS_DESCONHECIDAS
        
        # Extrai a região da placa
        pts = np.array(coords, np.int32)
        x, y, w, h = cv2.boundingRect(pts)
        
        # Adiciona margem de 10px
        margem = 10
        x = max(0, x - margem)
        y = max(0, y - margem)
        w = min(frame.shape[1] - x, w + 2*margem)
        h = min(frame.shape[0] - y, h + 2*margem)
        
        placa_recortada = frame[y:y+h, x:x+w]
        
        # Nome do arquivo com timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nome_arquivo = f"{placa}_{timestamp}.jpg"
        caminho_arquivo = os.path.join(pasta, nome_arquivo)
        
        # Salva a imagem
        cv2.imwrite(caminho_arquivo, placa_recortada)
        
        print(f"{'✓' if eh_conhecida else '📸'} Imagem salva: {caminho_arquivo}")
        return caminho_arquivo
    
    except Exception as e:
        print(f"❌ Erro ao salvar imagem: {e}")
        return None


def generate_frames():
    """
    Loop principal de captura e processamento de vídeo
    """
    global frame_atual, ultima_deteccao, conn_db, placas_cache
    
    print("\nIniciando captura de vídeo...")
    
    if USAR_WEBCAM:
        cap = cv2.VideoCapture(INDICE_CAMERA)
        print(f"📹 Usando WEBCAM (índice {INDICE_CAMERA})")
    else:
        cap = cv2.VideoCapture(ARQUIVO_VIDEO)
        print(f"📹 Processando vídeo: {ARQUIVO_VIDEO}")
    
    if not cap.isOpened():
        print("❌ ERRO: Não foi possível abrir câmera/vídeo")
        return
    
    print("✓ Câmera/vídeo conectado. Stream pronto em /video_feed")
    
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            print("Erro ao receber frame, tentando reconectar...")
            cap.release()
            if USAR_WEBCAM:
                cap = cv2.VideoCapture(INDICE_CAMERA)
            else:
                cap = cv2.VideoCapture(ARQUIVO_VIDEO)
            continue
        
        frame_count += 1
        frame_atual = frame.copy()
        deteccoes = []
        
        # Processa apenas a cada N frames
        if frame_count % PROCESSAR_A_CADA_N_FRAMES == 0:
            try:
                resultado = ocr.ocr(frame, cls=True)
                
                if resultado and resultado[0]:
                    textos_detectados = []
                    
                    for linha in resultado[0]:
                        coords = linha[0]
                        texto = linha[1][0]
                        confianca = linha[1][1]
                        
                        if confianca >= CONFIANCA_MINIMA:
                            textos_detectados.append({
                                'texto': texto,
                                'coords': coords,
                                'confianca': confianca
                            })
                    
                    # Valida placas individuais (carros)
                    for item in textos_detectados:
                        placa, tipo = validar_placa(item['texto'], eh_combinacao=False)
                        
                        if placa:
                            # Busca informações do veículo (SEMPRE busca para exibir)
                            veiculo = conn_db.buscar_veiculo(placa)
                            placa_conhecida = veiculo is not None
                            
                            # Verifica se deve SALVAR/REGISTRAR (com cooldown)
                            deve_registrar = pode_processar_placa(placa)
                            
                            if deve_registrar:
                                # Salva imagem
                                caminho_img = salvar_imagem_placa(
                                    frame, item['coords'], placa, placa_conhecida
                                )
                                
                                # Atualiza cache
                                placas_cache[placa] = datetime.now()
                                
                                # Registra acesso
                                conn_db.registrar_acesso(placa, item['confianca'], caminho_img)
                                
                                # Verifica alertas se for veículo conhecido
                                if veiculo:
                                    # Verifica se está marcado
                                    if veiculo.get('marcado'):
                                        conn_db.gerar_alerta(placa, 'VEICULO_MARCADO', 
                                                            f"Veículo marcado detectado: {veiculo.get('motivo_marcacao')}")
                                    
                                    # Verifica se usuário não está autorizado
                                    if not veiculo.get('usuario_autorizado'):
                                        conn_db.gerar_alerta(placa, 'NAO_AUTORIZADO', 
                                                            f"Veículo de usuário não autorizado: {veiculo.get('usuario_nome')}")
                                    
                                    print(f"✓ Veículo conhecido: {placa} - {veiculo.get('usuario_nome')} ({veiculo.get('usuario_tipo')})")
                                else:
                                    print(f"🆕 PLACA NOVA DETECTADA: {placa} ({tipo}) - {item['confianca']:.2%}")
                            
                            # SEMPRE adiciona às detecções para exibir no frame
                            deteccoes.append({
                                'placa': placa,
                                'tipo': tipo,
                                'confianca': item['confianca'],
                                'coordenadas': item['coords'],
                                'conhecida': placa_conhecida,
                                'imagem': None,
                                'veiculo': veiculo
                            })
                            
                            # Atualiza última detecção
                            ultima_deteccao = {
                                'placa': placa,
                                'tipo': tipo,
                                'confianca': item['confianca'],
                                'conhecida': placa_conhecida,
                                'veiculo': veiculo,
                                'timestamp': datetime.now()
                            }
                    
                    # Tenta combinar textos (motos)
                    for i, item1 in enumerate(textos_detectados):
                        for item2 in textos_detectados[i+1:]:
                            texto1 = re.sub(r'[^A-Z0-9]', '', item1['texto'].upper())
                            texto2 = re.sub(r'[^A-Z0-9]', '', item2['texto'].upper())
                            
                            combinado = texto1 + texto2
                            placa, tipo = validar_placa(combinado, eh_combinacao=True)
                            
                            if placa:
                                confianca_media = (item1['confianca'] + item2['confianca']) / 2
                                
                                if confianca_media >= CONFIANCA_MINIMA_MOTO:
                                    # Busca informações do veículo (SEMPRE busca para exibir)
                                    veiculo = conn_db.buscar_veiculo(placa)
                                    placa_conhecida = veiculo is not None
                                    
                                    # Verifica se deve SALVAR/REGISTRAR (com cooldown)
                                    deve_registrar = pode_processar_placa(placa)
                                    
                                    if deve_registrar:
                                        caminho_img = salvar_imagem_placa(
                                            frame, item1['coords'], placa, placa_conhecida
                                        )
                                        
                                        placas_cache[placa] = datetime.now()
                                        
                                        conn_db.registrar_acesso(placa, confianca_media, caminho_img)
                                        
                                        if veiculo:
                                            if veiculo.get('marcado'):
                                                conn_db.gerar_alerta(placa, 'VEICULO_MARCADO', 
                                                                    f"Veículo marcado: {veiculo.get('motivo_marcacao')}")
                                            
                                            if not veiculo.get('usuario_autorizado'):
                                                conn_db.gerar_alerta(placa, 'NAO_AUTORIZADO', 
                                                                    f"Usuário não autorizado: {veiculo.get('usuario_nome')}")
                                            
                                            print(f"✓ Moto conhecida: {placa} - {veiculo.get('usuario_nome')}")
                                        else:
                                            print(f"🆕 PLACA NOVA (MOTO): {placa} ({tipo}) - {confianca_media:.2%}")
                                    
                                    # SEMPRE adiciona às detecções para exibir no frame
                                    deteccoes.append({
                                        'placa': placa,
                                        'tipo': tipo,
                                        'confianca': confianca_media,
                                        'coordenadas': item1['coords'],
                                        'conhecida': placa_conhecida,
                                        'imagem': None,
                                        'veiculo': veiculo
                                    })
                                    
                                    ultima_deteccao = {
                                        'placa': placa,
                                        'tipo': tipo,
                                        'confianca': confianca_media,
                                        'conhecida': placa_conhecida,
                                        'veiculo': veiculo,
                                        'timestamp': datetime.now()
                                    }
                                    break
            
            except Exception as e:
                print(f"Erro na análise: {e}")
                pass
        
        # Desenha interface no frame
        frame_desenho = desenhar_interface(frame, deteccoes, frame_count)
        
        # Codifica para JPEG
        ret, buffer = cv2.imencode('.jpg', frame_desenho)
        if not ret:
            continue
        
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


def desenhar_interface(frame, deteccoes, frame_count):
    """Desenha interface no frame com informações detalhadas"""
    frame_desenho = frame.copy()
    altura, largura = frame.shape[:2]
    
    # Barra superior com fundo semitransparente
    overlay = frame_desenho.copy()
    cv2.rectangle(overlay, (0, 0), (largura, 90), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, frame_desenho, 0.3, 0, frame_desenho)
    
    # Título
    titulo = "SISTEMA DE RECONHECIMENTO DE PLACAS - IFSULDEMINAS"
    cv2.putText(frame_desenho, titulo, (10, 30),
               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    # Informações adicionais
    info = f"Frame: {frame_count} | Deteccoes: {len(deteccoes)}"
    cv2.putText(frame_desenho, info, (10, 60),
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    # Legenda de cores
    legenda_y = 75
    cv2.putText(frame_desenho, "Verde: Autorizado | Vermelho: Nao Cadastrado/Nao Autorizado | Laranja: Marcado", 
               (10, legenda_y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    
    # Desenha cada detecção
    for det in deteccoes:
        coords = det['coordenadas']
        placa = det['placa']
        tipo = det['tipo']
        confianca = det['confianca']
        conhecida = det['conhecida']
        veiculo = det.get('veiculo')
        
        # Define cor e status baseado no veículo
        if conhecida and veiculo:
            if veiculo.get('marcado'):
                cor = (0, 165, 255)  # Laranja para marcados (BGR)
                status = "MARCADO"
            elif not veiculo.get('usuario_autorizado'):
                cor = (0, 0, 255)  # Vermelho para não autorizados
                status = "NAO AUTORIZADO"
            else:
                cor = (0, 255, 0)  # Verde para autorizados
                status = "AUTORIZADO"
        else:
            cor = (0, 0, 255)  # Vermelho para desconhecidos
            status = "NAO CADASTRADO"
        
        # Desenha caixa ao redor da placa com bordas mais grossas
        pts = np.array(coords, np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame_desenho, [pts], True, cor, 4)
        
        # Calcula posição para o texto
        x, y = int(coords[0][0]), int(coords[0][1])
        
        # Prepara as linhas de texto
        if conhecida and veiculo:
            usuario_nome = veiculo.get('usuario_nome', 'Sem Proprietario')
            usuario_tipo = veiculo.get('usuario_tipo', '')
            modelo = veiculo.get('modelo', '')
            
            # Linha 1: Nome do usuário
            linha1 = f"{usuario_nome}"
            # Linha 2: Placa e tipo de usuário
            linha2 = f"{placa} - {usuario_tipo}"
            # Linha 3: Status e modelo (se houver)
            if modelo:
                linha3 = f"{status} | {modelo}"
            else:
                linha3 = status
        else:
            # Para placas desconhecidas
            linha1 = f"PLACA: {placa}"
            linha2 = f"{status}"
            linha3 = f"Confianca: {confianca:.0%}"
        
        # Calcula tamanho do fundo necessário
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2
        
        (w1, h1), _ = cv2.getTextSize(linha1, font, font_scale, thickness)
        (w2, h2), _ = cv2.getTextSize(linha2, font, font_scale, thickness)
        (w3, h3), _ = cv2.getTextSize(linha3, font, font_scale - 0.1, thickness - 1)
        
        max_width = max(w1, w2, w3)
        total_height = h1 + h2 + h3 + 30  # Espaçamento entre linhas
        
        # Ajusta posição se estiver muito em cima
        if y - total_height - 10 < 0:
            y_text = y + int(coords[2][1]) + 10  # Desenha embaixo
        else:
            y_text = y - 10  # Desenha em cima
        
        # Desenha fundo semitransparente para o texto
        overlay = frame_desenho.copy()
        cv2.rectangle(overlay, 
                     (x - 5, y_text - total_height - 5), 
                     (x + max_width + 10, y_text + 5), 
                     cor, -1)
        cv2.addWeighted(overlay, 0.85, frame_desenho, 0.15, 0, frame_desenho)
        
        # Desenha borda do fundo
        cv2.rectangle(frame_desenho, 
                     (x - 5, y_text - total_height - 5), 
                     (x + max_width + 10, y_text + 5), 
                     cor, 2)
        
        # Desenha os textos em branco
        y_offset = y_text - total_height + h1
        cv2.putText(frame_desenho, linha1, (x, y_offset),
                   font, font_scale, (255, 255, 255), thickness)
        
        y_offset += h2 + 5
        cv2.putText(frame_desenho, linha2, (x, y_offset),
                   font, font_scale, (255, 255, 255), thickness)
        
        y_offset += h3 + 5
        cv2.putText(frame_desenho, linha3, (x, y_offset),
                   font, font_scale - 0.1, (255, 255, 255), thickness - 1)
    
    return frame_desenho


# --- ROTAS FLASK ---

@app.route('/')
def index():
    """Página principal - Dashboard"""
    veiculos = conn_db.listar_veiculos(100)
    alertas = conn_db.listar_alertas(apenas_nao_resolvidos=True, limite=10)
    acessos = conn_db.listar_acessos_recentes(limite=20)
    
    # Lista imagens de placas desconhecidas
    imagens_desconhecidas = sorted(
        glob.glob(os.path.join(PASTA_PLACAS_DESCONHECIDAS, "*.jpg")),
        key=os.path.getmtime,
        reverse=True
    )[:20]  # Últimas 20
    
    html_page = """
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Sistema de Reconhecimento de Placas - IFSULDEMINAS</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
                background-color: #f4f7f6; 
                color: #333; 
            }
            .navbar {
                background-color: #1a1a1a;
                padding: 15px 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .navbar h1 {
                color: #fff;
                font-size: 1.5em;
                display: inline-block;
            }
            .navbar a {
                color: #fff;
                text-decoration: none;
                padding: 10px 15px;
                margin-left: 20px;
                border-radius: 5px;
                display: inline-block;
            }
            .navbar a:hover { background-color: #333; }
            .navbar .btn-primary { background-color: #007bff; }
            .navbar .btn-primary:hover { background-color: #0056b3; }
            
            .container { 
                max-width: 1400px; 
                margin: 20px auto; 
                padding: 20px; 
            }
            
            .alert-banner {
                background-color: #dc3545;
                color: white;
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            .alert-banner.warning { background-color: #ffc107; color: #000; }
            
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            .stat-card {
                background: white;
                padding: 25px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                text-align: center;
            }
            .stat-number {
                font-size: 2.5em;
                font-weight: bold;
                color: #007bff;
            }
            .stat-number.danger { color: #dc3545; }
            .stat-number.warning { color: #ffc107; }
            .stat-number.success { color: #28a745; }
            .stat-label {
                color: #666;
                margin-top: 8px;
                font-size: 0.95em;
            }
            
            .section {
                background: white;
                padding: 25px;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }
            h2 { 
                color: #1a1a1a; 
                margin-bottom: 20px;
                padding-bottom: 10px;
                border-bottom: 2px solid #007bff;
            }
            
            .images-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            .image-card {
                border: 2px solid #eee;
                border-radius: 8px;
                overflow: hidden;
                transition: all 0.3s;
                cursor: pointer;
            }
            .image-card:hover {
                transform: translateY(-5px);
                border-color: #007bff;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            .image-card img {
                width: 100%;
                height: 160px;
                object-fit: cover;
                background-color: #f0f0f0;
            }
            .image-info {
                padding: 12px;
                background: #f8f9fa;
            }
            .image-placa {
                font-weight: bold;
                font-size: 1.1em;
                color: #007bff;
                font-family: monospace;
            }
            .image-timestamp {
                font-size: 0.85em;
                color: #666;
                margin-top: 5px;
            }
            .btn-cadastrar {
                display: block;
                width: 100%;
                padding: 8px;
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin-top: 10px;
                font-weight: bold;
            }
            .btn-cadastrar:hover { background-color: #218838; }
            
            table { 
                width: 100%; 
                border-collapse: collapse; 
                margin: 20px 0;
            }
            th, td { 
                padding: 12px; 
                text-align: left; 
                border-bottom: 1px solid #eee; 
            }
            th { 
                background-color: #f8f9fa; 
                font-weight: 600;
            }
            tr:hover { background-color: #f8f9fa; }
            
            .badge {
                display: inline-block;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: 0.85em;
                font-weight: bold;
            }
            .badge-placa {
                background-color: #007bff;
                color: white;
                font-family: monospace;
                font-size: 1em;
            }
            .badge-oficial { background-color: #17a2b8; color: white; }
            .badge-particular { background-color: #6c757d; color: white; }
            .badge-marcado { background-color: #ffc107; color: #000; }
            .badge-autorizado { background-color: #28a745; color: white; }
            .badge-nao-autorizado { background-color: #dc3545; color: white; }
            
            .empty-state {
                text-align: center;
                padding: 40px;
                color: #999;
            }
        </style>
    </head>
    <body>
        <div class="navbar">
            <h1>🚗 Sistema de Controle de Acesso - IFSULDEMINAS</h1>
            <a href="{{ url_for('live_view') }}" class="btn-primary" target="_blank">📹 Visualização Ao Vivo</a>
            <a href="{{ url_for('cadastro_veiculo') }}">➕ Cadastrar Veículo</a>
            <a href="{{ url_for('listar_usuarios') }}">👥 Usuários</a>
        </div>
        
        <div class="container">
            {% if alertas|length > 0 %}
                {% for alerta in alertas[:3] %}
                <div class="alert-banner {% if alerta.tipo_alerta == 'VEICULO_MARCADO' %}warning{% endif %}">
                    <div>
                        <strong>⚠️ Alerta:</strong> {{ alerta.mensagem }}
                        (Placa: {{ alerta.placa }} - {{ alerta.data_alerta.strftime('%H:%M:%S') }})
                    </div>
                </div>
                {% endfor %}
            {% endif %}
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number success">{{ veiculos|length }}</div>
                    <div class="stat-label">Veículos Cadastrados</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number danger">{{ imagens_desconhecidas|length }}</div>
                    <div class="stat-label">Placas Não Cadastradas</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number warning">{{ alertas|length }}</div>
                    <div class="stat-label">Alertas Ativos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ acessos|length }}</div>
                    <div class="stat-label">Acessos Recentes</div>
                </div>
            </div>
            
            <div class="section">
                <h2>📸 Placas Não Cadastradas - Aguardando Cadastro</h2>
                <div class="images-grid">
                    {% for img_path in imagens_desconhecidas %}
                        {% set filename = img_path.split('\\\\')[-1] %}
                        {% set placa_nome = filename.split('_')[0] %}
                        <div class="image-card" onclick="window.location.href='{{ url_for('cadastro_veiculo', placa=placa_nome) }}'">
                            <img src="{{ url_for('static_image', filename=filename) }}" alt="{{ placa_nome }}">
                            <div class="image-info">
                                <div class="image-placa">{{ placa_nome }}</div>
                                <div class="image-timestamp">{{ filename.split('_')[1].split('.')[0] if '_' in filename else 'N/A' }}</div>
                                <button class="btn-cadastrar" onclick="event.stopPropagation(); window.location.href='{{ url_for('cadastro_veiculo', placa=placa_nome) }}'">
                                    Cadastrar Veículo
                                </button>
                            </div>
                        </div>
                    {% endfor %}
                    {% if imagens_desconhecidas|length == 0 %}
                        <div class="empty-state">
                            <p>✅ Nenhuma placa desconhecida no momento</p>
                        </div>
                    {% endif %}
                </div>
            </div>
            
            <div class="section">
                <h2>🚘 Veículos Cadastrados</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Placa</th>
                            <th>Proprietário</th>
                            <th>Tipo</th>
                            <th>Modelo</th>
                            <th>Status</th>
                            <th>Ações</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for veiculo in veiculos %}
                        <tr>
                            <td><span class="badge badge-placa">{{ veiculo.placa }}</span></td>
                            <td>{{ veiculo.usuario_nome or 'Não vinculado' }}</td>
                            <td>
                                {% if veiculo.usuario_tipo == 'OFICIAL' %}
                                    <span class="badge badge-oficial">OFICIAL</span>
                                {% else %}
                                    <span class="badge badge-particular">PARTICULAR</span>
                                {% endif %}
                            </td>
                            <td>{{ veiculo.modelo or '-' }}</td>
                            <td>
                                {% if veiculo.marcado %}
                                    <span class="badge badge-marcado">MARCADO</span>
                                {% elif veiculo.usuario_autorizado %}
                                    <span class="badge badge-autorizado">AUTORIZADO</span>
                                {% else %}
                                    <span class="badge badge-nao-autorizado">NÃO AUTORIZADO</span>
                                {% endif %}
                            </td>
                            <td>
                                <a href="{{ url_for('detalhes_veiculo', placa=veiculo.placa) }}" style="color: #007bff;">Ver detalhes</a>
                            </td>
                        </tr>
                        {% endfor %}
                        {% if veiculos|length == 0 %}
                        <tr>
                            <td colspan="6" class="empty-state">Nenhum veículo cadastrado ainda.</td>
                        </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h2>📊 Acessos Recentes</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Placa</th>
                            <th>Proprietário</th>
                            <th>Tipo</th>
                            <th>Data/Hora</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for acesso in acessos %}
                        <tr>
                            <td><span class="badge badge-placa">{{ acesso.placa }}</span></td>
                            <td>{{ acesso.usuario_nome or 'Desconhecido' }}</td>
                            <td>
                                {% if acesso.usuario_tipo == 'OFICIAL' %}
                                    <span class="badge badge-oficial">OFICIAL</span>
                                {% elif acesso.usuario_tipo == 'PARTICULAR' %}
                                    <span class="badge badge-particular">PARTICULAR</span>
                                {% else %}
                                    <span class="badge badge-nao-autorizado">NÃO CADASTRADO</span>
                                {% endif %}
                            </td>
                            <td>{{ acesso.data_acesso.strftime('%d/%m/%Y %H:%M:%S') }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_page, 
                                 veiculos=veiculos,
                                 alertas=alertas,
                                 acessos=acessos,
                                 imagens_desconhecidas=imagens_desconhecidas)


@app.route('/cadastro_veiculo')
def cadastro_veiculo():
    """Página de cadastro de veículo"""
    placa = request.args.get('placa', '')
    usuarios = conn_db.listar_usuarios(200)
    
    html_page = """
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Cadastrar Veículo - IFSULDEMINAS</title>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
                background-color: #f4f7f6; 
                color: #333; 
                margin: 0; 
                padding: 0; 
            }
            .navbar {
                background-color: #1a1a1a;
                padding: 15px 20px;
            }
            .navbar h1 {
                color: #fff;
                font-size: 1.5em;
                display: inline-block;
                margin: 0;
            }
            .navbar a {
                color: #fff;
                text-decoration: none;
                padding: 10px 15px;
                margin-left: 20px;
                border-radius: 5px;
                display: inline-block;
            }
            .navbar a:hover { background-color: #333; }
            
            .container { 
                max-width: 800px; 
                margin: 40px auto; 
                padding: 30px; 
                background-color: #fff; 
                border-radius: 8px; 
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); 
            }
            h2 { color: #1a1a1a; margin-bottom: 20px; }
            
            form { margin-top: 20px; }
            .form-group {
                margin-bottom: 20px;
            }
            label { 
                display: block; 
                margin-bottom: 8px; 
                font-weight: 600;
                color: #555;
            }
            input[type="text"], select, textarea {
                width: 100%; 
                padding: 12px; 
                box-sizing: border-box; 
                border: 1px solid #ddd; 
                border-radius: 5px;
                font-size: 1em;
            }
            input[type="text"]:focus, select:focus, textarea:focus {
                outline: none;
                border-color: #007bff;
            }
            .checkbox-group {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            input[type="checkbox"] {
                width: 20px;
                height: 20px;
            }
            button { 
                padding: 12px 30px; 
                background-color: #28a745; 
                color: white; 
                border: none; 
                border-radius: 5px; 
                cursor: pointer; 
                font-size: 1em;
                font-weight: bold;
            }
            button:hover { background-color: #218838; }
            .btn-secondary {
                background-color: #6c757d;
                margin-left: 10px;
            }
            .btn-secondary:hover { background-color: #5a6268; }
            
            .toggle-section {
                background-color: #f8f9fa;
                padding: 20px;
                border-radius: 5px;
                margin-top: 20px;
            }
            .toggle-btn {
                background-color: #007bff;
                padding: 10px 20px;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin-bottom: 15px;
            }
            .toggle-btn:hover { background-color: #0056b3; }
            .hidden { display: none; }
        </style>
        <script>
            function toggleNovoUsuario() {
                var section = document.getElementById('novo-usuario-section');
                var select = document.getElementById('usuario_existente');
                if (section.classList.contains('hidden')) {
                    section.classList.remove('hidden');
                    select.disabled = true;
                    select.required = false;
                } else {
                    section.classList.add('hidden');
                    select.disabled = false;
                    select.required = true;
                }
            }
        </script>
    </head>
    <body>
        <div class="navbar">
            <h1>🚗 Cadastrar Novo Veículo</h1>
            <a href="{{ url_for('index') }}">← Voltar ao Dashboard</a>
        </div>
        
        <div class="container">
            <h2>Cadastro de Veículo</h2>
            
            <form action="{{ url_for('salvar_veiculo') }}" method="post">
                <div class="form-group">
                    <label for="placa">Placa do Veículo *</label>
                    <input type="text" id="placa" name="placa" value="{{ placa }}" 
                           placeholder="ABC1234 ou ABC1D23" required 
                           pattern="[A-Z]{3}\d{4}|[A-Z]{3}\d[A-Z]\d{2}" 
                           title="Digite uma placa válida (ABC1234 ou ABC1D23)">
                </div>
                
                <div class="form-group">
                    <label for="modelo">Modelo do Veículo</label>
                    <input type="text" id="modelo" name="modelo" 
                           placeholder="Ex: Honda Civic, Toyota Corolla">
                </div>
                
                <div class="form-group">
                    <label for="cor">Cor</label>
                    <input type="text" id="cor" name="cor" placeholder="Ex: Preto, Branco, Prata">
                </div>
                
                <div class="form-group">
                    <label for="tipo_veiculo">Tipo de Veículo *</label>
                    <select id="tipo_veiculo" name="tipo_veiculo" required>
                        <option value="CARRO">Carro</option>
                        <option value="MOTO">Moto</option>
                        <option value="CAMINHAO">Caminhão</option>
                        <option value="OUTRO">Outro</option>
                    </select>
                </div>
                
                <hr style="margin: 30px 0;">
                
                <h3>Proprietário do Veículo</h3>
                
                <div class="form-group">
                    <label for="usuario_existente">Selecionar Usuário Existente *</label>
                    <select id="usuario_existente" name="usuario_existente" required>
                        <option value="">-- Selecione um usuário --</option>
                        {% for usuario in usuarios %}
                            <option value="{{ usuario.id }}">
                                {{ usuario.nome }} - {{ usuario.tipo }} 
                                {% if usuario.cpf %} (CPF: {{ usuario.cpf }}){% endif %}
                            </option>
                        {% endfor %}
                    </select>
                </div>
                
                <button type="button" class="toggle-btn" onclick="toggleNovoUsuario()">
                    ➕ Ou Cadastrar Novo Usuário
                </button>
                
                <div id="novo-usuario-section" class="toggle-section hidden">
                    <h4>Dados do Novo Usuário</h4>
                    
                    <div class="form-group">
                        <label for="usuario_nome">Nome Completo</label>
                        <input type="text" id="usuario_nome" name="usuario_nome" 
                               placeholder="Nome completo do proprietário">
                    </div>
                    
                    <div class="form-group">
                        <label for="usuario_cpf">CPF</label>
                        <input type="text" id="usuario_cpf" name="usuario_cpf" 
                               placeholder="000.000.000-00" maxlength="14">
                    </div>
                    
                    <div class="form-group">
                        <label for="usuario_telefone">Telefone</label>
                        <input type="text" id="usuario_telefone" name="usuario_telefone" 
                               placeholder="(00) 00000-0000">
                    </div>
                    
                    <div class="form-group">
                        <label for="usuario_tipo">Tipo de Usuário</label>
                        <select id="usuario_tipo" name="usuario_tipo">
                            <option value="PARTICULAR">Particular</option>
                            <option value="OFICIAL">Oficial (Servidor/Professor)</option>
                        </select>
                    </div>
                    
                    <div class="form-group checkbox-group">
                        <input type="checkbox" id="usuario_autorizado" name="usuario_autorizado" checked>
                        <label for="usuario_autorizado">Autorizado a acessar a instituição</label>
                    </div>
                </div>
                
                <hr style="margin: 30px 0;">
                
                <div class="form-group checkbox-group">
                    <input type="checkbox" id="marcado" name="marcado">
                    <label for="marcado">Marcar veículo para controle especial</label>
                </div>
                
                <div class="form-group">
                    <label for="motivo_marcacao">Motivo da Marcação (se aplicável)</label>
                    <textarea id="motivo_marcacao" name="motivo_marcacao" rows="3" 
                              placeholder="Descreva o motivo da marcação do veículo"></textarea>
                </div>
                
                <button type="submit">✅ Cadastrar Veículo</button>
                <a href="{{ url_for('index') }}" class="btn-secondary" style="text-decoration: none; display: inline-block; padding: 12px 30px; border-radius: 5px;">
                    Cancelar
                </a>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_page, placa=placa, usuarios=usuarios)


@app.route('/salvar_veiculo', methods=['POST'])
def salvar_veiculo():
    """Processa o cadastro de um novo veículo"""
    placa = request.form.get('placa', '').upper().strip()
    modelo = request.form.get('modelo', '').strip()
    cor = request.form.get('cor', '').strip()
    tipo_veiculo = request.form.get('tipo_veiculo', 'CARRO')
    marcado = 'marcado' in request.form
    motivo_marcacao = request.form.get('motivo_marcacao', '').strip()
    
    # Verifica se vai usar usuário existente ou criar novo
    usuario_existente_id = request.form.get('usuario_existente')
    
    if usuario_existente_id:
        usuario_id = int(usuario_existente_id)
    else:
        # Cria novo usuário
        usuario_nome = request.form.get('usuario_nome', '').strip()
        usuario_cpf = request.form.get('usuario_cpf', '').strip()
        usuario_telefone = request.form.get('usuario_telefone', '').strip()
        usuario_tipo = request.form.get('usuario_tipo', 'PARTICULAR')
        usuario_autorizado = 'usuario_autorizado' in request.form
        
        if not usuario_nome:
            return "Erro: Nome do usuário é obrigatório", 400
        
        usuario_id = conn_db.cadastrar_usuario(
            usuario_nome, usuario_cpf, usuario_telefone, usuario_tipo, usuario_autorizado
        )
        
        if not usuario_id:
            return "Erro ao cadastrar usuário", 500
    
    # Valida e determina tipo da placa
    placa_validada, tipo_placa = validar_placa(placa)
    
    if not placa_validada:
        return f"Erro: Placa '{placa}' inválida. Use formato ABC1234 ou ABC1D23", 400
    
    # Cadastra o veículo
    sucesso = conn_db.cadastrar_veiculo(
        placa_validada, tipo_placa, usuario_id, modelo, cor, tipo_veiculo
    )
    
    if not sucesso:
        return "Erro ao cadastrar veículo", 500
    
    # Se marcado, aplica marcação
    if marcado and motivo_marcacao:
        conn_db.marcar_veiculo(placa_validada, motivo_marcacao)
    
    # Remove imagens da placa da pasta de desconhecidos
    try:
        import shutil
        imagens_placa = glob.glob(os.path.join(PASTA_PLACAS_DESCONHECIDAS, f"{placa_validada}_*.jpg"))
        for img_path in imagens_placa:
            # Move para pasta de conhecidas ao invés de deletar
            nome_arquivo = os.path.basename(img_path)
            destino = os.path.join(PASTA_PLACAS_CONHECIDAS, nome_arquivo)
            shutil.move(img_path, destino)
            print(f"✓ Imagem movida de desconhecidas para conhecidas: {nome_arquivo}")
    except Exception as e:
        print(f"⚠️ Erro ao mover imagens: {e}")
    
    return redirect(url_for('index'))


@app.route('/detalhes_veiculo/<placa>')
def detalhes_veiculo(placa):
    """Mostra detalhes de um veículo específico"""
    veiculo = conn_db.buscar_veiculo(placa)
    
    if not veiculo:
        return "Veículo não encontrado", 404
    
    html_page = """
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>Detalhes - {{ veiculo.placa }}</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                background-color: #f4f7f6; 
                padding: 20px; 
            }
            .container { 
                max-width: 800px; 
                margin: 0 auto; 
                background: white; 
                padding: 30px; 
                border-radius: 8px; 
            }
            h1 { color: #1a1a1a; }
            .info-grid {
                display: grid;
                grid-template-columns: 200px 1fr;
                gap: 15px;
                margin: 20px 0;
            }
            .label { font-weight: bold; color: #666; }
            .value { color: #333; }
            .badge {
                display: inline-block;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: 0.9em;
            }
            .badge-success { background-color: #28a745; color: white; }
            .badge-danger { background-color: #dc3545; color: white; }
            .badge-warning { background-color: #ffc107; color: #000; }
            a { 
                display: inline-block;
                padding: 10px 20px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                margin-top: 20px;
            }
            a:hover { background-color: #0056b3; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚗 Detalhes do Veículo</h1>
            
            <div class="info-grid">
                <div class="label">Placa:</div>
                <div class="value"><strong style="font-size: 1.2em;">{{ veiculo.placa }}</strong></div>
                
                <div class="label">Tipo de Placa:</div>
                <div class="value">{{ veiculo.tipo_placa }}</div>
                
                <div class="label">Modelo:</div>
                <div class="value">{{ veiculo.modelo or 'Não informado' }}</div>
                
                <div class="label">Cor:</div>
                <div class="value">{{ veiculo.cor or 'Não informada' }}</div>
                
                <div class="label">Tipo de Veículo:</div>
                <div class="value">{{ veiculo.tipo_veiculo }}</div>
                
                <div class="label">Proprietário:</div>
                <div class="value">{{ veiculo.usuario_nome or 'Não vinculado' }}</div>
                
                {% if veiculo.usuario_cpf %}
                <div class="label">CPF:</div>
                <div class="value">{{ veiculo.usuario_cpf }}</div>
                {% endif %}
                
                {% if veiculo.usuario_telefone %}
                <div class="label">Telefone:</div>
                <div class="value">{{ veiculo.usuario_telefone }}</div>
                {% endif %}
                
                <div class="label">Tipo de Usuário:</div>
                <div class="value">{{ veiculo.usuario_tipo or 'N/A' }}</div>
                
                <div class="label">Status:</div>
                <div class="value">
                    {% if veiculo.marcado %}
                        <span class="badge badge-warning">MARCADO</span>
                    {% elif veiculo.usuario_autorizado %}
                        <span class="badge badge-success">AUTORIZADO</span>
                    {% else %}
                        <span class="badge badge-danger">NÃO AUTORIZADO</span>
                    {% endif %}
                </div>
                
                {% if veiculo.motivo_marcacao %}
                <div class="label">Motivo da Marcação:</div>
                <div class="value">{{ veiculo.motivo_marcacao }}</div>
                {% endif %}
            </div>
            
            <a href="{{ url_for('index') }}">← Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_page, veiculo=veiculo)


@app.route('/listar_usuarios')
def listar_usuarios():
    """Lista todos os usuários cadastrados"""
    usuarios = conn_db.listar_usuarios(200)
    
    html_page = """
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>Usuários Cadastrados</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                background-color: #f4f7f6; 
                padding: 20px; 
            }
            .container { 
                max-width: 1200px; 
                margin: 0 auto; 
                background: white; 
                padding: 30px; 
                border-radius: 8px; 
            }
            h1 { color: #1a1a1a; }
            table { width: 100%; border-collapse: collapse; margin: 20px 0; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
            th { background-color: #f8f9fa; font-weight: 600; }
            tr:hover { background-color: #f8f9fa; }
            .badge {
                display: inline-block;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: 0.85em;
            }
            .badge-oficial { background-color: #17a2b8; color: white; }
            .badge-particular { background-color: #6c757d; color: white; }
            .badge-success { background-color: #28a745; color: white; }
            .badge-danger { background-color: #dc3545; color: white; }
            a { 
                display: inline-block;
                padding: 10px 20px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                margin: 10px 0;
            }
            a:hover { background-color: #0056b3; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>👥 Usuários Cadastrados</h1>
            
            <a href="{{ url_for('index') }}">← Voltar ao Dashboard</a>
            
            <table>
                <thead>
                    <tr>
                        <th>Nome</th>
                        <th>CPF</th>
                        <th>Telefone</th>
                        <th>Tipo</th>
                        <th>Status</th>
                        <th>Cadastro</th>
                    </tr>
                </thead>
                <tbody>
                    {% for usuario in usuarios %}
                    <tr>
                        <td>{{ usuario.nome }}</td>
                        <td>{{ usuario.cpf or '-' }}</td>
                        <td>{{ usuario.telefone or '-' }}</td>
                        <td>
                            {% if usuario.tipo == 'OFICIAL' %}
                                <span class="badge badge-oficial">OFICIAL</span>
                            {% else %}
                                <span class="badge badge-particular">PARTICULAR</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if usuario.autorizado %}
                                <span class="badge badge-success">AUTORIZADO</span>
                            {% else %}
                                <span class="badge badge-danger">NÃO AUTORIZADO</span>
                            {% endif %}
                        </td>
                        <td>{{ usuario.data_cadastro.strftime('%d/%m/%Y') }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_page, usuarios=usuarios)


@app.route('/live')
def live_view():
    """Página de visualização ao vivo"""
    html_page = """
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>Reconhecimento Ao Vivo</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                background-color: #282c34; 
                color: white; 
                text-align: center;
                margin: 0;
                padding: 0;
            }
            h1 { 
                margin: 20px 0; 
                padding: 10px;
                background-color: rgba(0,0,0,0.3);
            }
            img { 
                margin: 10px auto;
                border: 3px solid #61dafb; 
                border-radius: 8px; 
                max-width: 95%;
                height: auto;
            }
            .controls {
                margin: 20px;
            }
            .btn {
                padding: 10px 20px;
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 1em;
                margin: 5px;
                text-decoration: none;
                display: inline-block;
            }
            .btn:hover {
                background-color: #0056b3;
            }
        </style>
    </head>
    <body>
        <h1>🚗 Reconhecimento de Placas - Ao Vivo</h1>
        <div class="controls">
            <a href="{{ url_for('index') }}" class="btn">← Voltar ao Dashboard</a>
        </div>
        <img src="{{ url_for('video_feed') }}" alt="Stream de Vídeo">
    </body>
    </html>
    """
    return render_template_string(html_page)


@app.route('/video_feed')
def video_feed():
    """Rota que serve o stream de vídeo"""
    return Response(generate_frames(), 
                   mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/images/<filename>')
def static_image(filename):
    """Serve imagens salvas"""
    from flask import send_file
    caminho = os.path.join(PASTA_PLACAS_DESCONHECIDAS, filename)
    if os.path.exists(caminho):
        return send_file(caminho, mimetype='image/jpeg')
    return "Imagem não encontrada", 404


# --- INICIALIZAÇÃO ---
if __name__ == '__main__':
    print("\n" + "="*60)
    print("SISTEMA WEB DE RECONHECIMENTO DE PLACAS - IFSULDEMINAS")
    print("="*60)
    print()
    
    # Inicializa componentes
    inicializar_ocr()
    conn_db = GerenciadorBanco()
    
    print("\n" + "="*60)
    print("Iniciando servidor web...")
    print("="*60)
    print("\n📍 Acesse: http://localhost:5000")
    print("📍 Ou pela rede: http://SEU_IP:5000")
    print("\nPressione Ctrl+C para encerrar\n")
    
    try:
        # Inicia o servidor Flask
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    finally:
        conn_db.fechar()
