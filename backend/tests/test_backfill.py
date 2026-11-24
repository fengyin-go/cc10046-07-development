"""补交批次结果集：按来源与采集日筛选、交付、回执与重查的端到端测试。"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.backfill import BackfillService
from app.store import store


@pytest.fixture(autouse=True)
def clean_store():
    store.reset()
    yield
    store.reset()


def service() -> BackfillService:
    return BackfillService()


def test_pending_candidates_are_scoped_by_source_and_date():
    svc = service()
    items, total, counts = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 2
    assert counts == {"pending": 2, "delivered": 0}
    assert [item["批次标识"] for item in items] == [
        "BATCH-20260410", "BATCH-20260411"]
    assert {item["来源配置"] for item in items} == {"来源-甲站"}


def test_same_batch_label_across_sources_never_crosses():
    svc = service()
    items, total, _ = svc.list_candidates(
        source="来源-乙站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 3
    assert [item["id"] for item in items] == [8, 6, 7]
    assert {item["来源配置"] for item in items} == {"来源-乙站"}


def test_full_label_search_filters_candidates():
    svc = service()
    items, total, _ = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11",
        batch="20260410")
    assert total == 1
    assert items[0]["批次标识"] == "BATCH-20260410"


def test_delivery_writes_receipts_and_moves_batches_out_of_pending():
    svc = service()
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
        "operator": "值班员",
    })
    assert result["ok"] is True
    assert result["实际送达批次数"] == 2
    assert result["未送达批次数"] == 0
    assert [item["批次标识"] for item in result["实际送达"]] == [
        "BATCH-20260410", "BATCH-20260411"]
    assert [(item["来源配置"], item["采集时间"]) for item in result["回执"]] == [
        ("来源-甲站", "2026-04-10"), ("来源-甲站", "2026-04-11")]

    remaining, total, counts = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 0
    assert remaining == []
    assert counts == {"pending": 0, "delivered": 2}

    receipts = svc.list_receipts(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert len(receipts) == 2
    assert {item["单号"] for item in receipts} == {result["单号"]}

    export_task = result["导出"]
    assert export_task["任务标识"] == f"补交-{result['单号']}"
    export_rows = store.rows("export_channel")
    assert export_rows[-1]["来源批次"] == "BATCH-20260410、BATCH-20260411"


def test_batch_label_of_another_source_is_rejected():
    svc = service()
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_labels": ["BATCH-20260409"],
    })
    assert result["ok"] is False
    assert result["实际送达批次数"] == 0
    assert "来源不符" in result["未送达"][0]["原因"]

    yi_items, _, _ = svc.list_candidates(
        source="来源-乙站", date_from="2026-04-09", date_to="2026-04-11")
    assert [item["id"] for item in yi_items] == [8, 6, 7]


def test_already_delivered_batch_is_not_delivered_twice():
    svc = service()
    svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
    })
    again = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4],
    })
    assert again["ok"] is False
    assert "已交付" in again["未送达"][0]["原因"]
    assert len(svc.list_receipts(source="来源-甲站")) == 2


def test_midway_failure_reenquery_separates_delivered_and_pending():
    svc = service()
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
        "fail_batch_ids": [5],
    })
    assert result["ok"] is True
    assert result["交付状态"] == "部分送达"
    assert [item["批次标识"] for item in result["实际送达"]] == ["BATCH-20260410"]
    assert [item["批次标识"] for item in result["未送达"]] == ["BATCH-20260411"]

    pending, total, counts = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 1
    assert pending[0]["批次标识"] == "BATCH-20260411"
    assert counts == {"pending": 1, "delivered": 1}

    everything, _, _ = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11",
        delivery_state="all")
    assert {item["批次标识"]: item["交付状态"] for item in everything} == {
        "BATCH-20260410": "已交付",
        "BATCH-20260411": "待补",
    }


def test_late_batch_enters_next_pending_list():
    svc = service()
    svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
    })
    late = svc.record_batch({
        "batch_label": "BATCH-20260409",
        "source": "来源-甲站",
        "collected_on": "2026-04-09",
        "row_count": 300,
        "valid_count": 299,
    })
    assert late["ok"] is True

    pending, total, counts = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 1
    assert pending[0]["批次标识"] == "BATCH-20260409"
    assert pending[0]["交付状态"] == "待补"
    assert counts == {"pending": 1, "delivered": 2}

    # 迟到批次只在甲站待补，乙站同名批次不受影响。
    yi_pending, yi_total, _ = svc.list_candidates(
        source="来源-乙站", date_from="2026-04-09", date_to="2026-04-11")
    assert yi_total == 3
    assert all(item["来源配置"] == "来源-乙站" for item in yi_pending)


def test_export_file_matches_delivered_receipts():
    svc = service()
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
    })
    delivery_id = int(result["交付记录"]["id"])
    csv_text = svc.export_csv_for_delivery(delivery_id)
    assert csv_text is not None
    lines = [line for line in csv_text.splitlines() if line.strip()]
    assert len(lines) == 3  # 表头 + 两批
    assert "BATCH-20260410" in lines[1]
    assert "BATCH-20260411" in lines[2]
    assert "来源-甲站" in lines[1]

    receipts = svc.receipts_for_delivery(delivery_id)
    assert [item["批次标识"] for item in receipts] == [
        "BATCH-20260410", "BATCH-20260411"]


def test_delivery_outside_window_is_rejected():
    svc = service()
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-10",
        "date_to": "2026-04-11",
        "batch_labels": ["BATCH-20260409"],
    })
    # 该标签只存在于乙站，甲站内不存在，按来源不符拒绝。
    assert result["ok"] is False
    late = svc.record_batch({
        "batch_label": "BATCH-20260409",
        "source": "来源-甲站",
        "collected_on": "2026-04-09",
    })
    assert late["ok"] is True
    window = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-10",
        "date_to": "2026-04-11",
        "batch_labels": ["BATCH-20260409"],
    })
    assert window["ok"] is False
    assert "早于本次补交范围" in window["未送达"][0]["原因"]


def test_ids_and_labels_together_do_not_count_as_failure():
    svc = service()
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4, 5],
        "batch_labels": ["BATCH-20260410", "BATCH-20260411"],
    })
    assert result["ok"] is True
    assert result["未送达批次数"] == 0
    assert [item["批次标识"] for item in result["实际送达"]] == [
        "BATCH-20260410", "BATCH-20260411"]


def test_deliver_all_matching_picks_up_late_batch():
    svc = service()
    svc.record_batch({
        "batch_label": "BATCH-20260409",
        "source": "来源-甲站",
        "collected_on": "2026-04-09",
    })
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "deliver_all_matching": True,
    })
    assert result["ok"] is True
    assert [item["批次标识"] for item in result["实际送达"]] == [
        "BATCH-20260409", "BATCH-20260410", "BATCH-20260411"]
    _, total, counts = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 0
    assert counts == {"pending": 0, "delivered": 3}


def test_deliver_all_matching_respects_window_and_source():
    svc = service()
    result = svc.deliver({
        "source": "来源-乙站",
        "date_from": "2026-04-10",
        "date_to": "2026-04-10",
        "deliver_all_matching": True,
    })
    assert [item["批次标识"] for item in result["实际送达"]] == ["BATCH-20260410"]
    assert result["实际送达"][0]["来源配置"] == "来源-乙站"


def test_duplicate_label_within_one_source_requires_batch_id():
    svc = service()
    svc.record_batch({
        "batch_label": "BATCH-20260410",
        "source": "来源-甲站",
        "collected_on": "2026-04-10",
    })
    by_label = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_labels": ["BATCH-20260410"],
    })
    assert by_label["ok"] is False
    assert "重复" in by_label["未送达"][0]["原因"]

    # 按批次ID可精确选择其中一份，另一份仍在待补。
    by_id = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4],
    })
    assert by_id["ok"] is True
    assert [item["批次标识"] for item in by_id["实际送达"]] == ["BATCH-20260410"]
    pending, _, _ = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert [item["id"] for item in pending] == [9, 5]


def test_labels_given_with_ids_do_not_pull_in_extra_batches():
    svc = service()
    svc.record_batch({
        "batch_label": "BATCH-20260410",
        "source": "来源-甲站",
        "collected_on": "2026-04-10",
    })
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "batch_ids": [4],
        "batch_labels": ["BATCH-20260410"],
    })
    assert result["ok"] is True
    assert [item["id"] for item in result["实际送达"]] == [4]
    pending, total, _ = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 2
    assert 9 in [item["id"] for item in pending]
    assert 5 in [item["id"] for item in pending]


def test_deliver_all_matching_honours_batch_label_filter():
    svc = service()
    svc.record_batch({
        "batch_label": "BATCH-20260409",
        "source": "来源-甲站",
        "collected_on": "2026-04-09",
    })
    result = svc.deliver({
        "source": "来源-甲站",
        "date_from": "2026-04-09",
        "date_to": "2026-04-11",
        "deliver_all_matching": True,
        "batch": "20260409",
    })
    assert result["ok"] is True
    assert [item["批次标识"] for item in result["实际送达"]] == ["BATCH-20260409"]
    pending, total, _ = svc.list_candidates(
        source="来源-甲站", date_from="2026-04-09", date_to="2026-04-11")
    assert total == 2


def test_batches_not_yet_stored_are_not_resendable():
    svc = service()
    # id=1 为「存储中」，id=3 为「校验未过」，都不应出现在可重发结果集里。
    items, total, _ = svc.list_candidates(
        source="结果存储样例1", delivery_state="all")
    assert total == 0
    assert items == []
    rejected = svc.deliver({
        "source": "结果存储样例1",
        "batch_ids": [1],
    })
    assert rejected["ok"] is False
    assert "尚未落库" in rejected["未送达"][0]["原因"]
