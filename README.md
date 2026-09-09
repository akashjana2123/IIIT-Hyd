# SARAL Chatbot Frontend

Next.js web application for the SARAL research paper communication chatbot.

## Getting Started

Install dependencies and start the development server:

```bash
npm install
npm run dev
```

Visit `http://localhost:3000`.

## Environment Variables

- `NEXT_PUBLIC_API_BASE_URL`: The URL of your deployed backend service (e.g. `https://saral-backend.onrender.com`). Defaults to `http://localhost:8000` for local development.

## Deployment on Vercel

1. Import this repository into Vercel and select the `frontend` branch.
2. Framework preset will automatically be detected as **Next.js**.
3. Set the environment variable:
   - `NEXT_PUBLIC_API_BASE_URL`: `https://<your-backend-url>`
4. Deploy.
