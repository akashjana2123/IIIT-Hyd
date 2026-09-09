from __future__ import annotations

import re

from .models import EvaluationResult, GenerationResponse
from .retrieval import DocumentStore


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _lcs_length(a: list[str], b: list[str]) -> int:
    row = [0] * (len(b) + 1)
    for left in a:
        next_row = [0]
        for right_index, right in enumerate(b, 1):
            next_row.append(row[right_index - 1] + 1 if left == right else max(row[right_index], next_row[-1]))
        row = next_row
    return row[-1]


def _rouge_l(candidate: str, reference: str) -> float:
    candidate_tokens, reference_tokens = candidate.lower().split(), reference.lower().split()
    if not candidate_tokens or not reference_tokens:
        return 0.0
    lcs = _lcs_length(candidate_tokens, reference_tokens)
    precision, recall = lcs / len(candidate_tokens), lcs / len(reference_tokens)
    return round((2 * precision * recall / (precision + recall)) if precision + recall else 0.0, 4)


def evaluate(store: DocumentStore, result: GenerationResponse, reference_script: str | None = None) -> EvaluationResult:
    claims = [claim for slide in result.slides for claim in [*slide.bullets, *slide.speaker_notes]] + result.script
    chunks = store.chunk_map(result.document_id)
    overlaps: list[float] = []
    for claim in claims:
        evidence = " ".join(chunks[citation.chunk_id].text for citation in claim.citations if citation.chunk_id in chunks)
        claim_tokens, evidence_tokens = _tokens(claim.text), _tokens(evidence)
        overlaps.append(len(claim_tokens & evidence_tokens) / len(claim_tokens) if claim_tokens else 0.0)
    generated_script = " ".join(claim.text for claim in result.script)
    total = len(claims)
    return EvaluationResult(
        claim_count=total, citation_coverage=round(sum(bool(claim.citations) for claim in claims) / total if total else 0.0, 4),
        mean_lexical_grounding=round(sum(overlaps) / len(overlaps) if overlaps else 0.0, 4),
        rouge_l_f1=_rouge_l(generated_script, reference_script) if reference_script else None,
        note="Citation coverage and lexical grounding are automatic factuality proxies. Supply a human reference script to calculate ROUGE-L; conduct the requested audience/factuality human review separately.",
    )

