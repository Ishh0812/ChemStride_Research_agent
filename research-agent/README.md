ChemStride Agent
AI-powered company research dashboard built with React + Vite and FastAPI. It uses SerpAPI, Requests, and BeautifulSoup to research companies across country-specific web sources and LinkedIn.
Features
- 🌍 Mandatory country-based research
- 🔎 Company and industry research
- 🌐 Official website and web-source extraction
- 📞 Phone, email, address & contact details
- 🇨🇳 Chinese website/address translation
- 💼 LinkedIn people research
- 📱 WeChat / WhatsApp extraction
- 📊 Confidence-based research results
- 🔗 Clickable sources
Project Structure
research-agent/
├── backend/
│   ├── main.py
│   ├── research_agent_newest.py
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/
    ├── src/
    ├── package.json
    └── vite.config.js
Tech Stack
Frontend: React, Vite
Backend: Python, FastAPI
Research: SerpAPI, Requests, BeautifulSoup
Deployment: Vercel + Render
Local Setup
Backend
cd backend
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Create .env:
SERPAPI_API_KEY=your_api_key
Run:
uvicorn main:app --reload --port 8000
Frontend
cd frontend
npm install
npm run dev
For local development:
VITE_API_BASE_URL=http://localhost:8000
Production
Frontend:
https://chem-stride-research-agent.vercel.app
Backend:
https://chemstride-research-agent-1.onrender.com
The production frontend communicates with the FastAPI backend through the configured VITE_API_BASE_URL.
Note: Use Python 3.12 for the backend environment. Never commit .env, venv/, or node_modules/.
