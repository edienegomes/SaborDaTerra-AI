"""Alocação conservadora de pedidos e geração de rascunhos por produtor."""

from collections import OrderedDict
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sabor_agent.data_tools import (
    DEFAULT_DATA_DIR,
    DataValidationError,
    find_producer_candidates,
)
from sabor_agent.formatters import format_producer_order_notification


_TRIAGE_STATUSES = {"pronto", "revisar", "bloqueado"}
_PRODUCTION_TYPES = {"convencional", "organico", "nao_informado"}


def build_producer_order_notifications(
    order: Mapping[str, Any],
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
) -> dict[str, Any]:
    """Aloca itens de um pedido triado e prepara rascunhos por produtor.

    Somente pedidos com status ``pronto`` são alocados. Um item é atribuído
    automaticamente apenas quando há exatamente um produtor ativo que oferece
    o produto; itens sem candidato ou com mais de um candidato ficam pendentes.
    Itens orgânicos exigem certificação ``sim`` válida até a data de entrega.
    A função usa a lista de produtos do cadastro, sem inferir estoque ou
    capacidade, e nunca envia mensagens.
    """
    if not isinstance(order, Mapping):
        raise DataValidationError("order deve ser um objeto de pedido triado.")

    status = _required_text(order.get("status"), "status").casefold()
    if status not in _TRIAGE_STATUSES:
        raise DataValidationError("status deve ser pronto, revisar ou bloqueado.")

    order_id = _optional_text(order.get("pedido_id"))
    raw_items = order.get("itens")
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list):
        raise DataValidationError("itens deve ser uma lista de itens triados.")

    if status != "pronto":
        return {
            "order_id": order_id,
            "status": status,
            "allocation_status": "not_ready",
            "drafts": [],
            "unresolved_items": [
                {
                    "item": _safe_item(item),
                    "reason": f"order_status_{status}",
                    "candidates": [],
                }
                for item in raw_items
            ],
        }

    if not raw_items:
        return {
            "order_id": order_id,
            "status": status,
            "allocation_status": "unallocated",
            "drafts": [],
            "unresolved_items": [],
        }

    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    unresolved = []
    deadline = _delivery_deadline(order.get("prazo"))

    for raw_item in raw_items:
        item = _safe_item(raw_item)
        if not isinstance(raw_item, Mapping):
            unresolved.append(
                {"item": item, "reason": "invalid_item", "candidates": []}
            )
            continue

        product = item["product"]
        quantity = item["quantity"]
        unit = item["unit"]
        if not product or quantity is None or not unit:
            unresolved.append(
                {"item": item, "reason": "incomplete_item", "candidates": []}
            )
            continue
        if not _positive_quantity(quantity):
            unresolved.append(
                {"item": item, "reason": "invalid_quantity", "candidates": []}
            )
            continue

        production = _optional_text(raw_item.get("producao"))
        if production is None:
            production = "nao_informado"
        production = _normalize_production(production)
        if production not in _PRODUCTION_TYPES:
            unresolved.append(
                {"item": item, "reason": "invalid_production_type", "candidates": []}
            )
            continue

        if production == "organico" and deadline is None:
            unresolved.append(
                {
                    "item": item,
                    "reason": "missing_delivery_date_for_organic",
                    "candidates": [],
                }
            )
            continue

        candidates = find_producer_candidates(
            product,
            organic_only=production == "organico",
            delivery_date=deadline if production == "organico" else None,
            data_dir=data_dir,
        )
        if len(candidates) != 1:
            unresolved.append(
                {
                    "item": item,
                    "reason": (
                        "no_eligible_organic_producer"
                        if not candidates and production == "organico"
                        else "no_active_producer"
                        if not candidates
                        else "multiple_active_producers"
                    ),
                    "candidates": candidates,
                }
            )
            continue

        producer = candidates[0]
        producer_id = producer["producer_id"]
        group = grouped.setdefault(
            producer_id,
            {
                "producer_id": producer_id,
                "producer_name": producer["producer_name"],
                "items": [],
            },
        )
        group["items"].append(
            {"product": product, "quantity": quantity, "unit": unit}
        )

    drafts = []
    for producer in grouped.values():
        message = format_producer_order_notification(
            producer["producer_name"],
            producer["items"],
            delivery_deadline=deadline,
            order_reference=order_id,
        )
        drafts.append({**producer, "message": message})

    if unresolved:
        allocation_status = "partial" if drafts else "unallocated"
    else:
        allocation_status = "complete"

    return {
        "order_id": order_id,
        "status": status,
        "allocation_status": allocation_status,
        "drafts": drafts,
        "unresolved_items": unresolved,
    }


def _safe_item(item: Any) -> dict[str, str | None]:
    if not isinstance(item, Mapping):
        return {"product": None, "quantity": None, "unit": None}
    return {
        "product": _optional_text(item.get("produto")),
        "quantity": _optional_text(item.get("quantidade")),
        "unit": _optional_text(item.get("unidade")),
    }


def _positive_quantity(value: str) -> bool:
    try:
        quantity = Decimal(value.replace(",", "."))
    except (InvalidOperation, ValueError):
        return False
    return quantity.is_finite() and quantity > 0


def _delivery_deadline(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return _optional_text(value.get("data_estimada"))


def _normalize_production(value: str) -> str:
    normalized = value.casefold().strip()
    if normalized == "orgânico":
        return "organico"
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise DataValidationError(f"{field} não pode estar vazio.")
    return text
