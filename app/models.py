from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Audience = Literal["policymakers", "graduate_students", "press", "general_public"]
Style = Literal["technical", "plain_english", "press_release"]
Length = Literal["30s", "90s", "5min"]


class SourceCitation(BaseModel):
    """A human-readable pointer to retrieved evidence."""

    chunk_id: str
    page: int | None = None
    score: float = 0.0
    excerpt: str


class GeneratedClaim(BaseModel):
    text: str
    citations: list[SourceCitation] = Field(min_length=1)


class Slide(BaseModel):
    number: int
    title: str
    bullets: list[GeneratedClaim] = Field(min_length=1)
    speaker_notes: list[GeneratedClaim] = Field(min_length=1)


class GenerationRequest(BaseModel):
    document_id: str
    prompt: str = Field(min_length=4, max_length=1200)
    audience: Audience = "graduate_students"
    length: Length = "90s"
    style: Style = "plain_english"
    slide_count: int = Field(default=5, ge=1, le=10)
    provider: Literal["auto", "google", "openai", "extractive_fallback"] = "auto"
    api_key: str | None = Field(default=None, max_length=300)


class GenerationResponse(BaseModel):
    run_id: str
    document_id: str
    provider: Literal["extractive_fallback", "openai", "google"]
    audience: Audience
    length: Length
    style: Style
    slides: list[Slide]
    script: list[GeneratedClaim]
    retrieved_sources: list[SourceCitation]
    created_at: datetime


class RevisionRequest(BaseModel):
    document_id: str
    previous_run_id: str
    slide_number: int = Field(ge=1, le=10)
    change_instruction: str = Field(min_length=4, max_length=600)


class Delta(BaseModel):
    slide_number: int
    old_text: list[str]
    new_text: list[str]
    unified_diff: str
    why_changed: str


class RevisionResponse(BaseModel):
    generation: GenerationResponse
    delta: Delta


class SearchRequest(BaseModel):
    document_id: str
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=15)


class EvaluationRequest(BaseModel):
    document_id: str
    run_id: str
    reference_script: str | None = Field(default=None, max_length=25000)


class EvaluationResult(BaseModel):
    claim_count: int
    citation_coverage: float
    mean_lexical_grounding: float
    rouge_l_f1: float | None = None
    note: str


class ConversationEvent(BaseModel):
    timestamp: datetime
    kind: Literal["generation", "revision"]
    summary: str
    run_id: str

