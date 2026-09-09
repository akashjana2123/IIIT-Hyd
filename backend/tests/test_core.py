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


def test_google_ai_generation_mocked(monkeypatch):
    import json
    from unittest.mock import AsyncMock, patch

    store = DocumentStore()
    source = Path(__file__).parent / "fixtures" / "sample_paper.tex"
    document = store.ingest(source.name, source.read_bytes())
    first_chunk_id = document.chunks[0].id

    mock_gemini_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "slides": [
                                    {
                                        "title": "Method Overview",
                                        "bullets": [{"text": "Method details here", "sources": [first_chunk_id]}],
                                        "speaker_notes": [{"text": "Explain method details", "sources": [first_chunk_id]}],
                                    }
                                ],
                                "script": [
                                    {"text": "Welcome to the presentation.", "sources": [first_chunk_id]}
                                ],
                            })
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json = lambda: mock_gemini_payload

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        request = GenerationRequest(
            document_id=document.id,
            prompt="Explain the method",
            slide_count=1,
            provider="google",
            api_key="mock-gemini-key",
        )
        result = asyncio.run(generate(store, request))
        assert result.provider == "google"
        assert len(result.slides) == 1
        assert result.slides[0].title == "Method Overview"
        assert result.slides[0].bullets[0].citations[0].chunk_id == first_chunk_id

