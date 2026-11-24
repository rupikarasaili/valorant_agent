# Valorant Tactical Scouting & Performance Agent

**Course:** Agentic AI (ITS 58100) - Project 1  
**Student:** Crystal Shrestha  

## Architecture Overview
- **Database (`database/models.py`):** SQLAlchemy persistent SQLite storage for match telemetry and tactical briefs.
- **Agent (`agent/`):** LangGraph state machine (`workflow.py`), deterministic analysis tools (`tools.py`), and typed state definitions (`state.py`).
- **Dashboard (`app/dashboard.py`):** Streamlit frontend supporting match telemetry ingestion, interactive human-in-the-loop coach reviews, and database record inspection.

## Setup & Execution
1. Install dependencies:
   ```bash
   pip install -r requirements.txt

## Run code

- macOS / Linux:

PYTHONPATH=. streamlit run app/dashboard.py

-Windows (PowerShell):

$env:PYTHONPATH="."; streamlit run app/dashboard.py

-Windows (Command Prompt):

set PYTHONPATH=.
streamlit run app/dashboard.py
