# Company Intel — AI Company Research Dashboard

A React + Vite frontend on top of your existing SerpAPI + Requests + BeautifulSoup
research script, served through a FastAPI backend. The Python research logic in
`backend/research_agent_newest.py` (the country-aware engine, with Chinese
address translation and WeChat extraction) is untouched — the backend only adds
an HTTP layer around `research_company(company_name, country, industry_hint)`.

```
research-agent/
├── backend/
│   ├── research_agent_newest.py  # your research engine, unchanged
│   ├── main.py                    # FastAPI app: GET /countries, POST /research
│   ├── requirements.txt
│   ├── .env.example               # copy to .env and add your real key
│   └── .gitignore
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   ├── api.js                  # calls GET /countries and POST /research
    │   ├── index.css               # design system (light/dark, glassmorphism)
    │   └── components/
    │       ├── SearchBar.jsx       # company name + country + industry hint
    │       ├── Loader.jsx          # skeleton loader with cycling status text
    │       ├── ErrorBanner.jsx
    │       ├── ResultCard.jsx      # dossier card with confidence badge
    │       └── icons.jsx
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── .gitignore
```

## 1. Backend setup (FastAPI)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env and set:
# SERPAPI_API_KEY=your_actual_key
```

The `SERPAPI_API_KEY` is read by `research_agent_newest.py` via `python-dotenv`,
exactly as before — it never leaves the backend and is never sent to the frontend.

`deep-translator` and `pypinyin` (also in `requirements.txt`) power the
Chinese-address-to-English translation and WeChat/pinyin handling. Both degrade
gracefully if missing, but install them for that feature to actually work.

Run the API:

```bash
uvicorn main:app --reload --port 8000
```

Check it's alive: open `http://localhost:8000/health` → `{"status": "ok"}`.
Interactive docs are at `http://localhost:8000/docs`.

## 2. Frontend setup (React + Vite)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`).

By default the frontend calls the API at `http://localhost:8000`. To point it
somewhere else (e.g. a deployed backend), create `frontend/.env.local` with:

```
VITE_API_BASE_URL=https://your-backend-host
```

## How it works

1. You type a company name, pick the **mandatory** country, and optionally add
   an industry hint, then click **Research Company**.
2. On load, the frontend calls `GET /countries` to populate the country
   dropdown from the backend's own `COUNTRY_PROFILES` (falls back to a static
   list if that request fails, so the form still works offline).
3. Submitting sends `POST /research` with
   `{ "company_name": "...", "country": "CN", "industry_hint": "..." }`.
4. FastAPI calls `research_company(company_name, country, industry_hint)` from
   `research_agent_newest.py` — the exact same function you had, doing the
   exact same country-scoped SerpAPI + requests + BeautifulSoup work.
5. The function's return value (a dict) is sent back as JSON and rendered as a
   dossier card: company, country, official website, phone, email, address
   (with the original Chinese address shown alongside its English translation
   when the company is Chinese), location, contact person, designation,
   industry, products, WeChat/WhatsApp (with a "Preferred" badge on whichever
   the backend picked), and clickable sources. A confidence badge (High /
   Medium / Low) is computed client-side from how many core fields were found.
   Any field the script couldn't find is shown as "Not found" rather than
   being hidden or crashing the page.
6. Any `print()` statements inside `research_agent_newest.py` still print to
   the backend's terminal (they're just progress logs) — the data itself now
   also reaches the browser via the API response, which is what the UI renders.

## Notes

- CORS in `main.py` is scoped to `http://localhost:5173` and
  `http://127.0.0.1:5173` (Vite's default). Add any other frontend origin you
  deploy to in the `allow_origins` list.
- `main.py` forces UTF-8 on stdout/stderr at startup. Without this, the
  research engine's emoji progress logs (🔎, 🌐, ...) crash every request on
  Windows consoles that default to a non-UTF-8 codepage — this is an
  environment fix at the HTTP entrypoint, not a change to the research logic.
- If a search takes a long time (SerpAPI + several page fetches, especially
  for China where multiple contact-page paths are each tried with their own
  timeout), that's the backend doing real network calls — the loading state
  in the UI reflects the full round trip and only clears once the response
  comes back or fails.
- If `/research` returns an error, the frontend shows it inline with a retry
  button rather than failing silently.
