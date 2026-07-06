"""Convex type AST — intermediate representation (IR) for codegen.

All IR models are frozen (immutable). Names are assigned externally via
a NameRegistry, not stored on the models themselves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConvexNull(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["null"] = "null"


class ConvexBoolean(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["boolean"] = "boolean"


class ConvexFloat64(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["float64"] = "float64"


class ConvexInt64(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["int64"] = "int64"


class ConvexString(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["string"] = "string"


class ConvexBytes(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["bytes"] = "bytes"


class ConvexAny(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["any"] = "any"


class ConvexId(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["id"] = "id"
    table_name: str


class ConvexLiteral(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["literal"] = "literal"
    value: str | int | float | bool


class ConvexArray(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["array"] = "array"
    element: ConvexType


class ConvexRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["record"] = "record"
    keys: ConvexType
    values: ConvexType


class ConvexUnion(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["union"] = "union"
    variants: tuple[ConvexType, ...]


class ConvexField(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    field_type: ConvexType
    optional: bool


class ConvexObject(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["object"] = "object"
    fields: tuple[ConvexField, ...]


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
    model_config = ConfigDict(frozen=True)
    table_name: str
    document_type: ConvexObject


class FunctionSchema(BaseModel):
    model_config = ConfigDict(frozen=True)
    module: str
    name: str
    fn_type: str
    args: ConvexObject
    returns: ConvexType | None = None


class ConvexExport(BaseModel):
    model_config = ConfigDict(frozen=True)
    tables: tuple[TableSchema, ...]
    functions: tuple[FunctionSchema, ...]
