"""
Sistema de Detecção de Placas em Vídeo/Webcam
Salva detecções em PostgreSQL ou MySQL
"""

import paddle
from paddleocr import PaddleOCR
import cv2
import numpy as np
import re
from datetime import datetime
import psycopg2
import mysql.connector
from typing import Optional, Dict, List

# --- CONFIGURAÇÃO ---
USAR_WEBCAM = False  # True para webcam, False para arquivo de vídeo
ARQUIVO_VIDEO = "video_entrada.mp4"

# Configuração do Banco de Dados
USAR_POSTGRES = True  # True = PostgreSQL, False = MySQL

# PostgreSQL
POSTGRES_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'ifsuldeminas',
    'user': 'postgres',
    'password': '353742Ap$'
}

# MySQL
MYSQL_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'database': 'ifsuldeminas',
    'user': 'root',
    'password': '353742Ap$'
}

# OCR e Processamento
PROCESSAR_A_CADA_N_FRAMES = 1  # Processar 1 a cada 1 frames (melhor performance)
CONFIANCA_MINIMA = 0.97  # Confiança mínima para aceitar detecção
CONFIANCA_MINIMA_MOTO = 0.97  # Confiança 100% para placas de moto (2 linhas)
COOLDOWN_SEGUNDOS = 120  # Tempo para ignorar mesma placa detectada novamente
# --------------------

# Padrões de placas brasileiras
# MERCOSUL (7 caracteres)
PADRAO_MERCOSUL_CARRO = re.compile(r'^[A-Z]{3}\d[A-Z]\d{2}$')  # ABC1D23
PADRAO_MERCOSUL_MOTO = re.compile(r'^[A-Z]{3}\d[A-Z]\d{2}$')   # ABC1D23 (mesmo padrão)

# ANTIGA (7 caracteres)
PADRAO_ANTIGO_CARRO = re.compile(r'^[A-Z]{3}\d{4}$')           # ABC1234
PADRAO_ANTIGO_MOTO = re.compile(r'^[A-Z]{3}\d{4}$')            # ABC1234 (mesmo padrão)

# Diferenciação: CARRO = 1 linha detectada | MOTO = 2 linhas combinadas


