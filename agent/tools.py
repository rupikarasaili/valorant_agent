from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from database.models import (
    SessionLocal,
    TacticalFindingModel,
    CoachMemoryModel,
    AccessLogModel,
)

VALID_TEAMS = {"team_alpha", "team_bravo"}


# ---------------------------------------------------------------------------
# 0. Existing Round-Level Analytical Tools (Preserved)
# ---------------------------------------------------------------------------

@tool
def analyze_economy_discipline(team_spend: int, enemy_spend: int, won: bool, round_num: int) -> str:
    """Performs an in-depth financial risk analysis for a given round."""
    if team_spend > 18000 and enemy_spend < 6000 and not won:
        return (
            f"[ECO-THROW DETECTED in Round {round_num}] "
            f"The team invested heavily ({team_spend:,} credits) into full rifles and utility, "
            f"but suffered an upset defeat against an enemy eco/save round ({enemy_spend:,} credits). "
            f"Root Cause: Over-peeking close angles against aggressive sheriff/spectre positioning without scanning with recon utility."
        )
    elif team_spend < 6000 and enemy_spend > 18000:
        return f"[Round {round_num}] Tactical Save Executed: Successfully preserved economy against an enemy full-buy."
    return f"[Round {round_num}] Economy management aligned with standard competitive buy matrix."


@tool
def evaluate_entry_trades(untraded_deaths: int, site: str, round_num: int) -> str:
    """Evaluates spatial control and entry success metrics on site executes."""
    if untraded_deaths >= 2:
        return (
            f"[SPATIAL COLLAPSE in Round {round_num} on {site}] "
            f"Recorded {untraded_deaths} un-traded opening casualties. "
            f"Tactical Implication: Duelists or initiators are dry-peeking choke points without simultaneous flash/smoke coordination, "
            f"resulting in immediate numerical disadvantage and stalled site executes."
        )
    return f"[Round {round_num}] Clean entry spacing and trade execution on {site}."


# ---------------------------------------------------------------------------
# Internal Helpers & Audit Logging
# ---------------------------------------------------------------------------

def _normalize_team(team: Optional[str]) -> Optional[str]:
    if not team:
        return None
    t = team.strip().lower()
    if t in {"alpha", "team_alpha", "coach_alpha"}:
        return "team_alpha"
    if t in {"bravo", "team_bravo", "coach_bravo"}:
        return "team_bravo"
    return t


def _log_access(
    db: Session,
    *,
    actor: str,
    action: str,
    target: str,
    result: str,
    reason: str,
    match_id: Optional[str] = None,
) -> Dict[str, Any]:
    entry = AccessLogModel(
        match_id=match_id,
        actor=actor,
        action=action,
        target=target,
        result=result,
        reason=reason,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id,
        "match_id": entry.match_id,
        "actor": entry.actor,
        "action": entry.action,
        "target": entry.target,
        "result": entry.result,
        "reason": entry.reason,
        "created_at": entry.created_at.isoformat(),
    }


