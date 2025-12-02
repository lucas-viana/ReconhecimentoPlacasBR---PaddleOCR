# ReconhecimentoPlacasBR - PaddleOCR

Sistema Web de Reconhecimento de Placas Veiculares (Brasil) usando Flask, PaddleOCR e PostgreSQL.

## Descrição
Este projeto realiza a detecção e reconhecimento de placas de veículos em tempo real a partir de vídeo ou webcam, permitindo cadastro de veículos, usuários e controle de acesso, com interface web moderna e banco de dados relacional.

## Funcionalidades
- Reconhecimento automático de placas (carros e motos)
- Cadastro de veículos e usuários vinculados
- Controle de acesso (autorizado, não autorizado, marcado)
- Geração de alertas e logs de acessos
- Dashboard web com estatísticas, imagens e histórico
- Armazenamento de imagens de placas desconhecidas/conhecidas
- Suporte a múltiplos formatos de placa (Mercosul e antigo)

## Como executar
1. **Clone o repositório:**
   ```bash
   git clone https://github.com/lucas-viana/ReconhecimentoPlacasBR---PaddleOCR.git
   cd ReconhecimentoPlacasBR---PaddleOCR
   ```
2. **Crie e ative o ambiente virtual:**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/Mac:
   source venv/bin/activate
   ```
3. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure o banco de dados PostgreSQL** (ajuste as credenciais no início do arquivo `web_app_placas.py`).
5. **Execute a aplicação:**
   ```bash
   python web_app_placas.py
   ```
6. **Acesse no navegador:**
   - [http://localhost:5000](http://localhost:5000)

## Versão do Python
- **Python 3.11.6** (recomendado)

## Principais Pacotes Utilizados
- **Flask** (web framework)
- **PaddleOCR** (reconhecimento óptico de caracteres)
- **paddlepaddle** (backend do PaddleOCR)
- **opencv-python** (processamento de vídeo/imagem)
- **psycopg2** (conector PostgreSQL)
- **numpy** (operações matriciais)
- **glob2** (busca de arquivos)

Outros pacotes auxiliares:
- **shutil** (operações de arquivos)
- **re** (expressões regulares)
- **datetime** (datas e horários)

## Estrutura de Pastas Importantes
- `placas_desconhecidas/` — Imagens de placas não cadastradas
- `placas_conhecidas/` — Imagens de placas já cadastradas

## Observações
- O sistema foi desenvolvido para rodar em Windows, mas pode ser adaptado para Linux/Mac.
- O banco de dados padrão é PostgreSQL, mas pode ser adaptado para outros SGBDs.
- O PaddleOCR pode usar GPU se disponível (CUDA).

## Licença
MIT
