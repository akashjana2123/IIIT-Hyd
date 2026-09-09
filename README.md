# SARAL Chatbot Backend

FastAPI backend providing retrieval, generation (Google AI Gemini & OpenAI), and citation tracking for research paper communication.

## Setup & Running Locally

```bash
python -m venv env
source env/bin/activate  # On Windows: .\env\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Interactive API documentation will be available at `http://localhost:8000/docs`.

## Running Tests

```bash
pytest
```

## Environment Variables

- `GEMINI_API_KEY`: Google AI Studio API key (recommended for Google AI).
- `GEMINI_MODEL`: Model name (defaults to `gemini-1.5-flash`).
- `OPENAI_API_KEY`: OpenAI API key (if using OpenAI).
- `OPENAI_MODEL`: OpenAI model (defaults to `gpt-4.1-mini`).
- `CORS_ORIGINS`: Comma-separated list of allowed origins, e.g. `https://your-frontend.vercel.app`.

## Deployment (Render / Railway / Fly.io)

- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
