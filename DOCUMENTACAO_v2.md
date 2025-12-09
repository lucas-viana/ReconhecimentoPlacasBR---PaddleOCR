# 📋 Documentação - Sistema de Detecção de Placas v2.0

## 📌 Resumo das Alterações

Este documento descreve as melhorias implementadas no sistema de detecção de placas, incluindo:

1. **Novos Métodos CRUD** na classe `GerenciadorBanco`
2. **Separação de Templates HTML** em um pacote dedicado
3. **Aplicação Web Flask** atualizada com suporte completo a Veículos e Usuários
4. **Interface responsiva** com design moderno

---

## 🔧 Novos Métodos no GerenciadorBanco

### Métodos de Atualização (UPDATE)

#### `atualizar_deteccao(id_deteccao, placa, tipo_placa, confianca)`
Atualiza os dados de uma detecção existente.

```python
from detectar_placas_video import GerenciadorBanco

db = GerenciadorBanco(usar_postgres=True)

# Atualizar apenas a confiança
db.atualizar_deteccao(1, confianca=0.99)

# Atualizar placa e tipo
db.atualizar_deteccao(1, placa="ABC1D23", tipo_placa="MERCOSUL_CARRO")

# Atualizar todos os campos
db.atualizar_deteccao(1, "ABC1D23", "MERCOSUL_CARRO", 0.99)
```

**Retorna:** `bool` - True se atualizado com sucesso, False caso contrário

---

### Métodos de Exclusão (DELETE)

#### `deletar_deteccao(id_deteccao)`
Deleta uma detecção específica pelo ID.

```python
# Deletar detecção com ID 5
sucesso = db.deletar_deteccao(5)

if sucesso:
    print("Detecção deletada com sucesso!")
```

**Retorna:** `bool` - True se deletado com sucesso

---

#### `deletar_deteccoes_por_placa(placa)`
Deleta TODAS as detecções de uma placa específica e retorna a quantidade deletada.

```python
# Deletar todas as detecções da placa ABC1234
quantidade = db.deletar_deteccoes_por_placa("ABC1234")
print(f"Foram deletadas {quantidade} detecções")
```

**Retorna:** `int` - Número de detecções deletadas

---

#### `deletar_deteccoes_por_data(data)`
Deleta todas as detecções de uma data específica (formato: YYYY-MM-DD).

```python
# Deletar detecções do dia 2025-12-09
quantidade = db.deletar_deteccoes_por_data("2025-12-09")
print(f"Foram deletadas {quantidade} detecções")
```

**Retorna:** `int` - Número de detecções deletadas

---

### Métodos de Leitura Avançados

#### `buscar_deteccao_por_id(id_deteccao)`
Busca uma detecção específica pelo ID.

```python
deteccao = db.buscar_deteccao_por_id(1)

if deteccao:
    print(f"Placa: {deteccao['placa']}")
    print(f"Confiança: {deteccao['confianca']:.2%}")
    print(f"Data: {deteccao['data_deteccao']}")
```

**Retorna:** `dict` ou `None`

---

#### `listar_todas_deteccoes(limite=100)`
Lista todas as detecções com limite.

```python
# Obter últimas 50 detecções
deteccoes = db.listar_todas_deteccoes(limite=50)

for det in deteccoes:
    print(f"{det['placa']} - {det['tipo_placa']} - {det['confianca']:.2%}")
```

**Retorna:** `List[Dict]` - Lista de detecções

---

#### `listar_deteccoes_por_tipo(tipo_placa)`
Lista todas as detecções de um tipo específico.

```python
# Listar apenas placas MERCOSUL de carros
deteccoes = db.listar_deteccoes_por_tipo("MERCOSUL_CARRO")

print(f"Total de placas MERCOSUL de carros: {len(deteccoes)}")
```

**Tipos disponíveis:**
- `MERCOSUL_CARRO`
- `MERCOSUL_MOTO`
- `ANTIGA_CARRO`
- `ANTIGA_MOTO`

**Retorna:** `List[Dict]` - Lista de detecções filtradas

---

## 📁 Estrutura de Templates HTML

A pasta `templates/` foi criada com os seguintes arquivos:

### Templates Base
- **`base.html`** - Template base com CSS e navegação
- **`index.html`** - Página inicial com estatísticas
- **`404.html`** - Página de erro 404
- **`500.html`** - Página de erro 500

### Templates de Detecções
- **`deteccoes.html`** - Listagem de detecções com busca
- **`editar_deteccao.html`** - Formulário para editar detecções

### Templates de Veículos
- **`veiculos.html`** - Listagem de veículos
- **`editar_veiculo.html`** - Formulário para criar/editar veículos

### Templates de Usuários
- **`usuarios.html`** - Listagem de usuários
- **`editar_usuario.html`** - Formulário para criar/editar usuários

