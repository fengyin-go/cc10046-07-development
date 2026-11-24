"""模块服务基类：共享查询、登记、动作和统计骨架，业务差异留在各模块文件。"""
from __future__ import annotations

from typing import Any

from app.store import store


class BaseModuleService:
    MODULE = ""
    ENTITY = ""
    LIST_FIELDS: list[str] = []
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER: list[str] = []
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []
    # 需要在列表/导出中支持日期区间与交付状态筛选的模块自行声明字段。
    RANGE_FIELDS: dict[str, str] = {}
    DELIVERY_STATE_FIELD = ""

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        delivery_state: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(self.MODULE))
        for field, expected in (filters or {}).items():
            if field in self.LIST_FIELDS:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        if keyword and self.LIST_FIELDS:
            field = self.LIST_FIELDS[0]
            rows = [row for row in rows if keyword.casefold() in str(row.get(field, "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        date_field = self.RANGE_FIELDS.get("date")
        if date_field:
            lower = (date_from or "").strip()[:10]
            upper = (date_to or "").strip()[:10]
            if lower:
                rows = [
                    row for row in rows
                    if str(row.get(date_field, ""))[:10] >= lower
                ]
            if upper:
                rows = [
                    row for row in rows
                    if str(row.get(date_field, ""))[:10] <= upper
                ]
        if self.DELIVERY_STATE_FIELD and delivery_state:
            rows = self._filter_delivery_state(rows, delivery_state)
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def _filter_delivery_state(
        self, rows: list[dict[str, Any]], expected: str,
    ) -> list[dict[str, Any]]:
        pending_terms = {"pending", "待补", "未交付"}
        delivered_terms = {"delivered", "已交付"}
        if expected in pending_terms:
            return [
                row for row in rows
                if str(row.get(self.DELIVERY_STATE_FIELD) or "待补") not in delivered_terms
            ]
        if expected in delivered_terms:
            return [
                row for row in rows
                if str(row.get(self.DELIVERY_STATE_FIELD) or "待补") in delivered_terms
            ]
        return rows

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(self.MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        rows = store.rows(self.MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in self.LIST_FIELDS})
        entry["status"] = self.STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"
        entry["status"] = target
        entry["pending"] = target != self.STATUS_ORDER[-1]
        entry["abnormal"] = action in self.NEGATIVE_ACTIONS
        return entry, f"{self.ENTITY}已{action}"

    def domain_snapshot(self) -> dict[str, Any]:
        """输出模块级数据质量快照，供跨模块消费和题位源码锚点使用。"""
        rows = store.rows(self.MODULE)
        by_status = {
            status: sum(1 for row in rows if row.get("status") == status)
            for status in self.STATUS_ORDER
        }
        return {
            "module": self.MODULE,
            "entity": self.ENTITY,
            "artifact": f"{self.ENTITY}数据集",
            "count": len(rows),
            "by_status": by_status,
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        }
