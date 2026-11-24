"""可重发批次结果集：按来源与采集日筛选待补批次，交付后落回执并移出待补范围。

约定：
- 批次数据仍住在 result_store，交付状态以附加字段写在批次行上；
- 补交单和回执放在 store 的内部表里，不参与 18 个业务模块的统计；
- 来源配置按“精确值”校验，批次标签相同的两个来源不会互相串批；
- 回执快照保存实际送出时的来源和采集日，交付文件只由回执生成。
"""
from __future__ import annotations

import csv
import io
import time
from typing import Any, Iterable

from app.store import store

BATCH_MODULE = "result_store"
DELIVERY_TABLE = "backfill_delivery"
RECEIPT_TABLE = "backfill_receipt"

PENDING = "待补"
DELIVERED = "已交付"

# 只有真正落库（或已归档但仍在库）的批次才可重发；
# 存储中 / 校验未过的批次不出现在可重发结果集里，也不能被补交提交。
RESENDABLE_STORAGE_STATES = {"已落库", "已归档"}
BLOCKED = "未就绪"

EXPORT_HEADERS = [
    "回执号", "单号", "批次标识", "来源配置", "采集时间",
    "原始行数", "有效行数", "存储路径", "校验摘要", "送达时间",
]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _date(value: Any) -> str:
    return _text(value)[:10]


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _csv_safe(value: Any) -> Any:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else value


def _delivery_state(row: dict[str, Any]) -> str:
    return _text(row.get("交付状态")) or PENDING