### Templates de Relatórios
- **`relatorio.html`** - Relatório com gráficos e estatísticas

---

## 🌐 API REST - Rotas JSON

### Obter todas as detecções
```
GET /api/deteccoes
```

**Resposta:**
```json
{
  "sucesso": true,
  "total": 150,
  "deteccoes": [
    {
      "id": 1,
      "placa": "ABC1D23",
      "tipo_placa": "MERCOSUL_CARRO",
      "confianca": 0.99,
      "data_deteccao": "2025-12-09 14:30:00",
      "frame_numero": 100,
      "origem": "WEBCAM"
    }
  ]
}
```

### Filtrar por tipo
```
GET /api/deteccoes?tipo=MERCOSUL_CARRO
```

### Obter detecção específica
```
GET /api/deteccao/<id>
```

**Exemplo:**
```
GET /api/deteccao/1
```

**Resposta:**
```json
{
  "sucesso": true,
  "deteccao": {
    "id": 1,
    "placa": "ABC1D23",
    "tipo_placa": "MERCOSUL_CARRO",
    "confianca": 0.99,
    "data_deteccao": "2025-12-09 14:30:00",
    "frame_numero": 100,
    "origem": "WEBCAM"
  }
}
```

---

## 🚀 Como Usar

### 1. Instalar Dependências
```bash
pip install flask flask-wtf python-dotenv
```

### 2. Executar a Aplicação Web
```bash
python web_app_placas_v2.py
```

A aplicação estará disponível em: **http://localhost:5000**

### 3. Exemplo de Uso do GerenciadorBanco
```python
from detectar_placas_video import GerenciadorBanco

# Conectar ao banco
db = GerenciadorBanco(usar_postgres=True)

# Listar detecções
deteccoes = db.listar_todas_deteccoes(limite=50)
print(f"Total: {len(deteccoes)}")

# Buscar detecção específica
det = db.buscar_deteccao_por_id(1)
print(f"Placa: {det['placa']}")

# Atualizar detecção
db.atualizar_deteccao(1, placa="ABC1D23", confianca=0.99)

# Deletar detecção
db.deletar_deteccao(1)

# Deletar por placa
quantidade = db.deletar_deteccoes_por_placa("ABC1D23")
print(f"Deletadas {quantidade} detecções")

# Deletar por data
quantidade = db.deletar_deteccoes_por_data("2025-12-09")
print(f"Deletadas {quantidade} detecções do dia")

# Fechar conexão
db.fechar()
```

---

## 📊 Funcionalidades da Web App

### Dashboard (Home)
- Estatísticas em tempo real
- Total de detecções
- Detecções do dia
- Placas únicas

### Gerenciamento de Detecções
- Listar todas as detecções
- Buscar por placa
- Editar detecções
- Deletar detecções
- Paginação

### Gerenciamento de Veículos
- Criar novo veículo
- Editar informações
- Deletar veículo
- Campos: placa, proprietário, marca, modelo, cor, tipo

### Gerenciamento de Usuários
- Criar novo usuário
- Editar informações
- Deletar usuário
- Campos: nome, email, telefone, cargo, status

### Relatórios
- Gráficos de detecções
- Agrupamento por tipo
- Agrupamento por origem
- Detecções recentes

---

## 🎨 Design Responsivo

A interface foi desenvolvida com:
- **CSS Grid e Flexbox** para layouts responsivos
- **Paleta de cores moderna** (gradiente roxo)
- **Mobile-first approach**
- **Animações suaves**
- **Tabelas interativas**
- **Formulários validados**

---

## 🔒 Segurança

### Recomendações:

1. **Altere a chave secreta da aplicação:**
```python
app.config['SECRET_KEY'] = 'sua_chave_secreta_muito_segura_aqui'
```

2. **Use variáveis de ambiente:**
```python
import os
from dotenv import load_dotenv

load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
```

3. **Configure HTTPS em produção**

4. **Use um banco de dados seguro** (PostgreSQL recomendado)

---

## 📝 Notas Importantes

- A aplicação simula dados para Veículos e Usuários. Você precisa implementar as tabelas correspondentes no banco de dados.
- Os métodos de atualização/exclusão de veículos e usuários precisam ser implementados similar aos de detecções.
- Todos os campos de forma são validados no frontend e backend.

---

## 📞 Suporte

Para dúvidas ou problemas, consulte:
- Documentação do Flask: https://flask.palletsprojects.com/
- Documentação do PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- PostgreSQL: https://www.postgresql.org/docs/
- MySQL: https://dev.mysql.com/doc/

---

**Versão:** 2.0  
**Última atualização:** Dezembro 2025  
**Instituição:** IFSULDEMINAS
