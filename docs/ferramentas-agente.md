# Ferramentas do agente

Este documento explica como consultar os dados estruturados pelo módulo `sabor_agent` e executar a demonstração local. A interface é independente de modelo e framework.

## Fluxo de chamada

1. `get_tool_definitions()` retorna as definições JSON Schema das ferramentas.
2. O chamador escolhe uma ferramenta e fornece seus argumentos estruturados.
3. `dispatch_tool(nome, argumentos)` valida a chamada e executa a ferramenta.
4. Para resultados tabulares, use o formatador correspondente para gerar uma resposta em português.

O despacho recebe uma chamada estruturada; ele não interpreta mensagens em linguagem natural nem decide a alocação de pedidos.

## Consultas tabulares do despacho local

| Nome | Argumentos obrigatórios | Uso |
|---|---|---|
| `get_producer_summary` | `producer_id`, `start_date`, `end_date` | Vendas e pagamentos do produtor no período inclusivo, com datas `AAAA-MM-DD`; usa o nome cadastrado quando disponível e mantém o ID como referência. |
| `lookup_price` | `product_query` | Preços da tabela de outubro de 2026. Retorna `matches` exatos e `suggestions` de variantes sem escolher uma. |
| `lookup_lot` | `lot_id` | Campos disponíveis para o lote. A API base retorna `None` quando não encontrado; o adaptador Cloud envolve o resultado em `{"found": false, "lot_id": ..., "lot": null}`. |

As três consultas estruturadas usam os CSVs locais. Preços e pagamentos são devolvidos conforme os dados, sem calcular descontos nem classificar pendências como atrasadas. As respostas de lote não incluem nome ou CPF do produtor.

## Adaptador para descoberta pelo agente

A branch Cloud configura o módulo `sabor_agentes.tool`. Esse adaptador publica em `TOOLS` quatro funções tipadas, documentadas e com retornos estruturados: `get_producer_summary`, `lookup_price`, `lookup_lot` e `draft_producer_order_notifications`. As três consultas tabulares delegam ao pacote `sabor_agent.data_tools`; a ferramenta de pedidos delega a `sabor_agent.notifications`. O `dispatch_tool` local continua oferecendo somente as três consultas tabulares.

O caminho padrão dos CSVs está configurado internamente em `sabor_agent.data_tools` (`data/processed/raw/documents/dados_csv/`), conforme a branch `integracao`. O adaptador não recebe caminho de arquivo como argumento, então o modelo não pode escolher diretórios ou arquivos.

### Resumo individual do produtor

`get_producer_summary(producer_id, start_date, end_date)` consulta um único produtor em um intervalo inclusivo e devolve vendas, quantidade, contagem de transações e valores/contagens de pagamentos `paid`, `pending` e `unclassified`. Ele não consolida produtores nem duplica o relatório agregado produzido pela equipe de Dados.

Trecho sintético usado nos testes para ilustrar os pagamentos retornados:

```json
{
  "producer_id": "P001",
  "period": {"start": "2026-10-01", "end": "2026-10-31"},
  "payments": {
    "paid": {"amount": "20.00", "transactions": 1},
    "pending": {"amount": "30.00", "transactions": 1},
    "unclassified": {"amount": "2.50", "transactions": 1}
  }
}
```

Os valores acima são de um cenário sintético dos testes; os resultados reais dependem das linhas encontradas nos CSVs.

### Saída do adaptador de lotes

`lookup_lot(lot_id)` sempre devolve um objeto JSON com `found`, `lot_id` e `lot`. Quando encontra o lote, `lot` contém os campos operacionais disponíveis; quando não encontra, retorna `found: false` e `lot: null`. Nome e CPF do produtor continuam omitidos.

### Exemplo de uso e limites

```python
from sabor_agentes.tool import TOOLS, get_producer_summary

# TOOLS é a lista descoberta pelo carregador da branch Cloud.
assert get_producer_summary in TOOLS

summary = get_producer_summary("P001", "2026-10-01", "2026-10-31")
pagamentos_pendentes = summary["payments"]["pending"]
```

`lookup_price` mantém `matches` e `suggestions` separados e não escolhe variantes. `draft_producer_order_notifications` também está em `TOOLS`; recebe o resultado estruturado da triagem, aloca somente correspondências sem ambiguidade e prepara rascunhos por produtor.

## Comportamento esperado das respostas

### Resumo do produtor