def _serialize_finding(row: TacticalFindingModel) -> Dict[str, Any]:
    return {
        "id": row.id,
        "match_id": row.match_id,
        "author": row.author,
        "kind": row.kind,
        "body": row.body,
        "status": row.status,
        "version": row.version,
        "corrects_id": row.corrects_id,
        "visibility": row.visibility,
        "owner": row.owner,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_memory(row: CoachMemoryModel) -> Dict[str, Any]:
    return {
        "id": row.id,
        "match_id": row.match_id,
        "author": row.author,
        "kind": row.kind,
        "body": row.body,
        "status": row.status,
        "version": row.version,
        "corrects_id": row.corrects_id,
        "visibility": row.visibility,
        "owner": row.owner,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# 1. Shared Tactical Findings Tools
# ---------------------------------------------------------------------------

def read_shared_findings(
    actor: str,
    match_id: str,
    include_outdated: bool = False,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Read shared findings for a match (all actors in the matrix are allowed)."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        allowed_actors = {
            "economy_analyst",
            "spatial_analyst",
            "head_coach",
            "coach_alpha",
            "coach_bravo",
        }
        if actor not in allowed_actors:
            log = _log_access(
                db,
                actor=actor,
                action="read_shared",
                target=f"tactical_findings:shared:{match_id}",
                result="denied",
                reason=f"Unknown actor '{actor}' cannot read shared findings.",
                match_id=match_id,
            )
            return {"ok": False, "error": log["reason"], "log": log, "findings": []}

        q = db.query(TacticalFindingModel).filter(
            TacticalFindingModel.match_id == match_id,
            TacticalFindingModel.visibility == "shared",
        )
        if not include_outdated:
            q = q.filter(TacticalFindingModel.status == "active")

        rows = q.order_by(TacticalFindingModel.id.asc()).all()
        log = _log_access(
            db,
            actor=actor,
            action="read_shared",
            target=f"tactical_findings:shared:{match_id}",
            result="allowed",
            reason=f"{actor} read {len(rows)} {'all' if include_outdated else 'active'} shared finding(s).",
            match_id=match_id,
        )
        return {
            "ok": True,
            "findings": [_serialize_finding(r) for r in rows],
            "log": log,
        }
    finally:
        if owns_session:
            db.close()


def write_shared_finding(
    actor: str,
    match_id: str,
    kind: str,
    body: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Write a new shared finding:
    - economy_analyst -> kind='economy'
    - spatial_analyst -> kind='spatial'
    - head_coach -> kind='directive'
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        permissions = {
            "economy_analyst": {"economy"},
            "spatial_analyst": {"spatial"},
            "head_coach": {"directive"},
        }
        allowed_kinds = permissions.get(actor, set())
        if kind not in allowed_kinds:
            log = _log_access(
                db,
                actor=actor,
                action="write_shared",
                target=f"tactical_findings:shared:{match_id}:{kind}",
                result="denied",
                reason=f"{actor} is not permitted to write shared finding of kind '{kind}'.",
                match_id=match_id,
            )
            return {"ok": False, "error": log["reason"], "log": log}

        row = TacticalFindingModel(
            match_id=match_id,
            author=actor,
            kind=kind,
            body=body,
            status="active",
            version=1,
            corrects_id=None,
            visibility="shared",
            owner=None,
        )
        db.add(row)
        db.flush()

        log = _log_access(
            db,
            actor=actor,
            action="write_shared",
            target=f"tactical_findings:shared:{match_id}:#{row.id}",
            result="allowed",
            reason=f"{actor} wrote shared {kind} finding #{row.id}.",
            match_id=match_id,
        )
        db.commit()
        db.refresh(row)
        return {"ok": True, "finding": _serialize_finding(row), "log": log}
    finally:
        if owns_session:
            db.close()


def correct_shared_finding(
    actor: str,
    finding_id: int,
    new_body: str,
    new_kind: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Non-destructive correction:
    Marks the old finding row as status='corrected' and inserts a new active row
    with version = old.version + 1 and corrects_id = old.id.
    Allowed for spatial_analyst and head_coach.
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        old = (
            db.query(TacticalFindingModel)
            .filter(TacticalFindingModel.id == finding_id)
            .first()
        )
        if not old:
            return {"ok": False, "error": f"Finding #{finding_id} not found."}

        if actor not in {"spatial_analyst", "head_coach"}:
            log = _log_access(
                db,
                actor=actor,
                action="correct_finding",
                target=f"tactical_findings:#{finding_id}",
                result="denied",
                reason=f"{actor} cannot file a finding correction.",
                match_id=old.match_id,
            )
            return {"ok": False, "error": log["reason"], "log": log}

        old.status = "corrected"
        replacement = TacticalFindingModel(
            match_id=old.match_id,
            author=actor,
            kind=new_kind or old.kind,
            body=new_body,
            status="active",
            version=(old.version or 1) + 1,
            corrects_id=old.id,
            visibility="shared",
            owner=None,
        )
        db.add(replacement)
        db.flush()

        log = _log_access(
            db,
            actor=actor,
            action="correct_finding",
            target=f"tactical_findings:#{old.id}->#{replacement.id}",
            result="allowed",
            reason=f"{actor} marked finding #{old.id} as corrected and inserted active replacement #{replacement.id}.",
            match_id=old.match_id,
        )
        db.commit()
        db.refresh(old)
        db.refresh(replacement)
        return {
            "ok": True,
            "corrected_finding": _serialize_finding(old),
            "active_finding": _serialize_finding(replacement),
            "log": log,
        }
    finally:
        if owns_session:
            db.close()


# ---------------------------------------------------------------------------
# 2. Private Team Memory Tools (team_alpha vs team_bravo)
# ---------------------------------------------------------------------------

def read_team_memory(
    actor: str,
    team: str,
    match_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Read private memory for a team ('team_alpha' or 'team_bravo'):
    - economy_analyst -> denied
    - spatial_analyst -> denied
    - coach_alpha -> allowed ONLY for team_alpha
    - coach_bravo -> allowed ONLY for team_bravo
    - head_coach -> allowed when publishing/reviewing both teams
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        target_team = _normalize_team(team)
        if target_team not in VALID_TEAMS:
            return {"ok": False, "error": f"Invalid team '{team}'. Use team_alpha or team_bravo."}

        allowed = (
            (actor == "coach_alpha" and target_team == "team_alpha")
            or (actor == "coach_bravo" and target_team == "team_bravo")
            or (actor == "head_coach")
        )

        if not allowed:
            log = _log_access(
                db,
                actor=actor,
                action="read_private_memory",
                target=f"coach_memories:{target_team}",
                result="denied",
                reason=f"Access denied: {actor} is not authorized to read {target_team} private memory.",
                match_id=match_id,
            )
            return {"ok": False, "error": log["reason"], "log": log, "memories": []}

        rows = (
            db.query(CoachMemoryModel)
            .filter(
                CoachMemoryModel.owner == target_team,
                CoachMemoryModel.visibility == "private",
                CoachMemoryModel.status == "active",
            )
            .order_by(CoachMemoryModel.id.asc())
            .all()
        )
        log = _log_access(
            db,
            actor=actor,
            action="read_private_memory",
            target=f"coach_memories:{target_team}",
            result="allowed",
            reason=f"{actor} read {len(rows)} active private memory note(s) for {target_team}.",
            match_id=match_id,
        )
        return {
            "ok": True,
            "team": target_team,
            "memories": [_serialize_memory(r) for r in rows],
            "log": log,
        }
    finally:
        if owns_session:
            db.close()


def write_team_memory(
    actor: str,
    team: str,
    body: str,
    kind: str = "note",
    match_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Write directly to a team's private memory:
    - coach_alpha -> allowed ONLY for team_alpha
    - coach_bravo -> allowed ONLY for team_bravo
    - economy_analyst / spatial_analyst / head_coach direct write -> denied
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        target_team = _normalize_team(team)
        if target_team not in VALID_TEAMS:
            return {"ok": False, "error": f"Invalid team '{team}'. Use team_alpha or team_bravo."}

        allowed = (actor == "coach_alpha" and target_team == "team_alpha") or (
            actor == "coach_bravo" and target_team == "team_bravo"
        )

        if not allowed:
            log = _log_access(
                db,
                actor=actor,
                action="write_private_memory",
                target=f"coach_memories:{target_team}",
                result="denied",
                reason=f"Access denied: {actor} cannot write private memory for {target_team}.",
                match_id=match_id,
            )
            return {"ok": False, "error": log["reason"], "log": log}

        row = CoachMemoryModel(
            match_id=match_id,
            author=actor,
            kind=kind,
            body=body,
            status="active",
            version=1,
            corrects_id=None,
            visibility="private",
            owner=target_team,
        )
        db.add(row)
        db.flush()

        log = _log_access(
            db,
            actor=actor,
            action="write_private_memory",
            target=f"coach_memories:{target_team}:#{row.id}",
            result="allowed",
            reason=f"{actor} added private memory #{row.id} to {target_team}.",
            match_id=match_id,
        )
        db.commit()
        db.refresh(row)
        return {"ok": True, "memory": _serialize_memory(row), "log": log}
    finally:
        if owns_session:
            db.close()


def publish_finding_to_team_memory(
    actor: str,
    team: str,
    finding_id: Optional[int] = None,
    directive_text: Optional[str] = None,
    match_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Head Coach publishes an approved shared finding or directive into a team's private memory.
    Allowed ONLY for head_coach.
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        target_team = _normalize_team(team)
        if target_team not in VALID_TEAMS:
            return {"ok": False, "error": f"Invalid team '{team}'. Use team_alpha or team_bravo."}

        if actor != "head_coach":
            log = _log_access(
                db,
                actor=actor,
                action="publish_to_team_memory",
                target=f"coach_memories:{target_team}",
                result="denied",
                reason=f"Access denied: only head_coach can publish findings into {target_team} memory (attempted by {actor}).",
                match_id=match_id,
            )
            return {"ok": False, "error": log["reason"], "log": log}

        body_to_publish = directive_text
        resolved_match_id = match_id

        if finding_id is not None:
            finding = (
                db.query(TacticalFindingModel)
                .filter(TacticalFindingModel.id == finding_id)
                .first()
            )
            if not finding:
                return {"ok": False, "error": f"Shared finding #{finding_id} not found."}
            body_to_publish = finding.body
            resolved_match_id = resolved_match_id or finding.match_id

        if not body_to_publish:
            return {"ok": False, "error": "No finding or directive text provided to publish."}

        mem = CoachMemoryModel(
            match_id=resolved_match_id,
            author="head_coach",
            kind="directive",
            body=body_to_publish,
            status="active",
            version=1,
            corrects_id=None,
            visibility="private",
            owner=target_team,
        )
        db.add(mem)
        db.flush()

        log = _log_access(
            db,
            actor=actor,
            action="publish_to_team_memory",
            target=f"coach_memories:{target_team}:#{mem.id}",
            result="allowed",
            reason=f"Head Coach published approved directive into {target_team} private memory (#{mem.id}).",
            match_id=resolved_match_id,
        )
        db.commit()
        db.refresh(mem)
        return {"ok": True, "memory": _serialize_memory(mem), "log": log}
    finally:
        if owns_session:
            db.close()


# ---------------------------------------------------------------------------
# 3. Audit Log Helper
# ---------------------------------------------------------------------------

def list_access_logs(
    match_id: Optional[str] = None,
    limit: int = 100,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    owns_session = db is None
    db = db or SessionLocal()
    try:
        q = db.query(AccessLogModel)
        if match_id:
            q = q.filter(
                (AccessLogModel.match_id == match_id) | (AccessLogModel.match_id.is_(None))
            )
        rows = q.order_by(AccessLogModel.id.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "match_id": r.match_id,
                "actor": r.actor,
                "action": r.action,
                "target": r.target,
                "result": r.result,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        if owns_session:
            db.close()