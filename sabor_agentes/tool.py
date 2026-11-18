"""Adaptador público das ferramentas de relatórios, consultas e pedidos."""

from typing import Literal, TypedDict

from sabor_agent.data_tools import (
    get_producer_summary as _get_producer_summary,
    lookup_lot as _lookup_lot,
    lookup_price as _lookup_price,
)
from sabor_agent.notifications import (
    build_producer_order_notifications as _build_producer_order_notifications,
)


class TriagedOrderItem(TypedDict):
    """Campos da triagem que podem participar da alocação de um item."""

    produto: str
    quantidade: str | int | float | None
    unidade: str | None
    producao: Literal["convencional", "organico", "nao_informado"]


class TriagedOrderDeadline(TypedDict):
    """Prazo resolvido pela triagem, quando disponível."""

    data_estimada: str | None
    texto_original: str | None


class TriagedOrder(TypedDict):
    """Campos consumidos da estrutura de PedidoTriado."""

    pedido_id: str | None
    status: Literal["pronto", "revisar", "bloqueado"]
    itens: list[TriagedOrderItem]
    prazo: TriagedOrderDeadline


def get_producer_summary(producer_id: str, start_date: str, end_date: str) -> dict:
    """Consulta vendas e pagamentos de um produtor em um período inclusivo.

    Use quando a pessoa pedir um relatório financeiro de produtor. Informe o ID
    do produtor e as datas inicial e final no formato AAAA-MM-DD.
    """
    return _get_producer_summary(producer_id, start_date, end_date)


def lookup_price(product_query: str) -> dict:
    """Consulta os preços de outubro de 2026 para um produto.

    Use quando a pessoa perguntar o preço de um produto. A resposta separa
    correspondências exatas de variantes; não escolha uma variante nem calcule
    descontos.
    """
    return _lookup_price(product_query)


def lookup_lot(lot_id: str) -> dict:
    """Consulta os dados registrados de rastreabilidade de um lote.

    Use quando a pessoa perguntar sobre um lote específico. Retorna somente os
    campos operacionais disponíveis, sem nome ou CPF do produtor. A chave
    ``found`` informa se o lote existe; quando não existe, ``lot`` é None.
    """
    lot = _lookup_lot(lot_id)
    return {"found": lot is not None, "lot_id": lot_id, "lot": lot}


def draft_producer_order_notifications(order: TriagedOrder) -> dict:
    """Gera rascunhos por produtor a partir de um pedido estruturado e triado.

    Use quando um pedido tiver sido extraído e validado pela ferramenta de
    triagem. Somente o status ``pronto`` pode gerar rascunhos. A ferramenta só
    aloca quando existe um produtor ativo único para o produto; ambiguidades e
    itens sem candidato retornam em ``unresolved_items``. Não consulta estoque
    nem envia mensagens.

    Args:
        order: Objeto estruturado com ``pedido_id``, ``status``, ``itens`` e
            ``prazo``, conforme os campos publicados pela ferramenta de triagem.
    """
    return _build_producer_order_notifications(order)


TOOLS = [
    get_producer_summary,
    lookup_price,
    lookup_lot,
    draft_producer_order_notifications,
]
