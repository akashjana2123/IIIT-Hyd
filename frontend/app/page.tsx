"use client";

import { ChangeEvent, FormEvent, useState } from "react";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

type Citation = { chunk_id: string; page?: number; score: number; excerpt: string };
type Claim = { text: string; citations: Citation[] };
type Slide = { number: number; title: string; bullets: Claim[]; speaker_notes: Claim[] };
type Generation = {
  run_id: string;
  provider: "extractive_fallback" | "openai" | "google";
  slides: Slide[];
  script: Claim[];
  retrieved_sources: Citation[];
};
type Delta = { slide_number: number; old_text: string[]; new_text: string[]; unified_diff: string; why_changed: string };

function CitationPills({ citations }: { citations: Citation[] }) {
  return <span className="citations">{citations.map((citation) => (
    <span className="citation" title={citation.excerpt} key={citation.chunk_id}>
      {citation.chunk_id}{citation.page ? ` · p.${citation.page}` : ""}
    </span>
  ))}</span>;
}

export default function Home() {
  const [documentId, setDocumentId] = useState("");
  const [fileName, setFileName] = useState("");
  const [chunkCount, setChunkCount] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("Make a 5-slide talk for graduate students focused on methods; include speaker notes and preserve key equations.");
  const [audience, setAudience] = useState("graduate_students");
  const [length, setLength] = useState("90s");
  const [style, setStyle] = useState("plain_english");
  const [slideCount, setSlideCount] = useState(5);
  const [provider, setProvider] = useState<"auto" | "google" | "openai" | "extractive_fallback">("auto");
  const [apiKey, setApiKey] = useState("");
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [delta, setDelta] = useState<Delta | null>(null);
  const [revisionSlide, setRevisionSlide] = useState(2);
  const [revision, setRevision] = useState("Make this less technical and more accessible.");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true); setError(""); setGeneration(null); setDelta(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`${API_BASE}/api/documents`, { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Upload failed");
      setDocumentId(data.document_id); setFileName(data.filename); setChunkCount(data.chunk_count);
    } catch (err) { setError(err instanceof Error ? err.message : "Upload failed"); }
    finally { setBusy(false); }
  }

  async function createGeneration(event: FormEvent) {
    event.preventDefault();
    if (!documentId) { setError("Upload a paper before generating content."); return; }
    setBusy(true); setError(""); setDelta(null);
    try {
      const response = await fetch(`${API_BASE}/api/generate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: documentId, prompt, audience, length, style, slide_count: slideCount,
          provider,
          ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Generation failed");
      setGeneration(data); setRevisionSlide(Math.min(2, data.slides.length));
    } catch (err) { setError(err instanceof Error ? err.message : "Generation failed"); }
    finally { setBusy(false); }
  }

  async function reviseSlide(event: FormEvent) {
    event.preventDefault();
    if (!generation) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/revise`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId, previous_run_id: generation.run_id, slide_number: revisionSlide, change_instruction: revision }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Revision failed");
      setGeneration(data.generation); setDelta(data.delta);
    } catch (err) { setError(err instanceof Error ? err.message : "Revision failed"); }
    finally { setBusy(false); }
  }

  return <main>
    <section className="hero">
      <p className="eyebrow">SARAL CHATBOT · PROTOTYPE</p>
      <h1>Make research <em>clear</em>, without losing the evidence.</h1>
      <p className="subhead">Upload a paper, choose an audience, and create cited slides, scripts, and tracked revisions.</p>
    </section>

    <section className="panel setup" aria-label="Create a presentation">
      <div className="step"><span>01</span><h2>Upload source</h2></div>
      <label className="upload">
        <input type="file" accept=".pdf,.tex,.latex,.txt,.md" onChange={upload} disabled={busy} />
        <strong>{fileName || "Choose a PDF or LaTeX paper"}</strong>
        <small>{chunkCount ? `${chunkCount} searchable evidence chunks indexed` : "PDF, .tex, .md, or .txt · max 20 MB"}</small>
      </label>
    </section>

    <section className="panel" aria-label="Generation controls">
      <div className="step"><span>02</span><h2>Set the communication brief</h2></div>
      <form onSubmit={createGeneration} className="brief">
        <label className="wide">What should SARAL create?<textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} /></label>
        <label>Audience<select value={audience} onChange={(e) => setAudience(e.target.value)}><option value="graduate_students">Graduate students</option><option value="policymakers">Policymakers</option><option value="press">Press</option><option value="general_public">General public</option></select></label>
        <label>Length<select value={length} onChange={(e) => setLength(e.target.value)}><option value="30s">30 seconds</option><option value="90s">90 seconds</option><option value="5min">5 minutes</option></select></label>
        <label>Style<select value={style} onChange={(e) => setStyle(e.target.value)}><option value="plain_english">Plain English</option><option value="technical">Technical</option><option value="press_release">Press release</option></select></label>
        <label>Slides<input type="number" min="1" max="10" value={slideCount} onChange={(e) => setSlideCount(Number(e.target.value))} /></label>
        <label>AI Provider<select value={provider} onChange={(e) => setProvider(e.target.value as any)}><option value="auto">Auto (Configured Key / Fallback)</option><option value="google">Google AI (Gemini)</option><option value="openai">OpenAI</option><option value="extractive_fallback">Local Extractive Fallback</option></select></label>
        {provider !== "extractive_fallback" && (
          <label>API Key (Optional)<input type="password" placeholder={provider === "google" ? "Google AI / Gemini key" : provider === "openai" ? "OpenAI key" : "Optional API key override"} value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label>
        )}
        <button type="submit" disabled={busy || !documentId}>{busy ? "Working…" : "Generate cited draft"}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </section>

    {generation && <>
      <section className="status"><span className="dot" /> Generated with {generation.provider === "google" ? "Google AI (Gemini)" : generation.provider === "openai" ? "OpenAI" : "the local extractive fallback"}. Every item below links to retrieved evidence.</section>
      <section className="output">
        <div className="deck"><div className="step"><span>03</span><h2>Slide-level draft</h2></div>
          {generation.slides.map((slide) => <article className="slide" key={slide.number}>
            <p className="slide-no">SLIDE {String(slide.number).padStart(2, "0")}</p><h3>{slide.title}</h3>
            <ul>{slide.bullets.map((bullet, i) => <li key={i}>{bullet.text}<CitationPills citations={bullet.citations} /></li>)}</ul>
            <details><summary>Speaker notes ({slide.speaker_notes.length})</summary>{slide.speaker_notes.map((note, i) => <p key={i}>{note.text}<CitationPills citations={note.citations} /></p>)}</details>
          </article>)}
        </div>
        <aside className="script"><div className="step"><span>04</span><h2>Speaker script</h2></div>{generation.script.map((part, i) => <p key={i}>{part.text}<CitationPills citations={part.citations} /></p>)}</aside>
      </section>
      <section className="panel revision"><div className="step"><span>05</span><h2>Refine in conversation</h2></div>
        <form onSubmit={reviseSlide} className="revision-form">
          <label>Slide <select value={revisionSlide} onChange={(e) => setRevisionSlide(Number(e.target.value))}>{generation.slides.map((slide) => <option value={slide.number} key={slide.number}>#{slide.number}</option>)}</select></label>
          <label className="wide">Change request <input value={revision} onChange={(e) => setRevision(e.target.value)} /></label>
          <button disabled={busy}>{busy ? "Revising…" : "Show tracked change"}</button>
        </form>
        {delta && <div className="delta"><p><strong>Why it changed:</strong> {delta.why_changed}</p><pre>{delta.unified_diff}</pre></div>}
      </section>
      <section className="sources"><h2>Retrieved evidence</h2>{generation.retrieved_sources.map((source) => <article key={source.chunk_id}><strong>{source.chunk_id} · page {source.page ?? "—"}</strong><p>{source.excerpt}</p></article>)}</section>
    </>}
  </main>;
}

