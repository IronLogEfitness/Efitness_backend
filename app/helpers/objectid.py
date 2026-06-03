"""Helpers for working with MongoDB ObjectIds.

`parse_object_id` validates a string from a path/query param and converts it,
raising a clean 400 instead of letting an invalid id bubble up as a 500.

`PyObjectId` is a Pydantic v2 annotated type for response models: it accepts a
str or ObjectId and serialises to a string in JSON.
"""
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

from app.helpers.exceptions import BadRequestError


def parse_object_id(value: str, field: str = "id") -> ObjectId:
    if not ObjectId.is_valid(value):
        raise BadRequestError(f"Invalid {field}")
    return ObjectId(value)


def _validate_object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if ObjectId.is_valid(value):
        return ObjectId(str(value))
    raise ValueError("Invalid ObjectId")


PyObjectId = Annotated[
    ObjectId,
    BeforeValidator(_validate_object_id),
    PlainSerializer(lambda v: str(v), return_type=str),
    WithJsonSchema({"type": "string"}),
]