class GerenciadorBanco:
    """Gerencia conexão e operações com PostgreSQL ou MySQL"""
    
    def __init__(self, usar_postgres=True):
        self.usar_postgres = usar_postgres
        self.conn = None
        self.conectar()
        self.criar_tabelas()
    
    def conectar(self):
        """Estabelece conexão com o banco de dados"""
        try:
            if self.usar_postgres:
                self.conn = psycopg2.connect(**POSTGRES_CONFIG)
                print(f"✓ Conectado ao PostgreSQL: {POSTGRES_CONFIG['database']}")
            else:
                self.conn = mysql.connector.connect(**MYSQL_CONFIG)
                print(f"✓ Conectado ao MySQL: {MYSQL_CONFIG['database']}")
        except Exception as e:
            print(f"❌ Erro ao conectar no banco: {e}")
            print("\n⚠️  Verifique as configurações de conexão no arquivo!")
            raise
    
    def criar_tabelas(self):
        """Cria tabela de detecções se não existir"""
        cursor = self.conn.cursor()
        
        if self.usar_postgres:
            # PostgreSQL
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deteccoes_placas (
                    id SERIAL PRIMARY KEY,
                    placa VARCHAR(10) NOT NULL,
                    tipo_placa VARCHAR(20) NOT NULL,
                    confianca DECIMAL(5, 4) NOT NULL,
                    data_deteccao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    frame_numero INTEGER,
                    origem VARCHAR(50)
                )
            """)
            
            # Índice para busca rápida por placa
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_placa 
                ON deteccoes_placas(placa)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_data 
                ON deteccoes_placas(data_deteccao)
            """)
        else:
            # MySQL
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deteccoes_placas (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    placa VARCHAR(10) NOT NULL,
                    tipo_placa VARCHAR(20) NOT NULL,
                    confianca DECIMAL(5, 4) NOT NULL,
                    data_deteccao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    frame_numero INT,
                    origem VARCHAR(50),
                    INDEX idx_placa (placa),
                    INDEX idx_data (data_deteccao)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        
        self.conn.commit()
        print("✓ Tabela 'deteccoes_placas' pronta")
    
    def salvar_deteccao(self, placa: str, tipo_placa: str, confianca: float, 
                       frame_numero: int, origem: str = 'CAMERA') -> bool:
        """Salva detecção no banco de dados"""
        try:
            cursor = self.conn.cursor()
            
            if self.usar_postgres:
                cursor.execute("""
                    INSERT INTO deteccoes_placas 
                    (placa, tipo_placa, confianca, frame_numero, origem)
                    VALUES (%s, %s, %s, %s, %s)
                """, (placa, tipo_placa, confianca, frame_numero, origem))
            else:
                cursor.execute("""
                    INSERT INTO deteccoes_placas 
                    (placa, tipo_placa, confianca, frame_numero, origem)
                    VALUES (%s, %s, %s, %s, %s)
                """, (placa, tipo_placa, confianca, frame_numero, origem))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao salvar no banco: {e}")
            self.conn.rollback()
            return False
    
    def buscar_ultima_deteccao(self, placa: str) -> Optional[Dict]:
        """Busca última detecção de uma placa"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, placa, tipo_placa, confianca, data_deteccao, frame_numero, origem
            FROM deteccoes_placas
            WHERE placa = %s
            ORDER BY data_deteccao DESC
            LIMIT 1
        """, (placa,))
        
        resultado = cursor.fetchone()
        
        if resultado:
            return {
                'id': resultado[0],
                'placa': resultado[1],
                'tipo_placa': resultado[2],
                'confianca': float(resultado[3]),
                'data_deteccao': resultado[4],
                'frame_numero': resultado[5],
                'origem': resultado[6]
            }
        return None
    
    def contar_deteccoes_hoje(self) -> int:
        """Conta quantas detecções foram feitas hoje"""
        cursor = self.conn.cursor()
        
        if self.usar_postgres:
            cursor.execute("""
                SELECT COUNT(*) FROM deteccoes_placas
                WHERE DATE(data_deteccao) = CURRENT_DATE
            """)
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM deteccoes_placas
                WHERE DATE(data_deteccao) = CURDATE()
            """)
        
        return cursor.fetchone()[0]
    
    def listar_placas_unicas_hoje(self) -> List[str]:
        """Lista placas únicas detectadas hoje"""
        cursor = self.conn.cursor()
        
        if self.usar_postgres:
            cursor.execute("""
                SELECT DISTINCT placa FROM deteccoes_placas
                WHERE DATE(data_deteccao) = CURRENT_DATE
                ORDER BY placa
            """)
        else:
            cursor.execute("""
                SELECT DISTINCT placa FROM deteccoes_placas
                WHERE DATE(data_deteccao) = CURDATE()
                ORDER BY placa
            """)
        
        return [row[0] for row in cursor.fetchall()]
    
    def atualizar_deteccao(self, id_deteccao: int, placa: str = None, 
                          tipo_placa: str = None, confianca: float = None) -> bool:
        """Atualiza uma detecção existente"""
        try:
            cursor = self.conn.cursor()
            campos = []
            valores = []
            
            if placa is not None:
                campos.append("placa = %s")
                valores.append(placa)
            if tipo_placa is not None:
                campos.append("tipo_placa = %s")
                valores.append(tipo_placa)
            if confianca is not None:
                campos.append("confianca = %s")
                valores.append(confianca)
            
            if not campos:
                return False
            
            valores.append(id_deteccao)
            
            sql = f"UPDATE deteccoes_placas SET {', '.join(campos)} WHERE id = %s"
            cursor.execute(sql, valores)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao atualizar detecção: {e}")
            self.conn.rollback()
            return False
    
    def deletar_deteccao(self, id_deteccao: int) -> bool:
        """Deleta uma detecção do banco"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM deteccoes_placas WHERE id = %s", (id_deteccao,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"❌ Erro ao deletar detecção: {e}")
            self.conn.rollback()
            return False
    
    def deletar_deteccoes_por_placa(self, placa: str) -> int:
        """Deleta todas as detecções de uma placa e retorna a quantidade deletada"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM deteccoes_placas WHERE placa = %s", (placa,))
            self.conn.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"❌ Erro ao deletar detecções: {e}")
            self.conn.rollback()
            return 0
    
    def deletar_deteccoes_por_data(self, data: str) -> int:
        """Deleta todas as detecções de uma data específica (formato: YYYY-MM-DD)"""
        try:
            cursor = self.conn.cursor()
            
            if self.usar_postgres:
                cursor.execute(
                    "DELETE FROM deteccoes_placas WHERE DATE(data_deteccao) = %s",
                    (data,)
                )
            else:
                cursor.execute(
                    "DELETE FROM deteccoes_placas WHERE DATE(data_deteccao) = %s",
                    (data,)
                )
            
            self.conn.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"❌ Erro ao deletar detecções por data: {e}")
            self.conn.rollback()
            return 0
    
    def buscar_deteccao_por_id(self, id_deteccao: int) -> Optional[Dict]:
        """Busca uma detecção específica pelo ID"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, placa, tipo_placa, confianca, data_deteccao, frame_numero, origem
            FROM deteccoes_placas
            WHERE id = %s
        """, (id_deteccao,))
        
        resultado = cursor.fetchone()
        
        if resultado:
            return {
                'id': resultado[0],
                'placa': resultado[1],
                'tipo_placa': resultado[2],
                'confianca': float(resultado[3]),
                'data_deteccao': resultado[4],
                'frame_numero': resultado[5],
                'origem': resultado[6]
            }
        return None
    
    def listar_todas_deteccoes(self, limite: int = 100) -> List[Dict]:
        """Lista todas as detecções com limite"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, placa, tipo_placa, confianca, data_deteccao, frame_numero, origem
            FROM deteccoes_placas
            ORDER BY data_deteccao DESC
            LIMIT %s
        """, (limite,))
        
        deteccoes = []
        for resultado in cursor.fetchall():
            deteccoes.append({
                'id': resultado[0],
                'placa': resultado[1],
                'tipo_placa': resultado[2],
                'confianca': float(resultado[3]),
                'data_deteccao': resultado[4],
                'frame_numero': resultado[5],
                'origem': resultado[6]
            })
        
        return deteccoes
    
    def listar_deteccoes_por_tipo(self, tipo_placa: str) -> List[Dict]:
        """Lista todas as detecções de um tipo específico"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT id, placa, tipo_placa, confianca, data_deteccao, frame_numero, origem
            FROM deteccoes_placas
            WHERE tipo_placa = %s
            ORDER BY data_deteccao DESC
        """, (tipo_placa,))
        
        deteccoes = []
        for resultado in cursor.fetchall():
            deteccoes.append({
                'id': resultado[0],
                'placa': resultado[1],
                'tipo_placa': resultado[2],
                'confianca': float(resultado[3]),
                'data_deteccao': resultado[4],
                'frame_numero': resultado[5],
                'origem': resultado[6]
            })
        
        return deteccoes
    
    def fechar(self):
        """Fecha conexão com o banco"""
        if self.conn:
            self.conn.close()
            print("✓ Conexão com banco fechada")


class DetectorPlacas:
    """Sistema de detecção de placas em vídeo"""
    
    def __init__(self):
        self.ocr = None
        self.db = None
        self.placas_cache = {}  # Cache para evitar detecções duplicadas
        self.configurar_gpu()
        self.conectar_banco()
    
    def configurar_gpu(self):
        """Configura GPU se disponível"""
        print("\n" + "="*60)
        print("CONFIGURAÇÃO DO SISTEMA")
        print("="*60)
        
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
        
        print("\nCarregando modelo OCR...")
        self.ocr = PaddleOCR(use_angle_cls=True, lang='en')
        print("✓ Modelo OCR carregado")
    
    def conectar_banco(self):
        """Conecta ao banco de dados"""
        self.db = GerenciadorBanco(usar_postgres=USAR_POSTGRES)
    
    def validar_placa(self, texto: str, eh_combinacao: bool = False) -> tuple:
        """
        Valida se o texto é uma placa brasileira válida
        
        Args:
            texto: Texto a validar
            eh_combinacao: True se foi combinação de 2 textos (placa de moto)
        
        Returns:
            (placa, tipo) ou (None, None)
        """
        # Remove espaços, traços, pontos, quebras de linha e outros caracteres especiais
        texto_limpo = texto.upper()
        texto_limpo = re.sub(r'[^A-Z0-9]', '', texto_limpo)  # Mantém apenas letras e números
        
        # Corrige erros comuns de OCR
        texto_corrigido = texto_limpo.replace('O', '0').replace('I', '1').replace('S', '5')
        
        # Tenta validar cada padrão
        for texto_teste in [texto_limpo, texto_corrigido]:
            # MERCOSUL
            if PADRAO_MERCOSUL_CARRO.match(texto_teste):
                if eh_combinacao:
                    return texto_teste, "MERCOSUL_MOTO"
                else:
                    return texto_teste, "MERCOSUL_CARRO"
            
            # ANTIGA
            elif PADRAO_ANTIGO_CARRO.match(texto_teste):
                if eh_combinacao:
                    return texto_teste, "ANTIGA_MOTO"
                else:
                    return texto_teste, "ANTIGA_CARRO"
        
        return None, None
    
    def pode_processar_placa(self, placa: str) -> bool:
        """Verifica se pode processar a placa (cooldown)"""
        if placa in self.placas_cache:
            tempo_decorrido = (datetime.now() - self.placas_cache[placa]).seconds
            if tempo_decorrido < COOLDOWN_SEGUNDOS:
                return False
        
        return True
    
    def processar_deteccao(self, placa: str, tipo_placa: str, 
                          confianca: float, frame_numero: int) -> bool:
        """Processa e salva uma detecção"""
        if not self.pode_processar_placa(placa):
            return False
        
        # Atualiza cache
        self.placas_cache[placa] = datetime.now()
        
        # Salva no banco
        sucesso = self.db.salvar_deteccao(placa, tipo_placa, confianca, frame_numero)
        
        if sucesso:
            print(f"\n{'='*60}")
            print(f"🚗 NOVA PLACA DETECTADA E SALVA!")
            print(f"   Placa: {placa}")
            print(f"   Tipo: {tipo_placa}")
            print(f"   Confiança: {confianca:.2%}")
            print(f"   Frame: {frame_numero}")
            print(f"   Horário: {datetime.now().strftime('%H:%M:%S')}")
            print('='*60)
        
        return sucesso
    
    def desenhar_interface(self, frame, deteccoes, frame_count):
        """Desenha interface no frame"""
        frame_desenho = frame.copy()
        altura, largura = frame.shape[:2]
        
        # Estatísticas
        total_hoje = self.db.contar_deteccoes_hoje()
        placas_unicas = len(self.db.listar_placas_unicas_hoje())
        
        # Barra superior
        cv2.rectangle(frame_desenho, (0, 0), (largura, 80), (0, 0, 0), -1)
        
        # Título
        titulo = "SISTEMA DE DETECÇÃO DE PLACAS - IFSULDEMINAS"
        cv2.putText(frame_desenho, titulo, (10, 25),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Estatísticas
        stats = f"Hoje: {total_hoje} deteccoes | Placas unicas: {placas_unicas} | Frame: {frame_count}"
        cv2.putText(frame_desenho, stats, (10, 55),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        # Desenha cada detecção
        for det in deteccoes:
            coords = det['coordenadas']
            placa = det['placa']
            tipo = det['tipo']
            confianca = det['confianca']
            salvo = det.get('salvo', False)
            
            # Cor baseada no status
            cor = (0, 255, 0) if salvo else (0, 165, 255)
            
            # Desenha caixa ao redor da placa
            pts = np.array(coords, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame_desenho, [pts], True, cor, 3)
            
            # Texto com informações
            x, y = int(coords[0][0]), int(coords[0][1])
            texto = f"{placa} ({tipo}) {confianca:.0%}"
            if salvo:
                texto += " - SALVO"
            
            # Fundo para o texto
            (w, h), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(frame_desenho, (x, y-35), (x+w+10, y-5), cor, -1)
            
            # Texto branco
            cv2.putText(frame_desenho, texto, (x+5, y-15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # Instruções
        instrucoes = "Pressione 'q' para sair | 'r' para relatorio"
        cv2.putText(frame_desenho, instrucoes, (10, altura - 15),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        return frame_desenho
    
    def mostrar_relatorio(self):
        """Mostra relatório de detecções do dia"""
        print("\n" + "="*60)
        print("RELATÓRIO DE DETECÇÕES - HOJE")
        print("="*60)
        
        total = self.db.contar_deteccoes_hoje()
        placas = self.db.listar_placas_unicas_hoje()
        
        print(f"Total de detecções: {total}")
        print(f"Placas únicas: {len(placas)}")
        
        if placas:
            print("\nPlacas detectadas:")
            for i, placa in enumerate(placas, 1):
                ultima = self.db.buscar_ultima_deteccao(placa)
                if ultima:
                    hora = ultima['data_deteccao'].strftime('%H:%M:%S')
                    print(f"  {i:2d}. {placa} ({ultima['tipo_placa']}) - "
                          f"Última: {hora} - Conf: {ultima['confianca']:.2%}")
        
        print("="*60 + "\n")
    
    def executar(self):
        """Loop principal do sistema"""
        # Abre câmera ou vídeo
        if USAR_WEBCAM:
            cap = cv2.VideoCapture(0)
            origem = "WEBCAM"
            print("📹 Usando WEBCAM")
        else:
            cap = cv2.VideoCapture(ARQUIVO_VIDEO)
            origem = "VIDEO"
            print(f"📹 Processando vídeo: {ARQUIVO_VIDEO}")
        
        if not cap.isOpened():
            print("❌ Erro ao abrir câmera/vídeo!")
            return
        
        # Informações do vídeo
        fps = cap.get(cv2.CAP_PROP_FPS)
        largura = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        altura = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        print(f"Resolução: {largura}x{altura} | FPS: {fps:.1f}")
        print(f"Processando a cada {PROCESSAR_A_CADA_N_FRAMES} frames")
        print(f"Confiança mínima: {CONFIANCA_MINIMA:.0%}")
        print(f"Cooldown entre detecções: {COOLDOWN_SEGUNDOS}s")
        print("\n" + "="*60)
        print("⏯️  SISTEMA INICIADO")
        print("="*60 + "\n")
        
        frame_count = 0
        
        try:
            while True:
                ret, frame = cap.read()
                
                if not ret:
                    print("\n✓ Fim do vídeo")
                    break
                
                frame_count += 1
                deteccoes = []
                
                # Processa apenas a cada N frames (performance)
                if frame_count % PROCESSAR_A_CADA_N_FRAMES == 0:
                    resultado = self.ocr.ocr(frame, cls=True)
                    
                    if resultado and resultado[0]:
                        # Coleta todos os textos detectados
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
                        
                        # Tenta validar cada texto individualmente (PLACAS DE CARRO)
                        for item in textos_detectados:
                            placa, tipo = self.validar_placa(item['texto'], eh_combinacao=False)
                            
                            if placa:
                                # Processa e salva no banco
                                salvo = self.processar_deteccao(
                                    placa, tipo, item['confianca'], frame_count
                                )
                                
                                deteccoes.append({
                                    'placa': placa,
                                    'tipo': tipo,
                                    'confianca': item['confianca'],
                                    'coordenadas': item['coords'],
                                    'salvo': salvo
                                })
                        
                        # Tenta combinar textos adjacentes (PLACAS DE MOTO em 2 linhas)
                        # ABC (linha 1) + 1D23 (linha 2) = ABC1D23
                        # IMPORTANTE: Só salva se confiança média for 100%
                        for i, item1 in enumerate(textos_detectados):
                            for item2 in textos_detectados[i+1:]:
                                # Limpa os textos
                                texto1 = re.sub(r'[^A-Z0-9]', '', item1['texto'].upper())
                                texto2 = re.sub(r'[^A-Z0-9]', '', item2['texto'].upper())
                                
                                # Combina apenas na ordem correta: ABC + 1D23 = ABC1D23
                                combinado = texto1 + texto2
                                
                                placa, tipo = self.validar_placa(combinado, eh_combinacao=True)
                                
                                if placa:
                                    # Média das confianças
                                    confianca_media = (item1['confianca'] + item2['confianca']) / 2
                                    
                                    # ⚠️ REGRA ESPECIAL PARA MOTOS (2 linhas):
                                    # Só processa se confiança for 100%
                                    if confianca_media < CONFIANCA_MINIMA_MOTO:
                                        print(f"   ⚠️  Placa de moto {placa} ignorada - "
                                              f"Confiança {confianca_media:.2%} < {CONFIANCA_MINIMA_MOTO:.0%}")
                                        continue
                                    
                                    # Processa e salva no banco
                                    salvo = self.processar_deteccao(
                                        placa, tipo, confianca_media, frame_count
                                    )
                                    
                                    # Usa coordenadas do primeiro item
                                    deteccoes.append({
                                        'placa': placa,
                                        'tipo': tipo,
                                        'confianca': confianca_media,
                                        'coordenadas': item1['coords'],
                                        'salvo': salvo
                                    })
                                    break  # Encontrou, não precisa testar outras combinações
                
                # Desenha interface
                frame = self.desenhar_interface(frame, deteccoes, frame_count)
                
                # Rotaciona o frame se necessário (corrige orientação)
                #frame = cv2.flip(frame, -1)  # -1 = rotação 180 graus
                
                # Mostra frame
                cv2.imshow('Sistema de Detecção de Placas', frame)
                
                # Controles de teclado
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("\n⏹️  Sistema encerrado pelo usuário")
                    break
                elif key == ord('r'):
                    self.mostrar_relatorio()
        
        finally:
            cap.release()
            cv2.destroyAllWindows()
            self.mostrar_relatorio()
            self.db.fechar()


if __name__ == "__main__":
    print("\n" + "="*60)
    print("SISTEMA IFSULDEMINAS - DETECÇÃO DE PLACAS")
    print("="*60)
    print()
    
    detector = DetectorPlacas()
    detector.executar()
