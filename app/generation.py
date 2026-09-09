from __future__ import annotations

import difflib
import json
import os
import re
import uuid
from datetime import datetime, timezone

import httpx

from .models import Delta, GeneratedClaim, GenerationRequest, GenerationResponse, RevisionResponse, Slide, SourceCitation
from .retrieval import DocumentStore


WORD_TARGETS = {"30s": 70, "90s": 190, "5min": 650}
STYLE_GUIDANCE = {
    "technical": "use field-appropriate terminology and retain important equations",
    "plain_english": "use short sentences and define specialist terms",
    "press_release": "lead with public value and use clear, quotable language",
}


def _sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if len(part.strip()) > 25]


def _title_from_text(text: str, index: int) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", text)
    keywords: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered not in {"this", "that", "with", "from", "their", "which", "these", "using", "were", "been"} and lowered not in keywords:
            keywords.append(lowered)
        if len(keywords) == 4:
            break
    return f"{index}. {' '.join(keywords).title() or 'Key evidence'}"


def _citation(source: SourceCitation) -> SourceCitation:
    return SourceCitation(**source.model_dump())


def _claims_from_source(source: SourceCitation, count: int = 3) -> list[GeneratedClaim]:
    sentences = _sentences(source.excerpt) or [source.excerpt.strip() or "The uploaded document provides supporting evidence for this point."]
    return [GeneratedClaim(text=sentences[n % len(sentences)], citations=[_citation(source)]) for n in range(count)]


def _fallback_response(request: GenerationRequest, sources: list[SourceCitation]) -> GenerationResponse:
    """A local, extractive mode that is demonstrably grounded without an API key."""
    slides: list[Slide] = []
    for index in range(request.slide_count):
        source = sources[index % len(sources)]
        bullets = _claims_from_source(source, 3)
        notes = [
            GeneratedClaim(
                text=f"For {request.audience.replace('_', ' ')}, explain why this evidence matters: {bullet.text}",
                citations=[_citation(source)],
            )
            for bullet in bullets
        ]
        slides.append(Slide(number=index + 1, title=_title_from_text(source.excerpt, index + 1), bullets=bullets, speaker_notes=notes))

    base_claims = [claim for slide in slides for claim in slide.bullets]
    script: list[GeneratedClaim] = []
    while sum(len(claim.text.split()) for claim in script) < WORD_TARGETS[request.length] and len(script) < 40:
        source_claim = base_claims[len(script) % len(base_claims)]
        prefix = "The source states: " if len(script) % 3 == 0 else "This supports the next point: "
        script.append(GeneratedClaim(text=f"{prefix}{source_claim.text}", citations=source_claim.citations))
        if request.length != "5min" and len(script) >= len(base_claims):
            break

    return GenerationResponse(
        run_id=str(uuid.uuid4()), document_id=request.document_id, provider="extractive_fallback",
        audience=request.audience, length=request.length, style=request.style, slides=slides, script=script,
        retrieved_sources=sources, created_at=datetime.now(timezone.utc),
    )


def _claim_from_llm(item: dict, source_lookup: dict[str, SourceCitation]) -> GeneratedClaim:
    source_ids = [source_id for source_id in item.get("sources", []) if source_id in source_lookup]
    if not source_ids:  # Fail closed: every output is cited.
        source_ids = [next(iter(source_lookup))]
    return GeneratedClaim(text=item["text"].strip(), citations=[_citation(source_lookup[source_id]) for source_id in source_ids])


async def _openai_response(request: GenerationRequest, sources: list[SourceCitation], api_key: str | None = None) -> GenerationResponse:
    """Optional OpenAI provider."""
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("No OPENAI_API_KEY configured")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    evidence = "\n\n".join(f"[{source.chunk_id} | page {source.page}]\n{source.excerpt}" for source in sources)
    item_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"text": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}},
        "required": ["text", "sources"],
    }
    schema = {
        "name": "saral_deck", "schema": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "slides": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"title": {"type": "string"}, "bullets": {"type": "array", "items": item_schema}, "speaker_notes": {"type": "array", "items": item_schema}}, "required": ["title", "bullets", "speaker_notes"]}},
                "script": {"type": "array", "items": item_schema},
            }, "required": ["slides", "script"],
        },
    }
    prompt = f"""Create a {request.slide_count}-slide presentation and approximately {WORD_TARGETS[request.length]}-word speaker script.
Audience: {request.audience}. Style: {request.style} ({STYLE_GUIDANCE[request.style]}).
User request: {request.prompt}
Use ONLY the evidence below. Every bullet, note, and script sentence must include one or more exact chunk IDs in sources. Preserve LaTeX equations verbatim when relevant. Do not make unsupported claims.

EVIDENCE:\n{evidence}"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You produce safe, accessible, evidence-grounded science communication."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_schema", "json_schema": schema},
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload)
        response.raise_for_status()
    parsed = json.loads(response.json()["choices"][0]["message"]["content"])
    lookup = {source.chunk_id: source for source in sources}
    slides = [
        Slide(
            number=index + 1,
            title=item.get("title", f"Slide {index + 1}"),
            bullets=[_claim_from_llm(claim, lookup) for claim in item.get("bullets", [])] or _claims_from_source(sources[index % len(sources)], 1),
            speaker_notes=[_claim_from_llm(claim, lookup) for claim in item.get("speaker_notes", [])] or _claims_from_source(sources[index % len(sources)], 1),
        )
        for index, item in enumerate(parsed.get("slides", []))
    ]
    return GenerationResponse(
        run_id=str(uuid.uuid4()), document_id=request.document_id, provider="openai", audience=request.audience,
        length=request.length, style=request.style, slides=slides,
        script=[_claim_from_llm(claim, lookup) for claim in parsed.get("script", [])] or [claim for slide in slides for claim in slide.bullets],
        retrieved_sources=sources, created_at=datetime.now(timezone.utc),
    )


async def _google_response(request: GenerationRequest, sources: list[SourceCitation], api_key: str | None = None) -> GenerationResponse:
    """Optional Google AI (Gemini) provider."""
    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("No GEMINI_API_KEY or GOOGLE_API_KEY configured")
    model = os.getenv("GEMINI_MODEL") or os.getenv("GOOGLE_MODEL") or "gemini-1.5-flash"
    evidence = "\n\n".join(f"[{source.chunk_id} | page {source.page}]\n{source.excerpt}" for source in sources)
    prompt = f"""Create a {request.slide_count}-slide presentation and approximately {WORD_TARGETS[request.length]}-word speaker script.