class BackfillService:
    """补交领域服务：待补查询、批次交付、回执与交付文件。"""

    # ---------- 数据访问 ----------

    def _batches(self) -> list[dict[str, Any]]:
        return store.rows(BATCH_MODULE)

    def _deliveries(self) -> list[dict[str, Any]]:
        return store.internal_rows(DELIVERY_TABLE)

    def _receipts(self) -> list[dict[str, Any]]:
        return store.internal_rows(RECEIPT_TABLE)

    # ---------- 待补批次结果集 ----------

    @staticmethod
    def _batch_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row.get("id", 0)),
            "批次标识": row.get("批次标识", ""),
            "来源配置": row.get("来源配置", ""),
            "采集时间": row.get("采集时间", ""),
            "原始行数": row.get("原始行数", ""),
            "有效行数": row.get("有效行数", ""),
            "存储路径": row.get("存储路径", ""),
            "压缩格式": row.get("压缩格式", ""),
            "校验摘要": row.get("校验摘要", ""),
            "存储状态": row.get("status", ""),
            "交付状态": _delivery_state(row),
            "补交单号": row.get("补交单号", ""),
            "交付时间": row.get("交付时间", ""),
        }

    @staticmethod
    def _normalise_state(value: str | None) -> str:
        state = _text(value)
        if state in {"", "pending", "待补"}:
            return "pending"
        if state in {"delivered", "已交付"}:
            return "delivered"
        return "all"

    def list_candidates(
        self,
        *,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        batch: str | None = None,
        delivery_state: str | None = "pending",
        page: int = 1,
        size: int = 200,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        """返回来源 + 采集日窗口内的可重发批次结果集。

        `batch` 对完整批次标签做包含检索；`delivery_state` 区分待补 / 已交付 / 全部。
        已交付批次默认不进入待补范围。
        """
        state_filter = self._normalise_state(delivery_state)
        wanted_source = _text(source)
        from_date = _date(date_from)
        to_date = _date(date_to)
        keyword = _text(batch).casefold()

        pending: list[dict[str, Any]] = []
        delivered: list[dict[str, Any]] = []
        for row in self._batches():
            if wanted_source and _text(row.get("来源配置")) != wanted_source:
                continue
            collected = _date(row.get("采集时间"))
            if from_date and collected < from_date:
                continue
            if to_date and collected > to_date:
                continue
            if keyword and keyword not in _text(row.get("批次标识")).casefold():
                continue
            if _text(row.get("status")) not in RESENDABLE_STORAGE_STATES:
                continue
            if _delivery_state(row) == DELIVERED:
                delivered.append(row)
            else:
                pending.append(row)

        counts = {"pending": len(pending), "delivered": len(delivered)}
        if state_filter == "pending":
            rows = pending
        elif state_filter == "delivered":
            rows = delivered
        else:
            rows = [*pending, *delivered]
        rows.sort(key=lambda item: (
            _date(item.get("采集时间")),
            _text(item.get("批次标识")).casefold(),
            int(item.get("id", 0)),
        ))
        total = len(rows)
        start = max(page - 1, 0) * max(size, 1)
        return [self._batch_view(row) for row in rows[start:start + size]], total, counts

    def list_sources(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for row in self._batches():
            name = _text(row.get("来源配置"))
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def record_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """登记一份新落库的采集结果批次（供迟到批次演练用）。

        新批次默认处于待补状态，写入后按原条件重查即可看到它与先前选中的批次同时出现。
        """
        label = _text(payload.get("batch_label") or payload.get("批次标识"))
        source = _text(payload.get("source") or payload.get("来源配置"))
        collected = _date(payload.get("collected_on") or payload.get("采集时间"))
        if not label or not source or not collected:
            return {"ok": False, "message": "批次标识、来源配置、采集时间均为必填"}
        rows = self._batches()
        entry = {
            "id": _next_id(rows),
            "批次标识": label,
            "来源配置": source,
            "采集时间": collected,
            "原始行数": str(payload.get("row_count", 0)),
            "有效行数": str(payload.get("valid_count", 0)),
            "存储路径": f"/data/results/{label}.json.gz",
            "压缩格式": "gzip",
            "校验摘要": f"md5:{label[-8:]}",
            "status": "已落库",
            "pending": False,
            "abnormal": False,
            "交付状态": PENDING,
        }
        rows.append(entry)
        return {"ok": True, "message": f"批次 {label} 已落库", "entry": self._batch_view(entry)}

    # ---------- 补交交付 ----------

    def deliver(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = _text(payload.get("source") or payload.get("来源配置"))
        date_from = _date(payload.get("date_from") or payload.get("采集起日"))
        date_to = _date(payload.get("date_to") or payload.get("采集止日"))
        operator = _text(payload.get("operator") or payload.get("操作人")) or "值班员"
        batch_ids = list(payload.get("batch_ids") or [])
        batch_labels = list(payload.get("batch_labels") or [])
        deliver_all = bool(payload.get("deliver_all_matching") or payload.get("全量交付"))
        fail_ids = {
            int(value) for value in (payload.get("fail_batch_ids") or [])
            if str(value).strip().lstrip("-").isdigit()
        }

        if not source:
            inferred = {
                _text(row.get("来源配置")) for row in self._batches()
                if any(str(row.get("id")) == str(value) for value in batch_ids)
            }
            if len(inferred) == 1:
                source = inferred.pop()
        if not source:
            return self._reject("请先指定采集来源（来源配置）")
        if date_from and date_to and date_from > date_to:
            return self._reject("采集起日不能晚于采集止日")

        if deliver_all:
            # 全量模式：按当前来源 + 采集日窗口 + 批次标签重新取待补集合，
            # 查询后迟到的批次会一并进入本次送出范围。
            matched, _, _ = self.list_candidates(
                source=source,
                date_from=date_from,
                date_to=date_to,
                batch=_text(payload.get("batch") or payload.get("批次标签")),
                delivery_state="pending",
                page=1,
                size=1_000_000,
            )
            batch_ids = [item["id"] for item in matched]
            batch_labels = []

        if not batch_ids and not batch_labels:
            if deliver_all:
                return self._reject("当前来源与采集日范围内没有待补批次")
            return self._reject("请先选择待补批次")

        batches = self._batches()
        requested: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        seen: set[int] = set()

        def record_failure(label: str, reason: str, row: dict[str, Any] | None = None) -> None:
            failures.append({
                "批次标识": label,
                "来源配置": _text(row.get("来源配置")) if row else "",
                "采集时间": _date(row.get("采集时间")) if row else "",
                "原因": reason,
            })

        for raw_id in batch_ids:
            try:
                batch_id = int(raw_id)
            except (TypeError, ValueError):
                record_failure(_text(raw_id), "批次ID无效")
                continue
            row = next(
                (item for item in batches if int(item.get("id", 0)) == batch_id), None)
            if row is None:
                record_failure(f"#{batch_id}", "批次不存在，可能已归档")
                continue
            if batch_id in seen:
                continue
            seen.add(batch_id)
            requested.append(row)

        # 显式按批次ID提交时，批次标签只作展示，不再二次解析，
        # 避免同一来源内同名标签把未选中的批次带进本次送出集合。
        labels_to_resolve = [] if batch_ids else batch_labels
        for raw_label in labels_to_resolve:
            label = _text(raw_label)
            if not label:
                continue
            matches = [
                item for item in batches
                if _text(item.get("批次标识")).casefold() == label.casefold()
            ]
            own = [item for item in matches if _text(item.get("来源配置")) == source]
            if not own:
                record_failure(
                    label,
                    "来源不符：该批次标签不属于所选来源",
                    matches[0] if matches else None,
                )
                continue
            outstanding = [
                item for item in own if int(item.get("id", 0)) not in seen]
            if not outstanding:
                # 该标签对应的批次已按批次ID选入，不重复记失败。
                continue
            if len(own) > 1:
                record_failure(label, "批次标签在所选来源内重复，请按批次ID选择")
                continue
            row = outstanding[0]
            seen.add(int(row.get("id", 0)))
            requested.append(row)

        if not requested:
            return {
                "ok": False,
                "message": "没有可提交的批次：" + "；".join(
                    f"{item['批次标识']}（{item['原因']}）" for item in failures),
                "实际送达批次数": 0,
                "未送达批次数": len(failures),
                "实际送达": [],
                "未送达": failures,
                "回执": [],
            }

        accepted: list[dict[str, Any]] = []
        for row in requested:
            row_source = _text(row.get("来源配置"))
            if row_source != source:
                record_failure(
                    _text(row.get("批次标识")),
                    f"来源不符：属于「{row_source}」，本次来源为「{source}」",
                    row,
                )
                continue
            if _text(row.get("status")) not in RESENDABLE_STORAGE_STATES:
                record_failure(
                    _text(row.get("批次标识")),
                    f"批次存储状态为「{_text(row.get('status')) or '未知'}」，尚未落库不可补交",
                    row,
                )
                continue
            collected = _date(row.get("采集时间"))
            if date_from and collected < date_from:
                record_failure(
                    _text(row.get("批次标识")), "采集日早于本次补交范围", row)
                continue
            if date_to and collected > date_to:
                record_failure(
                    _text(row.get("批次标识")), "采集日晚于本次补交范围", row)
                continue
            if _delivery_state(row) == DELIVERED:
                record_failure(
                    _text(row.get("批次标识")),
                    f"已交付（{_text(row.get('补交单号')) or '历史单'}），无需重复补交",
                    row,
                )
                continue
            if int(row.get("id", 0)) in fail_ids:
                record_failure(_text(row.get("批次标识")), "模拟发送失败", row)
                continue
            accepted.append(row)

        delivery_no = self._next_delivery_no()
        now = _now()
        delivered_views: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []

        for index, row in enumerate(accepted, start=1):
            receipt_no = f"RCPT-{delivery_no}-{index:02d}"
            receipt = {
                "id": _next_id(self._receipts()),
                "回执号": receipt_no,
                "单号": delivery_no,
                "批次ID": int(row.get("id", 0)),
                "批次标识": row.get("批次标识", ""),
                "来源配置": row.get("来源配置", ""),
                "采集时间": _date(row.get("采集时间")),
                "原始行数": row.get("原始行数", ""),
                "有效行数": row.get("有效行数", ""),
                "存储路径": row.get("存储路径", ""),
                "校验摘要": row.get("校验摘要", ""),
                "送达状态": "已送达",
                "送达时间": now,
            }
            self._receipts().append(receipt)
            receipts.append(receipt)

            row["交付状态"] = DELIVERED
            row["补交单号"] = delivery_no
            row["交付时间"] = now

            view = self._batch_view(row)
            view["回执号"] = receipt_no
            delivered_views.append(view)

        delivery = {
            "id": _next_id(self._deliveries()),
            "单号": delivery_no,
            "来源配置": source,
            "采集起日": date_from,
            "采集止日": date_to,
            "操作人": operator,
            "提交时间": now,
            "提交批次数": len(requested),
            "提交批次": "、".join(_text(row.get("批次标识")) for row in requested),
            "实际送达批次数": len(delivered_views),
            "实际送达批次": "、".join(item["批次标识"] for item in delivered_views),
            "未送达批次数": len(failures),
            "未送达批次": "、".join(item["批次标识"] for item in failures),
            "状态": (
                "全部送达" if delivered_views and not failures
                else "部分送达" if delivered_views
                else "全部失败"
            ),
            "导出任务": "",
        }

        export_task: dict[str, Any] | None = None
        if delivered_views:
            export_task = self._create_export_task(delivery, receipts)
            delivery["导出任务"] = export_task["任务标识"]
        self._deliveries().append(delivery)

        if delivered_views and not failures:
            message = f"补交完成，实际送出 {len(delivered_views)} 批"
        elif delivered_views:
            message = (
                f"补交部分完成，实际送出 {len(delivered_views)} 批，"
                f"{len(failures)} 批未送达"
            )
        else:
            message = "补交未送出任何批次：" + "；".join(
                f"{item['批次标识']}（{item['原因']}）" for item in failures)

        return {
            "ok": bool(delivered_views),
            "message": message,
            "单号": delivery_no,
            "来源配置": source,
            "采集起日": date_from,
            "采集止日": date_to,
            "交付状态": delivery["状态"],
            "提交批次数": len(requested),
            "实际送达批次数": len(delivered_views),
            "未送达批次数": len(failures),
            "实际送达": delivered_views,
            "未送达": failures,
            "回执": receipts,
            "导出": export_task,
            "交付记录": delivery,
            "查询条件": {
                "source": source,
                "date_from": date_from,
                "date_to": date_to,
            },
        }

    @staticmethod
    def _reject(message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "message": message,
            "实际送达批次数": 0,
            "未送达批次数": 0,
            "实际送达": [],
            "未送达": [],
            "回执": [],
        }

    # ---------- 补交单 / 回执 / 交付文件 ----------

    def _next_delivery_no(self) -> str:
        serial = max(
            (int(row.get("id", 0)) for row in self._deliveries()), default=0) + 1
        return f"BF-{time.strftime('%Y%m%d')}-{serial:04d}"

    def list_deliveries(
        self,
        *,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        wanted_source = _text(source)
        from_date = _date(date_from)
        to_date = _date(date_to)
        rows = [
            dict(row) for row in self._deliveries()
            if (not wanted_source or _text(row.get("来源配置")) == wanted_source)
            and (not from_date or _date(row.get("采集起日")) >= from_date)
            and (not to_date or _date(row.get("采集止日")) <= to_date)
        ]
        rows.sort(key=lambda item: int(item.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * max(size, 1)
        return rows[start:start + size], total

    def get_delivery(self, delivery_id: int) -> dict[str, Any] | None:
        delivery = next(
            (dict(row) for row in self._deliveries()
             if int(row.get("id", 0)) == int(delivery_id)),
            None,
        )
        if delivery is None:
            return None
        delivery["回执"] = [
            dict(row) for row in self._receipts()
            if row.get("单号") == delivery.get("单号")
        ]
        return delivery

    def list_receipts(
        self,
        *,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        batch: str | None = None,
        delivery_no: str | None = None,
    ) -> list[dict[str, Any]]:
        wanted_source = _text(source)
        from_date = _date(date_from)
        to_date = _date(date_to)
        keyword = _text(batch).casefold()
        wanted_no = _text(delivery_no)
        rows = []
        for row in self._receipts():
            if wanted_source and _text(row.get("来源配置")) != wanted_source:
                continue
            collected = _date(row.get("采集时间"))
            if from_date and collected < from_date:
                continue
            if to_date and collected > to_date:
                continue
            if keyword and keyword not in _text(row.get("批次标识")).casefold():
                continue
            if wanted_no and _text(row.get("单号")) != wanted_no:
                continue
            rows.append(dict(row))
        rows.sort(key=lambda item: (
            _text(item.get("单号")), _text(item.get("回执号"))))
        return rows

    def receipts_for_delivery(self, delivery_id: int) -> list[dict[str, Any]]:
        delivery = next(
            (row for row in self._deliveries()
             if int(row.get("id", 0)) == int(delivery_id)),
            None,
        )
        if delivery is None:
            return []
        return self.list_receipts(delivery_no=_text(delivery.get("单号")))

    def build_export_csv(self, receipts: Iterable[dict[str, Any]]) -> str:
        output = io.StringIO()
        output.write("﻿")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(EXPORT_HEADERS)
        for receipt in receipts:
            writer.writerow([
                _csv_safe(receipt.get(header, "")) for header in EXPORT_HEADERS
            ])
        return output.getvalue()

    def export_csv_for_delivery(self, delivery_id: int) -> str | None:
        receipts = self.receipts_for_delivery(delivery_id)
        delivery = next(
            (row for row in self._deliveries()
             if int(row.get("id", 0)) == int(delivery_id)),
            None,
        )
        if delivery is None:
            return None
        return self.build_export_csv(receipts)

    def _create_export_task(
        self, delivery: dict[str, Any], receipts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rows = store.rows("export_channel")
        csv_text = self.build_export_csv(receipts)
        entry = {
            "id": _next_id(rows),
            "任务标识": f"补交-{delivery['单号']}",
            "来源批次": "、".join(item["批次标识"] for item in receipts),
            "导出格式": "csv",
            "目标路径": f"/exports/backfill/{delivery['单号']}.csv",
            "字段筛选": "回执号,批次标识,来源配置,采集时间",
            "导出状态": "已完成",
            "文件大小": str(len(csv_text.encode("utf-8"))),
            "完成时间": delivery["提交时间"],
            "status": "已完成",
            "pending": False,
            "abnormal": False,
            "关联补交单": delivery["单号"],
            "关联来源配置": delivery["来源配置"],
        }
        rows.append(entry)
        return entry


backfill_service = BackfillService()