- **Entrada:** `producer_id`, `start_date` e `end_date`. As datas usam `AAAA-MM-DD` e o intervalo inclui os dois extremos.
- **Cálculo:** considera somente linhas de venda do produtor no período. `total_sales` e `total_quantity_kg` somam os campos do `financeiro.csv`; os pagamentos são separados por `status_pagamento` (`pago`, `pendente` e `unclassified` para qualquer outro valor).
- **Saída:** ID e nome cadastrado do produtor, período consultado, quantidade de transações, total vendido, quantidade registrada, valores e contagens por status de pagamento e arquivo-fonte.
- **Produtor existente sem vendas no período:** informar que não há vendas no intervalo e mostrar totais e contagens iguais a zero.
- **Produtor desconhecido:** informar que o produtor não foi encontrado; não apresentar isso como um relatório zerado.
- **Data inválida, intervalo invertido ou arquivo ausente/inválido:** informar o erro e pedir correção ou revisão; não substituir erro por zero.
- **Limites:** o resumo não classifica pagamentos como atrasados e não inclui pedidos alocados. Pedidos não são vendas e só podem ser incluídos quando outra etapa fornecer uma alocação confirmada.

### Consulta de preços

- **Entrada:** nome do produto em `product_query`.
- A busca ignora maiúsculas/minúsculas e acentos. Retorna produtos de nome normalizado idêntico em `matches` e variantes cujo nome começa com a consulta em `suggestions`; não é uma busca aproximada geral.
- **Correspondência exata:** apresentar o nome completo, unidade, preços e observações disponíveis. Mostrar descontos e volume mínimo exatamente como informados, sem calcular um preço descontado.
- **Somente variantes:** a ferramenta e seu formatador apresentam que não houve correspondência exata e listam todas as variantes pelo nome completo. Não selecionam nem confirmam um preço. A decisão de perguntar ao usuário qual variante deseja consultar pertence ao comportamento conversacional definido pela função de Prompt/Parser.
- **Nenhuma correspondência ou variante:** dizer que o produto não foi encontrado na tabela consultada; não chutar produto ou preço.
- Identificar sempre o período `2026-10`. Não apresentar esses valores como atuais para outro período.

### Consulta de lote

- **Entrada:** `lot_id`; a comparação ignora maiúsculas/minúsculas e espaços nas extremidades.
- **Lote encontrado:** apresentar o ID e somente os campos disponíveis: datas de colheita e entrega, ID do produtor, produto, quantidade, comprador, pedido, temperatura de transporte, validade, inspeção e observações. Informar `lotes.csv` como fonte.
- Omitir nome e CPF do produtor. Não completar campos ausentes por inferência.
- **Lote não encontrado:** responder “Lote não encontrado.”
- **ID duplicado ou dados inválidos:** informar que a base precisa de revisão; não escolher um dos registros.

### Rascunho de notificação ao produtor

`format_producer_order_notification` é o formatador local. `build_producer_order_notifications` recebe o objeto estruturado retornado pela triagem, consulta `produtores.csv` e gera os rascunhos. O fluxo não interpreta a mensagem original e não envia mensagens.

- Só processa pedidos com status `pronto`; `revisar` e `bloqueado` não geram rascunhos.
- Compara o produto triado com a lista `produtos` do cadastro, considerando apenas produtores `ativos`. Para itens `organico`, exige `certificacao_organica = sim` e `validade_certificacao` igual ou posterior à data estimada de entrega (`prazo.data_estimada`).
- Sem data estimada, o item orgânico fica pendente. Certificado vencido não é elegível; certificado ausente ou inválido gera erro de validação da base, em vez de alocação presumida.
- Aloca automaticamente apenas quando há exatamente um candidato. Sem candidato ou com vários, devolve o item em `unresolved_items` para revisão; não presume estoque nem capacidade de entrega.
- Para alocações parciais, produz rascunhos somente para os itens que tiveram um único produtor elegível. Cada produtor recebe um rascunho agrupado com seus itens.
- Não usa dados de contato, CPF, dados bancários, chave Pix ou informações pessoais do comprador. O retorno é JSON com `drafts`, `unresolved_items`, `status` e `allocation_status`.

```text
Olá, [nome do produtor]!

Há um novo pedido com os seguintes itens destinados a você:
- [produto] — [quantidade] [unidade]
- [produto] — [quantidade] [unidade]

Prazo de entrega: [prazo confirmado]
Referência: [identificador do pedido, se disponível]
[instrução de confirmação, se definida pela cooperativa]
```

