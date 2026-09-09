from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .evaluation import evaluate
from .generation import generate, revise
from .models import ConversationEvent, EvaluationRequest, GenerationRequest, GenerationResponse, RevisionRequest, RevisionResponse, SearchRequest
from .retrieval import DocumentStore


app = FastAPI(title="SARAL Chatbot Prototype", version="0.1.0")
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
allow_all = "*" in allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=not allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = DocumentStore()
runs: dict[str, GenerationResponse] = {}
conversations: dict[str, list[ConversationEvent]] = {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A filename is required.")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Use a file smaller than 20 MB for this prototype.")
    try:
        document = store.ingest(file.filename, data)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"document_id": document.id, "filename": document.filename, "chunk_count": len(document.chunks)}


@app.post("/api/search")
def search(request: SearchRequest):
    try:
        return {"sources": store.search(request.document_id, request.query, request.top_k)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/generate", response_model=GenerationResponse)
async def create_generation(request: GenerationRequest) -> GenerationResponse:
    try:
        result = await generate(store, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    runs[result.run_id] = result
    conversations.setdefault(request.document_id, []).append(ConversationEvent(timestamp=datetime.now(timezone.utc), kind="generation", summary=request.prompt, run_id=result.run_id))
    return result


@app.post("/api/revise", response_model=RevisionResponse)
def create_revision(request: RevisionRequest) -> RevisionResponse:
    previous = runs.get(request.previous_run_id)
    if previous is None or previous.document_id != request.document_id:
        raise HTTPException(status_code=404, detail="The earlier generation is no longer available. Generate again first.")
    try:
        result = revise(previous, request.slide_number, request.change_instruction)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    runs[result.generation.run_id] = result.generation
    conversations.setdefault(request.document_id, []).append(ConversationEvent(timestamp=datetime.now(timezone.utc), kind="revision", summary=f"Slide {request.slide_number}: {request.change_instruction}", run_id=result.generation.run_id))
    return result


@app.get("/api/conversations/{document_id}", response_model=list[ConversationEvent])
def conversation_log(document_id: str) -> list[ConversationEvent]:
    return conversations.get(document_id, [])


@app.post("/api/evaluate")
def evaluate_generation(request: EvaluationRequest):
    result = runs.get(request.run_id)
    if result is None or result.document_id != request.document_id:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return evaluate(store, result, request.reference_script)

