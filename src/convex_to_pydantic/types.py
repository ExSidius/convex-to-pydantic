"""Convex type AST — intermediate representation (IR) for codegen."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ConvexNull(BaseModel):
    type: Literal["null"] = "null"


class ConvexBoolean(BaseModel):
    type: Literal["boolean"] = "boolean"


class ConvexFloat64(BaseModel):
    type: Literal["float64"] = "float64"


class ConvexInt64(BaseModel):
    type: Literal["int64"] = "int64"


class ConvexString(BaseModel):
    type: Literal["string"] = "string"


class ConvexBytes(BaseModel):
    type: Literal["bytes"] = "bytes"


class ConvexAny(BaseModel):
    type: Literal["any"] = "any"


class ConvexId(BaseModel):
    type: Literal["id"] = "id"
    table_name: str


class ConvexLiteral(BaseModel):
    type: Literal["literal"] = "literal"
    value: str | int | float | bool


class ConvexArray(BaseModel):
    type: Literal["array"] = "array"
    element: ConvexType


class ConvexRecord(BaseModel):
    type: Literal["record"] = "record"
    keys: ConvexType
    values: ConvexType


class ConvexUnion(BaseModel):
    type: Literal["union"] = "union"
    variants: list[ConvexType]


class ConvexField(BaseModel):
    name: str
    field_type: ConvexType
    optional: bool


class ConvexObject(BaseModel):
    type: Literal["object"] = "object"
    fields: list[ConvexField]
    class_name: str = ""


ConvexType = Annotated[
    ConvexNull
    | ConvexBoolean
    | ConvexFloat64
    | ConvexInt64
    | ConvexString
    | ConvexBytes
    | ConvexAny
    | ConvexId
    | ConvexLiteral
    | ConvexArray
    | ConvexRecord
    | ConvexUnion
    | ConvexObject,
    Field(discriminator="type"),
]

# Rebuild models that reference ConvexType (forward refs)
ConvexArray.model_rebuild()
ConvexRecord.model_rebuild()
ConvexUnion.model_rebuild()
ConvexField.model_rebuild()
ConvexObject.model_rebuild()


class TableSchema(BaseModel):
    table_name: str
    document_type: ConvexObject


class FunctionSchema(BaseModel):
    module: str
    name: str
    fn_type: str
    args: ConvexObject
    class_name: str = ""
    fn_name: str = ""


class ConvexExport(BaseModel):
    """Top-level container for the full parsed export."""

    tables: list[TableSchema]
    functions: list[FunctionSchema]