Se o pedido não estiver pronto, ou se faltar produto, quantidade, unidade ou um produtor único elegível, não produzir rascunho para o item; devolver a lacuna em `unresolved_items`. O resultado é somente um rascunho. A ferramenta não consulta contato, não escolhe canal e não envia mensagens. Não incluir CPF, dados bancários, chave Pix ou dados pessoais do comprador.

Exemplo com um pedido triado estruturado. `comprador` pode estar presente no objeto de origem, mas seus dados não são copiados para o rascunho:

```python
from sabor_agentes.tool import draft_producer_order_notifications

resultado = draft_producer_order_notifications(
    {
        "pedido_id": "PED-EXEMPLO-001",
        "status": "pronto",
        "itens": [
            {
                "produto": "queijo coalho",
                "quantidade": 30,
                "unidade": "kg",
                "producao": "convencional",
            }
        ],
        "prazo": {"data_estimada": "2026-11-21"},
    }
)
rascunhos = resultado["drafts"]
itens_pendentes = resultado["unresolved_items"]
```

O helper `format_producer_order_notification` continua disponível para formatação direta quando a alocação já foi informada por outro chamador. A ferramenta registrada executa a consulta conservadora do cadastro antes de chamar esse helper.

## Exemplos de respostas esperadas

- **Produtor cadastrado sem vendas no intervalo:** apresentar o período, totais iguais a zero e a fonte `financeiro.csv`; não dizer que o produtor não existe.
- **Produtor desconhecido:** “Produtor [ID] não encontrado.”
- **Busca de preço com variantes:** “Não encontrei correspondência exata para [consulta]. Variantes disponíveis: [lista com nomes completos e valores da fonte].” A ferramenta não escolhe uma variante.
- **Busca de preço sem resultado:** “Não encontrei [produto] na tabela de preços de outubro de 2026.”
- **Lote inexistente:** “Lote não encontrado.”
- **Pedido em revisão/bloqueado, item sem produtor ou com vários candidatos:** não gerar rascunho para esse item; retornar o motivo e os candidatos elegíveis, quando houver, em `unresolved_items`.

## Chamar as ferramentas em Python

```python
from sabor_agent import (
    dispatch_tool,
    format_lot_lookup,
    format_price_lookup,
    format_producer_summary,
    get_tool_definitions,
)

# Catálogo independente de provedor ou framework.
definitions = get_tool_definitions()

# Resumo financeiro.
summary = dispatch_tool(
    "get_producer_summary",
    {
        "producer_id": "P001",
        "start_date": "2026-09-01",
        "end_date": "2026-10-31",
    },
)
print(format_producer_summary(summary))

# Preço: variantes aparecem separadas para confirmação.
price = dispatch_tool("lookup_price", {"product_query": "goiaba paluma"})
print(format_price_lookup(price))

# Rastreabilidade por ID.
lot = dispatch_tool("lookup_lot", {"lot_id": "LOT-2026-0089"})
print(format_lot_lookup(lot))
```

`dispatch_tool` aceita também o argumento opcional `data_dir`, caso os CSVs estejam em outra pasta:

```python
summary = dispatch_tool(
    "get_producer_summary",
    {
        "producer_id": "P001",
        "start_date": "2026-09-01",
        "end_date": "2026-10-31",
    },
    data_dir="caminho/para/dados_csv",
)
```

Argumentos ausentes, inesperados ou ferramenta desconhecida geram `ToolDispatchError`. Os erros de validação e de dados das consultas tabulares são definidos em `sabor_agent.data_tools`.

## Executar a demonstração local

Na raiz do repositório, rode:

```powershell
python -m scripts.demo_data_tools
```

O script chama as três ferramentas tabulares e imprime seus resultados em JSON. Os argumentos opcionais são `--producer`, `--start`, `--end`, `--product`, `--lot` e `--data-dir`. Para ver os valores padrão e a sintaxe:

```powershell
python -m scripts.demo_data_tools --help
```

Por padrão, os CSVs são lidos de `data/processed/raw/documents/dados_csv/`, presente na branch `integracao`. Em uma branch/checkout que ainda não recebeu essa pasta, use `--data-dir source/Facepe` para executar a demonstração com os arquivos locais. `source/` deve permanecer ignorada pelo Git e seus dados não devem ser enviados ao repositório.

## Testes locais

Para executar os testes das consultas, despacho, formatação, alocação de pedidos e adaptador Cloud:

```powershell
python -m pytest tests/test_data_tools.py tests/test_orchestrator.py tests/test_formatters.py tests/test_order_notifications.py tests/test_sabor_agentes_tool.py -q
```
