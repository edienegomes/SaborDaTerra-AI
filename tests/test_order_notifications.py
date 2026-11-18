import csv
import importlib
import importlib.util
import json

import pytest

from sabor_agent.data_tools import DataValidationError


PRODUCER_FIELDS = [
    "id",
    "nome_completo",
    "produtos",
    "certificacao_organica",
    "validade_certificacao",
    "status",
    "telefone",
    "cpf",
]


def _write_producers(data_dir, producers):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "produtores.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PRODUCER_FIELDS)
        writer.writeheader()
        writer.writerows(producers)
    return data_dir


def _producer(
    producer_id,
    name,
    products,
    *,
    organic="nao",
    certificate_expiry="2027-12-31",
    status="ativo",
):
    return {
        "id": producer_id,
        "nome_completo": name,
        "produtos": products,
        "certificacao_organica": organic,
        "validade_certificacao": certificate_expiry,
        "status": status,
        "telefone": "81999990000",
        "cpf": "12345678901",
    }


def _service():
    spec = importlib.util.find_spec("sabor_agent.notifications")
    assert spec is not None, "o serviço de rascunhos de notificação ainda não existe"
    module = importlib.import_module("sabor_agent.notifications")
    function = getattr(module, "build_producer_order_notifications", None)
    assert callable(function), "build_producer_order_notifications deve ser pública"
    return function


def _order(*items, status="pronto"):
    return {
        "pedido_id": "PED-2026-001",
        "status": status,
        "comprador": {"nome": "Comprador Confidencial", "contato": "81988887777"},
        "itens": list(items),
        "prazo": {"data_estimada": "2026-11-21", "texto_original": "sexta-feira"},
    }


def _item(product, quantity="5", unit="kg", *, production="convencional"):
    return {
        "produto": product,
        "quantidade": quantity,
        "unidade": unit,
        "producao": production,
    }


def test_unique_active_producer_gets_a_draft_without_personal_data(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer("P001", "Ana Silva", "mel silvestre", organic="sim"),
            _producer("P002", "Produtor Inativo", "mel silvestre", status="inativo"),
        ],
    )

    result = _service()(_order(_item("mel silvestre")), data_dir=data_dir)

    assert result["allocation_status"] == "complete"
    assert result["unresolved_items"] == []
    assert result["drafts"] == [
        {
            "producer_id": "P001",
            "producer_name": "Ana Silva",
            "items": [{"product": "mel silvestre", "quantity": "5", "unit": "kg"}],
            "message": (
                "Olá, Ana Silva!\n\n"
                "Há um novo pedido com os seguintes itens destinados a você:\n"
                "- mel silvestre — 5 kg\n"
                "Prazo de entrega: 2026-11-21\n"
                "Referência: PED-2026-001"
            ),
        }
    ]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "Comprador Confidencial" not in serialized
    assert "81988887777" not in serialized
    assert "81999990000" not in serialized
    assert "12345678901" not in serialized


def test_ambiguous_item_is_left_unallocated_with_active_candidates(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer("P001", "Ana Silva", "mel silvestre"),
            _producer("P002", "Beto Souza", "mel silvestre"),
        ],
    )

    result = _service()(_order(_item("mel silvestre")), data_dir=data_dir)

    assert result["allocation_status"] == "unallocated"
    assert result["drafts"] == []
    assert result["unresolved_items"] == [
        {
            "item": {"product": "mel silvestre", "quantity": "5", "unit": "kg"},
            "reason": "multiple_active_producers",
            "candidates": [
                {"producer_id": "P001", "producer_name": "Ana Silva"},
                {"producer_id": "P002", "producer_name": "Beto Souza"},
            ],
        }
    ]


def test_item_without_an_active_supplier_remains_unresolved(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [_producer("P001", "Produtor Inativo", "mel silvestre", status="inativo")],
    )

    result = _service()(_order(_item("mel silvestre")), data_dir=data_dir)

    assert result["drafts"] == []
    assert result["unresolved_items"][0]["reason"] == "no_active_producer"
    assert result["unresolved_items"][0]["candidates"] == []


def test_organic_item_only_matches_an_active_organically_certified_producer(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer("P001", "Ana Silva", "mel silvestre", organic="nao"),
            _producer("P002", "Beto Souza", "mel silvestre", organic="sim"),
        ],
    )

    result = _service()(
        _order(_item("mel silvestre", production="organico")), data_dir=data_dir
    )

    assert [draft["producer_id"] for draft in result["drafts"]] == ["P002"]
    assert result["allocation_status"] == "complete"


