from typing import List, Optional

from pydantic import BaseModel, Field


class CatalogueItem(BaseModel):
    """One choice: a scope ID, a use case (``name@major``), or a Master Data
    code (purposes, subject ID types)."""

    id: str
    label: Optional[str] = None
    description: Optional[str] = None
    # Use cases: the purpose the exchange states for it.
    purpose: Optional[str] = None
    # Scopes: the fields its current version covers.
    fields: List[str] = Field(default_factory=list)


class CatalogueSourceOut(BaseModel):
    kind: str  # scopes | use_cases | purposes | subject_id_types
    data_controller: Optional[str] = None  # scopes only
    label: str
    items: List[CatalogueItem] = Field(default_factory=list)
    # Why the source could not be read (items then empty); null = read.
    error: Optional[str] = None
    # Why a Master Data list offers no choices although it was read (e.g. not in
    # this country's pack): free text, not checked, no warning.
    note: Optional[str] = None


class CatalogueResponse(BaseModel):
    sources: List[CatalogueSourceOut] = Field(default_factory=list)
