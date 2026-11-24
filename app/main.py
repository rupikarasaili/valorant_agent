import time
from typing import Dict, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langgraph.types import Command

from database.models import SessionLocal, MatchModel, init_db
from agent.workflow import compiled_graph
from agent.api_client import fetch_player_matches, parse_henrik_match
from app.audit_routes import router as audit_router

init_db()
app = FastAPI(title="Valorant Ranked Coaching API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit_router)

# Short-lived cache (5 min) so browsing matches/agents doesn't waste HenrikDev requests
_MATCH_CACHE: Dict[Tuple[str, str, str], Tuple[float, list]] = {}
_CACHE_TTL_SECONDS = 300.0


def _get_cached_matches(region: str, name: str, tag: str, api_key: str, size: int = 5):
    key = (region.strip().lower(), name.strip().lower(), tag.strip().lower())
    now = time.time()
    cached = _MATCH_CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS and len(cached[1]) >= size:
        return cached[1]
    matches = fetch_player_matches(region, name, tag, api_key, size=size)
    _MATCH_CACHE[key] = (now, matches)
    return matches


class RecentMatchesRequest(BaseModel):
    region: str
    name: str
    tag: str
    api_key: str


class IngestRequest(BaseModel):
    region: str
    name: str
    tag: str
    api_key: str
    llm_api_key: str | None = None
    selected_match_id: str | None = None
    agent_name: str | None = None
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    coach_feedback: str


def _extract_player_agent(raw_match: dict, name: str, tag: str) -> str:
    players = (raw_match.get("players") or {}).get("all_players") or []
    target_name = (name or "").strip().lower()
    target_tag = (tag or "").strip().lower()
    for p in players:
        p_name = (p.get("name") or "").strip().lower()
        p_tag = (p.get("tag") or "").strip().lower()
        if p_name == target_name and (not target_tag or p_tag == target_tag):
            return p.get("character") or "Jett"
    return players[0].get("character") if players and players[0].get("character") else "Jett"


@app.post("/api/recent-matches")
def get_recent_matches(req: RecentMatchesRequest):
    try:
        raw_matches = _get_cached_matches(req.region, req.name, req.tag, req.api_key, size=5)
        if not raw_matches:
            raise HTTPException(status_code=404, detail="No recent matches found for this Riot ID.")

        items = []
        for idx, m in enumerate(raw_matches[:5]):
            meta = m.get("metadata") or {}
            match_id = meta.get("matchid") or f"match-{idx + 1}"
            map_name = meta.get("map") or "Unknown Map"
            mode = meta.get("mode") or "Ranked"
            agent_played = _extract_player_agent(m, req.name, req.tag)
            items.append(
                {
                    "match_id": match_id,
                    "map_name": map_name,
                    "mode": mode,
                    "agent_played": agent_played,
                    "label": f"Game {idx + 1}: {map_name} ({mode}) — Played {agent_played}",
                }
            )

        return {"matches": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ingest")
def ingest_and_run(req: IngestRequest):
    try:
        fetch_size = 5 if req.selected_match_id else 1
        raw_matches = _get_cached_matches(
            req.region, req.name, req.tag, req.api_key, size=fetch_size
        )
        if not raw_matches:
            raise HTTPException(status_code=404, detail="No matches found for this Riot ID.")

        chosen_raw = raw_matches[0]
        if req.selected_match_id:
            for m in raw_matches:
                meta = m.get("metadata") or {}
                if meta.get("matchid") == req.selected_match_id:
                    chosen_raw = m
                    break

        parsed_payload = parse_henrik_match(
            chosen_raw, player_name=req.name, player_tag=req.tag
        )
        detected_agent = _extract_player_agent(chosen_raw, req.name, req.tag)
        parsed_payload["agent_name"] = (req.agent_name or "").strip() or detected_agent
        parsed_payload["llm_api_key"] = (req.llm_api_key or "").strip() or None

        effective_thread_id = req.thread_id or parsed_payload["match_id"]
        config = {"configurable": {"thread_id": effective_thread_id}}

        snapshot = compiled_graph.invoke(parsed_payload, config=config)

        if isinstance(snapshot, dict) and "__interrupt__" in snapshot:
            interrupt_data = snapshot["__interrupt__"]
            prompt = interrupt_data[0].value if hasattr(interrupt_data[0], "value") else str(interrupt_data[0])
            return {
                "status": "paused",
                "thread_id": effective_thread_id,
                "interrupt_prompt": prompt,
                "match_id": parsed_payload["match_id"],
                "map_name": parsed_payload["map_name"],
                "agent_name": parsed_payload["agent_name"],
            }

        return {
            "status": "completed",
            "thread_id": effective_thread_id,
            "match_id": parsed_payload["match_id"],
            "map_name": parsed_payload["map_name"],
            "agent_name": parsed_payload["agent_name"],
            "final_playbook": snapshot.get("final_playbook", ""),
            "round_reviews": snapshot.get("round_reviews", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/resume")
def resume_workflow(req: ResumeRequest):
    try:
        config = {"configurable": {"thread_id": req.thread_id}}
        final_output = compiled_graph.invoke(Command(resume=req.coach_feedback), config=config)
        return {
            "status": "completed",
            "thread_id": req.thread_id,
            "final_playbook": final_output.get("final_playbook", ""),
            "round_reviews": final_output.get("round_reviews", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/matches")
def get_matches():
    db: Session = SessionLocal()
    try:
        matches = db.query(MatchModel).all()
        return [
            {
                "match_id": m.match_id,
                "map_name": m.map_name,
                "status": m.status,
                "pipeline_stage": m.pipeline_stage,
                "handoff_note": m.handoff_note,
                "coach_review": m.coach_review,
                "final_brief": m.final_brief,
            }
            for m in matches
        ]
    finally:
        db.close()