import inspect
import json

from sabor_agentes import tool


def test_tool_module_exposes_only_typed_documented_agent_tools():
    assert tool.TOOLS == [
        tool.get_producer_summary,
        tool.lookup_price,
        tool.lookup_lot,
        getattr(tool, "draft_producer_order_notifications", None),
    ]
    assert callable(getattr(tool, "draft_producer_order_notifications", None))

    for function in tool.TOOLS:
        assert function.__module__ == tool.__name__
        assert "Use quando" in function.__doc__
        assert all(
            parameter.annotation is not inspect.Parameter.empty
            for parameter in inspect.signature(function).parameters.values()
        )
        assert inspect.signature(function).return_annotation is dict

    order_type = inspect.signature(
        tool.draft_producer_order_notifications
    ).parameters["order"].annotation
    assert set(order_type.__annotations__) == {
        "pedido_id",
        "status",
        "itens",
        "prazo",
    }


def test_producer_summary_tool_forwards_one_producer_and_period(monkeypatch):
    expected = {
        "producer_id": "P001",
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "payments": {
            "paid": {"amount": "20.00", "transactions": 1},
            "pending": {"amount": "30.00", "transactions": 1},
            "unclassified": {"amount": "2.50", "transactions": 1},
        },
    }
    calls = []

    def fake_summary(producer_id, start_date, end_date):
        calls.append((producer_id, start_date, end_date))
        return expected

    monkeypatch.setattr(tool, "_get_producer_summary", fake_summary)

    result = tool.get_producer_summary("P001", "2026-10-01", "2026-10-31")

    assert calls == [("P001", "2026-10-01", "2026-10-31")]
    assert result is expected
    assert result["payments"]["pending"] == {"amount": "30.00", "transactions": 1}
    assert result["producer_id"] == "P001"
    assert result["period"] == {"start": "2026-10-01", "end": "2026-10-31"}


def test_price_tool_preserves_exact_matches_and_variants(monkeypatch):
    expected = {
        "query": "goiaba paluma",
        "period": "2026-10",
        "matches": [],
        "suggestions": [{"product": "goiaba paluma extra"}],
    }
    calls = []

    def fake_lookup(product_query):
        calls.append(product_query)
        return expected

    monkeypatch.setattr(tool, "_lookup_price", fake_lookup)

    result = tool.lookup_price("goiaba paluma")

    assert calls == ["goiaba paluma"]
    assert result is expected
    assert result["matches"] == []
    assert result["suggestions"] == [{"product": "goiaba paluma extra"}]


def test_lot_tool_returns_a_json_serializable_found_envelope(monkeypatch):
    lot = {"lot_id": "LOT-1", "producer_id": "P001", "product": "mel"}
    monkeypatch.setattr(tool, "_lookup_lot", lambda lot_id: lot)

    result = tool.lookup_lot("LOT-1")

    assert result == {"found": True, "lot_id": "LOT-1", "lot": lot}
    assert json.loads(json.dumps(result)) == result


def test_lot_tool_returns_a_json_serializable_not_found_envelope(monkeypatch):
    monkeypatch.setattr(tool, "_lookup_lot", lambda lot_id: None)

    result = tool.lookup_lot("LOT-MISSING")

    assert result == {"found": False, "lot_id": "LOT-MISSING", "lot": None}
    assert json.loads(json.dumps(result)) == result


def test_notification_tool_forwards_structured_triaged_order(monkeypatch):
    expected = {"allocation_status": "complete", "drafts": [], "unresolved_items": []}
    calls = []
    order = {"status": "pronto", "itens": []}

    def fake_draft(order_value):
        calls.append(order_value)
        return expected

    monkeypatch.setattr(tool, "_build_producer_order_notifications", fake_draft)

    result = tool.draft_producer_order_notifications(order)

    assert calls == [order]
    assert result is expected
