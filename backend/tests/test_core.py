import asyncio
from pathlib import Path

from app.evaluation import evaluate
from app.generation import generate, revise
from app.models import GenerationRequest
from app.retrieval import DocumentStore


def test_generation_has_citation_for_every_claim():
    store = DocumentStore()
    source = Path(__file__).parent / "fixtures" / "sample_paper.tex"
    document = store.ingest(source.name, source.read_bytes())
    result = asyncio.run(generate(store, GenerationRequest(document_id=document.id, prompt="Make a five-slide technical talk focused on the method and preserve the equation.", audience="graduate_students", length="90s", style="technical", slide_count=5)))
    claims = [claim for slide in result.slides for claim in [*slide.bullets, *slide.speaker_notes]] + result.script
    assert all(claim.citations for claim in claims)
    assert any("coverage" in claim.text.lower() for claim in claims)
    assert any(r"\mathrm{coverage}" in chunk.text for chunk in document.chunks)


def test_revision_returns_a_visible_delta():
    store = DocumentStore()
    source = Path(__file__).parent / "fixtures" / "sample_paper.tex"
    document = store.ingest(source.name, source.read_bytes())
    result = asyncio.run(generate(store, GenerationRequest(document_id=document.id, prompt="Explain the method", slide_count=2)))
    updated = revise(result, 2, "Make this less technical and accessible.")
    assert updated.delta.unified_diff
    assert all(text.startswith("In plain terms") for text in updated.delta.new_text)
    assert evaluate(store, updated.generation).citation_coverage == 1.0
