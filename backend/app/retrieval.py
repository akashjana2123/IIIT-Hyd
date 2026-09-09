from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .models import SourceCitation


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    page: int | None


@dataclass
class IndexedDocument:
    id: str
    filename: str
    chunks: list[Chunk]
    vectorizer: TfidfVectorizer
    matrix: object


def _normalise(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _blocks(text: str, max_chars: int = 1100) -> list[str]:
    """Chunk on paragraphs, never splitting a paragraph/math block unless unavoidable."""
    units = [u.strip() for u in re.split(r"\n\s*\n", text) if u.strip()]
    blocks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        if current and current_len + len(unit) + 2 > max_chars:
            blocks.append("\n\n".join(current))
            current, current_len = [], 0
        if len(unit) > max_chars and not current:
            pieces = re.split(r"(?<=[.!?])\s+", unit)
            buffer = ""
            for piece in pieces:
                if buffer and len(buffer) + len(piece) + 1 > max_chars:
                    blocks.append(buffer)
                    buffer = piece
                else:
                    buffer = f"{buffer} {piece}".strip()
            if buffer:
                blocks.append(buffer)
            continue
        current.append(unit)
        current_len += len(unit) + 2
    if current:
        blocks.append("\n\n".join(current))
    return blocks


def _tex_units(text: str) -> list[str]:
    """Separate TeX display math before paragraph packing, keeping every math block intact."""
    pattern = r"(\\\[.*?\\\]|\$\$.*?\$\$|\\begin\{(?:equation\*?|align\*?|gather\*?)\}.*?\\end\{(?:equation\*?|align\*?|gather\*?)\})"
    pieces = re.split(pattern, text, flags=re.DOTALL)
    units: list[str] = []
    for piece in pieces:
        clean = piece.strip()
        if not clean:
            continue
        if re.fullmatch(pattern, clean, flags=re.DOTALL):
            units.append(clean)
        else:
            units.extend([p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()])
    return units


def _tex_blocks(text: str, max_chars: int = 1100) -> list[str]:
    units = _tex_units(text)
    output: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        is_math = unit.startswith((r"\[", "$$", r"\begin"))
        if current and (size + len(unit) + 2 > max_chars or is_math):
            output.append("\n\n".join(current))
            current, size = [], 0
        if is_math:
            output.append(unit)
        else:
            current.append(unit)
            size += len(unit) + 2
    if current:
        output.append("\n\n".join(current))
    return output


class DocumentStore:
    """In-memory sparse index. Swap this boundary for a persistent vector DB at scale."""

    def __init__(self) -> None:
        self.documents: dict[str, IndexedDocument] = {}

    def ingest(self, filename: str, data: bytes) -> IndexedDocument:
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            pages = self._extract_pdf(data)
            chunks = [
                Chunk(id=f"C{page_no}-{i + 1}", text=block, page=page_no)
                for page_no, page_text in pages
                for i, block in enumerate(_blocks(page_text))
            ]
        elif suffix in {".tex", ".latex", ".txt", ".md"}:
            text = data.decode("utf-8", errors="replace")
            block_list = _tex_blocks(text) if suffix in {".tex", ".latex"} else _blocks(text)
            chunks = [Chunk(id=f"C1-{i + 1}", text=block, page=1) for i, block in enumerate(block_list)]
        else:
            raise ValueError("Upload a PDF, LaTeX, Markdown, or text file.")
        if not chunks:
            raise ValueError("No readable text was found in this file.")
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=30000)
        matrix = vectorizer.fit_transform([chunk.text for chunk in chunks])
        document = IndexedDocument(str(uuid.uuid4()), filename, chunks, vectorizer, matrix)
        self.documents[document.id] = document
        return document

    @staticmethod
    def _extract_pdf(data: bytes) -> list[tuple[int, str]]:
        pdf = fitz.open(stream=data, filetype="pdf")
        try:
            return [(page.number + 1, _normalise(page.get_text("text"))) for page in pdf if page.get_text("text").strip()]
        finally:
            pdf.close()

    def get(self, document_id: str) -> IndexedDocument:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise KeyError("Document not found. Upload it again; indexes are kept in memory for this prototype.") from exc

    def search(self, document_id: str, query: str, top_k: int = 6) -> list[SourceCitation]:
        document = self.get(document_id)
        q = document.vectorizer.transform([query])
        scores = (document.matrix @ q.T).toarray().ravel()
        indices = np.argsort(-scores)[:top_k].tolist() if np.any(scores) else list(range(min(top_k, len(document.chunks))))
        return [
            SourceCitation(chunk_id=document.chunks[i].id, page=document.chunks[i].page, score=round(float(scores[i]), 4), excerpt=document.chunks[i].text[:420].replace("\n", " "))
            for i in indices
        ]

    def chunk_map(self, document_id: str) -> dict[str, Chunk]:
        return {chunk.id: chunk for chunk in self.get(document_id).chunks}
