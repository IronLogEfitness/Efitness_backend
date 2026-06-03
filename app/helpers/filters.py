"""Reusable query-parameter helpers.

These are FastAPI dependencies that parse and validate common query params, so
routers stay declarative and the same rules are reused across endpoints.
"""
from dataclasses import dataclass

from fastapi import Query


@dataclass
class Pagination:
    limit: int
    skip: int


def pagination_params(
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    skip: int = Query(0, ge=0, description="Items to skip (for paging)"),
) -> Pagination:
    return Pagination(limit=limit, skip=skip)
