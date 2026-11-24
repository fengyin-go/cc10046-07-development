"""补交接口层测试：固定路由优先于通用资源路由，导出文件按回执生成。"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app
from app.store import store


@pytest.fixture()
def client():
    store.reset()
    with TestClient(app) as test_client:
        yield test_client
    store.reset()


def test_candidates_route_is_not_shadowed_by_resource_router(client):
    response = client.get("/api/backfill/candidates", params={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["pending"] == 2
    assert payload["delivered"] == 0


def test_sources_route(client):
    payload = client.get("/api/backfill/sources").json()
    assert "来源-甲站" in payload["items"]
    assert "来源-乙站" in payload["items"]


def test_deliver_then_export_and_receipts(client):
    payload = client.get("/api/backfill/candidates", params={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
    }).json()
    ids = [item["id"] for item in payload["items"]]

    delivered = client.post("/api/backfill/deliver", json={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": ids,
        "operator": "值班员",
    }).json()
    assert delivered["ok"] is True
    assert delivered["实际送达批次数"] == 2
    assert len(delivered["回执"]) == 2

    pending_after = client.get("/api/backfill/candidates", params={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
    }).json()
    assert pending_after["total"] == 0

    delivery_id = delivered["交付记录"]["id"]
    export = client.get(f"/api/backfill/deliveries/{delivery_id}/export.csv")
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    body = export.content.decode("utf-8-sig")
    assert "BATCH-20260410" in body and "BATCH-20260411" in body
    assert body.count("来源-甲站") == 2

    # 回执可按原查询条件回查，且只包含甲站。
    receipts = client.get("/api/backfill/receipts", params={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
    }).json()
    assert receipts["total"] == 2
    assert {item["来源配置"] for item in receipts["items"]} == {"来源-甲站"}


def test_export_route_still_works_for_regular_modules(client):
    response = client.get("/api/result_store/export", params={
        "来源配置": "来源-甲站"})
    assert response.status_code == 200
    assert "BATCH-20260410" in response.text


def test_late_batch_recorded_then_found_by_original_query(client):
    client.post("/api/backfill/deliver", json={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
    })
    created = client.post("/api/backfill/record", json={
        "batch_label": "BATCH-20260409",
        "source": "来源-甲站",
        "collected_on": "2026-04-09",
    }).json()
    assert created["ok"] is True

    payload = client.get("/api/backfill/candidates", params={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
    }).json()
    assert payload["total"] == 1
    assert payload["items"][0]["批次标识"] == "BATCH-20260409"


def test_result_store_list_and_export_support_window_and_delivery_state(client):
    payload = client.get("/api/result_store", params={
        "来源配置": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "delivery_state": "pending",
        "size": 200,
    }).json()
    assert payload["total"] == 2

    client.post("/api/backfill/deliver", json={
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4],
    })
    pending = client.get("/api/result_store", params={
        "来源配置": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "delivery_state": "pending",
        "size": 200,
    }).json()
    assert [item["批次标识"] for item in pending["items"]] == ["BATCH-20260411"]

    delivered = client.get("/api/result_store", params={
        "来源配置": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "delivery_state": "delivered",
        "size": 200,
    }).json()
    assert [item["批次标识"] for item in delivered["items"]] == ["BATCH-20260410"]

    export = client.get("/api/result_store/export", params={
        "来源配置": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "delivery_state": "pending",
    })
    assert export.status_code == 200
    body = export.text
    assert "BATCH-20260411" in body
    assert "BATCH-20260410" not in body
    assert "交付状态" in body.splitlines()[0]