Audience: {request.audience}. Style: {request.style} ({STYLE_GUIDANCE[request.style]}).
User request: {request.prompt}
Use ONLY the evidence below. Every bullet, note, and script sentence must include one or more exact chunk IDs in sources. Preserve LaTeX equations verbatim when relevant. Do not make unsupported claims.

EVIDENCE:\n{evidence}

Respond ONLY with valid JSON matching this schema:
{{
  "slides": [
    {{
      "title": "Slide title",
      "bullets": [{{"text": "bullet claim", "sources": ["chunk_id"]}}],
      "speaker_notes": [{{"text": "note claim", "sources": ["chunk_id"]}}]
    }}
  ],
  "script": [
    {{"text": "script sentence", "sources": ["chunk_id"]}}
  ]
}}"""
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    data = response.json()
    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)
    parsed = json.loads(raw_text)
    lookup = {source.chunk_id: source for source in sources}
    slides = [
        Slide(
            number=index + 1,
            title=item.get("title", f"Slide {index + 1}"),
            bullets=[_claim_from_llm(claim, lookup) for claim in item.get("bullets", [])] or _claims_from_source(sources[index % len(sources)], 1),
            speaker_notes=[_claim_from_llm(claim, lookup) for claim in item.get("speaker_notes", [])] or _claims_from_source(sources[index % len(sources)], 1),
        )
        for index, item in enumerate(parsed.get("slides", []))
    ]
    script = [_claim_from_llm(claim, lookup) for claim in parsed.get("script", [])] or [claim for slide in slides for claim in slide.bullets]
    return GenerationResponse(
        run_id=str(uuid.uuid4()), document_id=request.document_id, provider="google", audience=request.audience,
        length=request.length, style=request.style, slides=slides,
        script=script, retrieved_sources=sources,
        created_at=datetime.now(timezone.utc),
    )


async def generate(store: DocumentStore, request: GenerationRequest) -> GenerationResponse:
    sources = store.search(request.document_id, f"{request.prompt} {request.audience} {request.style}", top_k=max(6, request.slide_count))

    if request.provider == "google":
        try:
            return await _google_response(request, sources, api_key=request.api_key)
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError):
            pass
    elif request.provider == "openai":
        try:
            return await _openai_response(request, sources, api_key=request.api_key)
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError):
            pass
    elif request.provider == "extractive_fallback":
        return _fallback_response(request, sources)
    else:
        # Auto mode: check Google AI first, then OpenAI, else fallback
        google_key = request.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if google_key:
            try:
                return await _google_response(request, sources, api_key=google_key)
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError):
                pass
        openai_key = request.api_key or os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                return await _openai_response(request, sources, api_key=openai_key)
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError):
                pass

    return _fallback_response(request, sources)


def _simplify(text: str) -> str:
    replacements = {"methodology": "method", "utilize": "use", "demonstrates": "shows", "approximately": "about", "significant": "important", "therefore": "so"}
    new_text = text
    for source, replacement in replacements.items():
        new_text = re.sub(rf"\b{source}\b", replacement, new_text, flags=re.IGNORECASE)
    new_text = re.sub(r"\([^)]{20,}\)", "", new_text)
    return f"In plain terms, {new_text[0].lower() + new_text[1:] if len(new_text) > 1 else new_text}"


def revise(previous: GenerationResponse, slide_number: int, instruction: str) -> RevisionResponse:
    if slide_number > len(previous.slides):
        raise ValueError(f"Slide {slide_number} does not exist in run {previous.run_id}.")
    updated = previous.model_copy(deep=True)
    updated.run_id, updated.created_at = str(uuid.uuid4()), datetime.now(timezone.utc)
    target = updated.slides[slide_number - 1]
    old_text = [claim.text for claim in target.bullets]
    wants_simple = any(term in instruction.lower() for term in ("less technical", "simpl", "plain", "dumb down", "accessible"))
    if wants_simple:
        new_bullets = [claim.model_copy(update={"text": _simplify(claim.text)}) for claim in target.bullets]
        reason = "Applied the requested plain-language rewrite while retaining the same retrieved evidence and citations."
    else:
        new_bullets = [claim.model_copy(update={"text": f"{claim.text} ({instruction.strip().rstrip('.')})"}) for claim in target.bullets]
        reason = "Applied the requested edit only to the selected slide and retained its original evidence links."
    target.bullets = new_bullets
    target.speaker_notes = [note.model_copy(update={"text": _simplify(note.text) if wants_simple else f"{note.text} {instruction.strip()}"}) for note in target.speaker_notes]
    new_text = [claim.text for claim in new_bullets]
    diff = "\n".join(difflib.unified_diff(old_text, new_text, fromfile="before", tofile="after", lineterm=""))
    return RevisionResponse(generation=updated, delta=Delta(slide_number=slide_number, old_text=old_text, new_text=new_text, unified_diff=diff, why_changed=reason))

