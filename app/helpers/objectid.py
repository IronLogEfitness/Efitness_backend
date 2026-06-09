"""Helpers for working with MongoDB ObjectIds.

`parse_object_id` validates a string from a path/query param and converts it,
raising a clean 400 instead of letting an invalid id bubble up as a 500.
"""
from bson import ObjectId

from app.helpers.exceptions import BadRequestError


def parse_object_id(value: str, field: str = "id") -> ObjectId:
    if not ObjectId.is_valid(value):
        raise BadRequestError(f"Invalid {field}")
    return ObjectId(value)
