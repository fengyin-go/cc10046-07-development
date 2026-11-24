"""业务路由汇总：补交固定路由先注册，再挂通用模块路由与跨模块链路。"""
from __future__ import annotations

from app.routers import backfill
from app.routers import chains
from app.routers import resource

ROUTERS = [backfill, resource, chains]
