"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ResultStoreService(BaseModuleService):
    MODULE = "result_store"
    ENTITY = "存储批次"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["批次标识", "来源配置", "采集时间", "原始行数", "有效行数", "存储路径", "压缩格式", "校验摘要"]
    REQUIRED_FIELDS = ["批次标识", "来源配置", "采集时间"]
    STATUS_ORDER = ["存储中", "已落库", "校验未过", "已归档"]
    ACTION_RULES = {"执行校验": "已落库", "发起归档": "已落库"}
    NEGATIVE_ACTIONS = []
    RANGE_FIELDS = {"date": "采集时间"}
    DELIVERY_STATE_FIELD = "交付状态"

    def domain_store_result(self, batch_id: str, source_config: str,
                            row_count: int, valid_count: int) -> dict:
        """结构化存储采集结果。"""
        from app.store import store
        import time
        rows = store.rows(self.MODULE)
        store_path = f"/data/results/{batch_id}.json.gz"
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "批次标识": batch_id,
            "来源配置": source_config,
            "采集时间": time.strftime("%Y-%m-%d"),
            "原始行数": str(row_count),
            "有效行数": str(valid_count),
            "存储路径": store_path,
            "压缩格式": "gzip",
            "校验摘要": f"md5:{batch_id[:8]}",
            "status": "已落库",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)
        return entry

    # ---------- 可重发批次结果集 ----------
    # 结果存储本身只管落库；补交所需的“来源 + 采集日”结果集由补交服务基于本模块数据生成。

    def resend_candidates(self, **query) -> dict:
        """按来源、采集日和批次标签返回可重发批次结果集。"""
        from app.services.backfill import backfill_service
        items, total, counts = backfill_service.list_candidates(**query)
        return {
            "items": items,
            "total": total,
            "pending": counts["pending"],
            "delivered": counts["delivered"],
        }

    def deliver_resend(self, payload: dict) -> dict:
        """交付可重发批次并返回逐批回执。"""
        from app.services.backfill import backfill_service
        return backfill_service.deliver(payload)
