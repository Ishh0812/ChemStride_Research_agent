Company Intel"""
FastAPI backend for the company research tool.

This file only adds an HTTP layer. All research/extraction logic lives
untouched in research_agent_newest.py — this module imports and calls
research_company(company_name, country, industry_hint) and returns its
result as JSON.
"""

import logging
import sys

# research_agent_newest.py logs progress with emoji (🔎, 🌐, ...). On Windows
# stdout can default to a non-UTF-8 codepage, which turns every request into
# a crash. Force UTF-8 here at the HTTP entrypoint, not in the research logic.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from research_agent_newest import COUNTRY_PROFILES, MENU_ORDER, research_company

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("research-api")

app = FastAPI(title="Company Research API", version="1.0.0")

# Vite's default dev server ports. Add your deployed frontend origin here too.
app.add_middleware(
    CORSMiddleware,
   allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://chem-stride-research-agent.vercel.app",
]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    company_name: str = Field(..., min_length=1, description="Company name to research")
    country: str = Field(..., min_length=1, description="ISO country code, e.g. 'CN' or 'IN'")
    industry_hint: str | None = Field(None, description="Optional industry hint to narrow the search")
    include_linkedin: bool = Field(True, description="Run the LinkedIn people pass (CN/IN only)")


@app.get("/health")
def health():
    """Simple liveness check the frontend (or you) can hit to confirm the API is up."""
    return {"status": "ok"}


@app.get("/countries")
def countries():
    """Country list for the frontend's dropdown, sourced from the research agent's own profiles."""
    return [
        {"code": code, "name": COUNTRY_PROFILES[code]["name"], "dial_code": "+" + COUNTRY_PROFILES[code]["dial_code"]}
        for code in MENU_ORDER
    ]


@app.post("/research")
def research(payload: ResearchRequest):
    company_name = payload.company_name.strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="company_name cannot be empty")

    industry_hint = (payload.industry_hint or "").strip() or None

    logger.info("Research request received: %s (%s)", company_name, payload.country)
    try:
        result = research_company(
            company_name,
            country=payload.country,
            industry_hint=industry_hint,
            include_linkedin=payload.include_linkedin,
        )
    except Exception as exc:  # noqa: BLE001 - surface any extraction failure to the client
        logger.exception("Research failed for %s", company_name)
        raise HTTPException(
            status_code=500,
            detail=f"Research failed for '{company_name}': {exc}",
        ) from exc

    return result