def test_organic_producer_certificate_must_cover_the_delivery_date(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer(
                "P001",
                "Ana Silva",
                "mel silvestre",
                organic="sim",
                certificate_expiry="2026-11-20",
            )
        ],
    )

    result = _service()(
        _order(_item("mel silvestre", production="organico")),
        data_dir=data_dir,
    )

    assert result["allocation_status"] == "unallocated"
    assert result["drafts"] == []
    assert result["unresolved_items"][0]["reason"] == "no_eligible_organic_producer"


def test_organic_certificate_expiring_on_delivery_date_is_still_valid(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer(
                "P001",
                "Ana Silva",
                "mel silvestre",
                organic="sim",
                certificate_expiry="2026-11-21",
            )
        ],
    )

    result = _service()(
        _order(_item("mel silvestre", production="organico")),
        data_dir=data_dir,
    )

    assert result["allocation_status"] == "complete"
    assert [draft["producer_id"] for draft in result["drafts"]] == ["P001"]


def test_organic_item_without_a_resolved_delivery_date_is_not_allocated(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [_producer("P001", "Ana Silva", "mel silvestre", organic="sim")],
    )
    order = _order(_item("mel silvestre", production="organico"))
    order["prazo"]["data_estimada"] = None

    result = _service()(order, data_dir=data_dir)

    assert result["drafts"] == []
    assert result["unresolved_items"][0]["reason"] == "missing_delivery_date_for_organic"


def test_organic_candidate_with_missing_certificate_expiry_is_a_data_error(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer(
                "P001",
                "Ana Silva",
                "mel silvestre",
                organic="sim",
                certificate_expiry="",
            )
        ],
    )

    with pytest.raises(DataValidationError, match="validade_certificacao"):
        _service()(
            _order(_item("mel silvestre", production="organico")),
            data_dir=data_dir,
        )


def test_items_for_the_same_producer_are_grouped_in_one_draft(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [_producer("P001", "Ana Silva", "tomate,mel silvestre")],
    )

    result = _service()(
        _order(_item("tomate", quantity="10"), _item("mel silvestre", quantity="2")),
        data_dir=data_dir,
    )

    assert len(result["drafts"]) == 1
    assert result["drafts"][0]["producer_id"] == "P001"
    assert result["drafts"][0]["items"] == [
        {"product": "tomate", "quantity": "10", "unit": "kg"},
        {"product": "mel silvestre", "quantity": "2", "unit": "kg"},
    ]
    assert result["drafts"][0]["message"].count("\n- ") == 2


def test_partial_allocation_drafts_only_items_with_one_eligible_producer(tmp_path):
    data_dir = _write_producers(
        tmp_path,
        [
            _producer("P001", "Ana Silva", "tomate"),
            _producer("P002", "Beto Souza", "mel silvestre"),
            _producer("P003", "Caio Lima", "mel silvestre"),
        ],
    )

    result = _service()(
        _order(_item("tomate"), _item("mel silvestre")), data_dir=data_dir
    )

    assert result["allocation_status"] == "partial"
    assert [draft["producer_id"] for draft in result["drafts"]] == ["P001"]
    assert result["drafts"][0]["items"] == [
        {"product": "tomate", "quantity": "5", "unit": "kg"}
    ]
    assert result["unresolved_items"][0]["item"]["product"] == "mel silvestre"


@pytest.mark.parametrize("status", ["revisar", "bloqueado"])
def test_non_ready_order_never_generates_drafts(tmp_path, status):
    data_dir = _write_producers(
        tmp_path, [_producer("P001", "Ana Silva", "mel silvestre")]
    )

    result = _service()(
        _order(_item("mel silvestre"), status=status), data_dir=data_dir
    )

    assert result["allocation_status"] == "not_ready"
    assert result["drafts"] == []
    assert result["unresolved_items"][0]["reason"] == f"order_status_{status}"


def test_item_with_incomplete_quantity_or_unit_is_not_allocated(tmp_path):
    data_dir = _write_producers(
        tmp_path, [_producer("P001", "Ana Silva", "mel silvestre")]
    )

    result = _service()(
        _order(_item("mel silvestre", quantity=None, unit="")), data_dir=data_dir
    )

    assert result["drafts"] == []
    assert result["unresolved_items"][0]["reason"] == "incomplete_item"
