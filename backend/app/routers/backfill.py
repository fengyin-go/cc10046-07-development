"""补交接口：待补批次查询、批次交付、回执与交付文件下载。

路由必须排在通用资源路由 /api/{module} 之前注册，避免动态路径抢先匹配。
"""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.backfill import backfill_service

router = APIRouter(prefix="/api/backfill", tags=["补交批次"])


@router.get("/sources")
def list_sources() -> dict[str, Any]:
    """可筛选的采集来源清单。"""
    return {"items": backfill_service.list_sources()}


@router.get("/candidates")
def list_candidates(
    source: str | None = Query(default=None),
    date_from: str | None = Query(default=None, alias="date_from"),
    date_to: str | None = Query(default=None, alias="date_to"),
    batch: str | None = Query(default=None),
    delivery_state: str = Query(default="pending"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """按来源与采集日筛选可重发批次结果集。"""
    items, total, counts = backfill_service.list_candidates(
        source=source,
        date_from=date_from,
        date_to=date_to,
        batch=batch,
        delivery_state=delivery_state,
        page=page,
        size=size,
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pending": counts["pending"],
        "delivered": counts["delivered"],
        "query": {
            "source": source or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "batch": batch or "",
            "delivery_state": delivery_state,
        },
    }


@router.post("/record")
def record_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """登记一份迟到的采集结果批次，写入后仍按原查询条件检索。"""
    return backfill_service.record_batch(payload)


@router.post("/deliver")
def deliver(payload: dict[str, Any]) -> dict[str, Any]:
    """提交补交：只交付实际选中的批次（或按当前条件全量交付），并返回逐批回执。"""
    return backfill_service.deliver(payload)


@router.get("/deliveries")
def list_deliveries(
    source: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    items, total = backfill_service.list_deliveries(
        source=source, date_from=date_from, date_to=date_to, page=page, size=size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/deliveries/{delivery_id}")
def get_delivery(delivery_id: int) -> dict[str, Any]:
    delivery = backfill_service.get_delivery(delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail=f"补交单 {delivery_id} 不存在")
    return delivery


@router.get("/deliveries/{delivery_id}/export.csv")
def export_delivery(delivery_id: int) -> StreamingResponse:
    csv_text = backfill_service.export_csv_for_delivery(delivery_id)
    if csv_text is None:
        raise HTTPException(status_code=404, detail=f"补交单 {delivery_id} 不存在")
    delivery = backfill_service.get_delivery(delivery_id)
    filename = f"backfill-{delivery['单号']}.csv"
    return StreamingResponse(
        io.BytesIO(csv_text.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/receipts")
def list_receipts(
    source: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    batch: str | None = Query(default=None),
    delivery_no: str | None = Query(default=None),
) -> dict[str, Any]:
    items = backfill_service.list_receipts(
        source=source,
        date_from=date_from,
        date_to=date_to,
        batch=batch,
        delivery_no=delivery_no,
    )
    return {"items": items, "total": len(items)}
