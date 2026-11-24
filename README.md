# Valorant Tactical Scouting Agent

A multi-agent, human-in-the-loop Valorant Ranked match coaching system built with **FastAPI**, **LangGraph**, **SQLAlchemy (SQLite)**, and **React + Tailwind CSS**.

---

## API Keys & Credentials (Entered Directly in the UI)

No API keys are hardcoded in this repository, and you do **not** need to set up a `.env` file. Enter both keys directly into the web interface:

1. **HenrikDev Valorant API Key (`Match Lookup Key`)**:
   * **Provided separately via email** with the project submission.
   * Paste this key into the **Match Lookup Key** input field in the web UI to pull real Valorant Ranked match data.
2. **Google Gemini API Key (`Your Gemini API Key`)**:
   * **Please use your own Gemini API key** (free tier works out of the box—no billing setup required).
   * Create a free key at **[Google AI Studio](https://aistudio.google.com/)** → **Get API key** → **Create API key**.
   * Paste your Gemini API key directly into the **Your Gemini API Key** input box in the web UI when running a match review.

---

## Prerequisites

* **Python 3.11+** with [`uv`](https://docs.astral.sh/uv/) installed
* **Node.js 18+** and `npm`

---

## Quick Start

### 1. Clone the Repository

```bash
git clone [https://github.com/rupikarasaili/valorant_agent.git](https://github.com/rupikarasaili/valorant_agent.git)
cd valorant_agent
```

### 2. Start the Backend Server (FastAPI + LangGraph)

Install dependencies and launch Uvicorn from the project root:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

> **Note:** Run `app.main:app` (not `main:app`), as `main.py` is located inside the `app/` directory. The backend runs at **`http://127.0.0.1:8000`** and automatically creates the local SQLite databases (`valorant_scout.db` and `checkpoints.sqlite`) on startup.

### 3. Start the Frontend Dashboard (React + Vite)

Open a **second terminal**, navigate to `frontend/`, install dependencies, and start the dev server:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL displayed in your terminal (typically **`http://localhost:5173`**) in your browser.

---

## Step-by-Step Demo Walkthrough

1. **Enter Match & API Credentials** on the **Recent Ranked Matches** tab:
   * **Match Lookup Key**: Paste the HenrikDev API key sent via email.
   * **Region**: Select `North America` (or the player's region).
   * **Riot ID Name & Tagline**: Enter a valid Riot ID (e.g., `Szohn` and `NA1`).
   * **Your Gemini API Key**: Paste your own Gemini API key from [Google AI Studio](https://aistudio.google.com/) directly into the UI field.
2. **Select a Match & Agent**:
   * The player's last 5 Ranked matches and detected agent auto-populate in the dropdowns.
   * Click **Review Selected Match**.
3. **Human-in-the-Loop Coach Approval**:
   * The LangGraph workflow runs the **Economy Specialist** and **Map & Entry Specialist**, then pauses at a LangGraph `interrupt()` checkpoint (**Coach Review Needed Before Sharing**).
   * Review or edit the suggested team callout and click **Approve & Open Round-by-Round Review**.
4. **Explore Round-by-Round Coaching Cards**:
   * The app switches automatically to the **Round-by-Round** tab, displaying individualized feedback (*What You Could Have Done Better* and *What Your Team Could Have Done Better*) for `Round 1`, `Round 2`, `Round 3`, and every round played.
   * Use the **All Rounds / Won Rounds / Lost Rounds** toggle at the top to filter rounds.
5. **Inspect Multi-Agent Handoffs, Memory Isolation & Audit Logs**:
   * Open **Team Notes & History** in the sidebar to inspect the 3-step specialist trace, edit shared tactical findings (with version history), switch between **Coach Alpha (Team Alpha)** and **Coach Bravo (Team Bravo)** private notebooks, and test role-based access enforcement in the **Activity & Privacy Log**.

---

## System Architecture

```text
valorant_agent/
├── agent/
│   ├── api_client.py      # HenrikDev Valorant API client & match parser
│   ├── state.py           # LangGraph TypedDict state definition
│   ├── tools.py           # Economy, spatial trade, shared board & RBAC memory tools
│   └── workflow.py        # Multi-agent StateGraph, interrupt gate & batched LLM synthesis
├── app/
│   ├── main.py            # FastAPI endpoints (/api/recent-matches, /api/ingest, /api/resume)
│   └── audit_routes.py    # Shared findings, private team memory & access-log routes
├── database/
│   └── models.py          # SQLAlchemy ORM models & SQLite database setup
├── frontend/
│   └── src/
│       └── App.jsx        # Multi-tab React + Tailwind coaching dashboard
└── pyproject.toml         # Python dependencies managed by uv
```