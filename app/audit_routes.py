from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.models import (
    SessionLocal,
    MatchModel,
    TacticalFindingModel,
    CoachMemoryModel,
    AccessLogModel,
)
from agent.tools import (
    read_shared_findings,
    correct_shared_finding,
    read_team_memory,
    write_team_memory,
    publish_finding_to_team_memory,
    list_access_logs,
    _serialize_finding,
    _serialize_memory,
)
from agent.workflow import compiled_graph

router = APIRouter(prefix="/api/audit", tags=["audit"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class CorrectFindingRequest(BaseModel):
    actor: str = Field(..., description="spatial_analyst or head_coach")
    new_body: str = Field(..., min_length=1)
    new_kind: Optional[str] = Field(default=None)


class CoachResumeRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    feedback: str = Field(default="approved")
    publish_to_team: str = Field(default="team_alpha")


class AccessTestRequest(BaseModel):
    actor: str = Field(..., description="e.g. coach_bravo, economy_analyst, spatial_analyst, coach_alpha, head_coach")
    action: str = Field(default="read_private_memory", description="read_private_memory | write_private_memory | publish_to_team_memory")
    team: str = Field(default="team_alpha")
    match_id: Optional[str] = Field(default=None)
    note_body: Optional[str] = Field(default="Attempted unauthorized note write.")


class PrivateNoteCreateRequest(BaseModel):
    actor: str = Field(..., description="coach_alpha or coach_bravo")
    body: str = Field(..., min_length=1)
    kind: str = Field(default="note")
    match_id: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Helpers for Live Telemetry Trace & Playbook
# ---------------------------------------------------------------------------

STAGE_ORDER = ["ingested", "economy_done", "spatial_done", "awaiting_coach", "completed"]


def _build_handoff_trace(match: MatchModel, findings: List[TacticalFindingModel]) -> List[Dict[str, Any]]:
    stage = match.pipeline_stage or "ingested"
    current_idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0

    econ_rows = [f for f in findings if f.author == "economy_analyst"]
    spatial_rows = [f for f in findings if f.author == "spatial_analyst"]
    coach_rows = [f for f in findings if f.author == "head_coach" and f.kind == "directive"]

    return [
        {
            "step": 1,
            "agent": "economy_analyst",
            "label": "Economy Analyst → Spatial",
            "stage_key": "economy_done",
            "completed": current_idx >= STAGE_ORDER.index("economy_done"),
            "active": stage == "economy_done",
            "findings_count": len(econ_rows),
            "summary": (
                econ_rows[-1].body
                if econ_rows
                else "Pending round economy evaluation."
            ),
            "handoff_note": match.handoff_note if stage == "economy_done" else (
                "Handed economy findings to Spatial Analyst for site/trade check."
                if current_idx > STAGE_ORDER.index("economy_done")
                else None
            ),
        },
        {
            "step": 2,
            "agent": "spatial_analyst",
            "label": "Spatial / Map Control → Head Coach",
            "stage_key": "spatial_done",
            "completed": current_idx >= STAGE_ORDER.index("spatial_done"),
            "active": stage == "spatial_done",
            "findings_count": len(spatial_rows),
            "summary": (
                spatial_rows[-1].body
                if spatial_rows
                else "Pending spatial & site rotation review."
            ),
            "handoff_note": match.handoff_note if stage == "spatial_done" else (
                "Handed spatial & corrected findings to Head Coach."
                if current_idx > STAGE_ORDER.index("spatial_done")
                else None
            ),
        },
        {
            "step": 3,
            "agent": "head_coach",
            "label": "Head Coach Directive & Approval",
            "stage_key": "awaiting_coach",
            "completed": stage == "completed",
            "active": stage == "awaiting_coach",
            "findings_count": len(coach_rows),
            "summary": (
                coach_rows[-1].body
                if coach_rows
                else "Awaiting directive draft from active shared findings."
            ),
            "handoff_note": (
                "Paused at LangGraph interrupt; ready to resume & publish to Team Alpha."
                if stage == "awaiting_coach"
                else ("Completed and published to Team Alpha memory." if stage == "completed" else None)
            ),
        },
    ]


# ---------------------------------------------------------------------------
# 1. Match Trace, Playbook & Shared Findings
# ---------------------------------------------------------------------------

@router.get("/matches/{match_id}/overview")
def get_match_audit_overview(match_id: str, db: Session = Depends(get_db)):
    match = db.query(MatchModel).filter(MatchModel.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail=f"Match '{match_id}' not found.")

    all_findings = (
        db.query(TacticalFindingModel)
        .filter(
            TacticalFindingModel.match_id == match_id,
            TacticalFindingModel.visibility == "shared",
        )
        .order_by(TacticalFindingModel.id.asc())
        .all()
    )
    active_findings = [f for f in all_findings if f.status == "active"]
    trace = _build_handoff_trace(match, all_findings)

    # Check if LangGraph has an active interrupt payload for this thread_id
    interrupt_payload = None
    try:
        snap = compiled_graph.get_state({"configurable": {"thread_id": match_id}})
        if snap and getattr(snap, "tasks", None):
            for task in snap.tasks:
                if getattr(task, "interrupts", None):
                    interrupt_payload = task.interrupts[0].value
                    break
    except Exception:
        interrupt_payload = None

    return {
        "match_id": match.match_id,
        "map_name": match.map_name,
        "status": match.status,
        "pipeline_stage": match.pipeline_stage,
        "handoff_note": match.handoff_note,
        "coach_review": match.coach_review,
        "final_brief": match.final_brief,
        "trace": trace,
        "findings": [_serialize_finding(f) for f in all_findings],
        "active_findings": [_serialize_finding(f) for f in active_findings],
        "interrupt": interrupt_payload,
    }


@router.get("/matches/{match_id}/findings")
def get_shared_findings(
    match_id: str,
    actor: str = Query(default="head_coach"),
    include_outdated: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    res = read_shared_findings(
        actor=actor,
        match_id=match_id,
        include_outdated=include_outdated,
        db=db,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=403, detail=res.get("error", "Access denied"))
    return res


@router.post("/findings/{finding_id}/correct")
def correct_finding_endpoint(
    finding_id: int,
    payload: CorrectFindingRequest,
    db: Session = Depends(get_db),
):
    res = correct_shared_finding(
        actor=payload.actor,
        finding_id=finding_id,
        new_body=payload.new_body,
        new_kind=payload.new_kind,
        db=db,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=403, detail=res.get("error", "Correction denied"))
    return res


@router.get("/matches/{match_id}/playbook")
def get_derived_playbook(match_id: str, db: Session = Depends(get_db)):
    """Builds the playbook strictly from status='active' shared findings and approved directive."""
    match = db.query(MatchModel).filter(MatchModel.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail=f"Match '{match_id}' not found.")

    active_rows = (
        db.query(TacticalFindingModel)
        .filter(
            TacticalFindingModel.match_id == match_id,
            TacticalFindingModel.visibility == "shared",
            TacticalFindingModel.status == "active",
        )
        .order_by(TacticalFindingModel.id.asc())
        .all()
    )

    directives = [r.body for r in active_rows if r.kind == "directive"]
    non_directives = [r for r in active_rows if r.kind != "directive"]

    return {
        "match_id": match.match_id,
        "map_name": match.map_name,
        "pipeline_stage": match.pipeline_stage,
        "active_findings": [_serialize_finding(r) for r in non_directives],
        "approved_directive": match.coach_review or (directives[-1] if directives else None),
        "playbook_text": match.final_brief,
    }


# ---------------------------------------------------------------------------
# 2. Private Team Memories & Access Denial Demo Endpoint
# ---------------------------------------------------------------------------

@router.get("/memories/{team}")
def get_team_memories_endpoint(
    team: str,
    actor: str = Query(..., description="coach_alpha | coach_bravo | head_coach | economy_analyst | spatial_analyst"),
    match_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    res = read_team_memory(actor=actor, team=team, match_id=match_id, db=db)
    if not res.get("ok"):
        return {
            "ok": False,
            "allowed": False,
            "error": res.get("error"),
            "log": res.get("log"),
            "memories": [],
        }
    return {
        "ok": True,
        "allowed": True,
        "team": res.get("team"),
        "memories": res.get("memories", []),
        "log": res.get("log"),
    }


@router.post("/memories/{team}")
def create_team_memory_endpoint(
    team: str,
    payload: PrivateNoteCreateRequest,
    db: Session = Depends(get_db),
):
    res = write_team_memory(
        actor=payload.actor,
        team=team,
        body=payload.body,
        kind=payload.kind,
        match_id=payload.match_id,
        db=db,
    )
    if not res.get("ok"):
        return {
            "ok": False,
            "allowed": False,
            "error": res.get("error"),
            "log": res.get("log"),
        }
    return {
        "ok": True,
        "allowed": True,
        "memory": res.get("memory"),
        "log": res.get("log"),
    }


@router.post("/access-test")
def run_access_test(payload: AccessTestRequest, db: Session = Depends(get_db)):
    """
    Executes a read/write/publish check through agent/tools.py so allowed and denied
    attempts both record an access_log entry in SQLite without mutating blocked rows.
    """
    if payload.action == "read_private_memory":
        return read_team_memory(
            actor=payload.actor,
            team=payload.team,
            match_id=payload.match_id,
            db=db,
        )
    if payload.action == "write_private_memory":
        return write_team_memory(
            actor=payload.actor,
            team=payload.team,
            body=payload.note_body or "Unauthorized write probe.",
            match_id=payload.match_id,
            db=db,
        )
    if payload.action == "publish_to_team_memory":
        return publish_finding_to_team_memory(
            actor=payload.actor,
            team=payload.team,
            directive_text=payload.note_body or "Unauthorized publish probe.",
            match_id=payload.match_id,
            db=db,
        )
    raise HTTPException(status_code=400, detail=f"Unsupported access test action '{payload.action}'.")


@router.get("/access-log")
def get_access_log_endpoint(
    match_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return {"logs": list_access_logs(match_id=match_id, limit=limit, db=db)}


# ---------------------------------------------------------------------------
# 3. Resume Paused Coach Interrupt Across Restarts
# ---------------------------------------------------------------------------

@router.post("/coach/resume")
def resume_coach_interrupt(payload: CoachResumeRequest, db: Session = Depends(get_db)):
    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        result = compiled_graph.invoke(Command(resume=payload.feedback), config=config)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not resume thread '{payload.thread_id}': {exc}",
        ) from exc

    match = db.query(MatchModel).filter(MatchModel.match_id == payload.thread_id).first()
    return {
        "ok": True,
        "thread_id": payload.thread_id,
        "pipeline_stage": match.pipeline_stage if match else "completed",
        "status": match.status if match else "Completed",
        "final_playbook": result.get("final_playbook") or (match.final_brief if match else None),
    }