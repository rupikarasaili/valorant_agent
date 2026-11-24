import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from database.models import SessionLocal, MatchModel, RoundModel, TacticalFindingModel
from agent.state import ValorantState
from agent.tools import (
    analyze_economy_discipline,
    evaluate_entry_trades,
    read_shared_findings,
    write_shared_finding,
    correct_shared_finding,
    publish_finding_to_team_memory,
)

CHECKPOINT_DB_PATH = "checkpoints.sqlite"


def _extract_llm_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _invoke_coach_llm(
    prompt: str, max_retries: int = 2, override_key: Optional[str] = None
) -> Optional[str]:
    """Calls Gemini Flash-Lite / Gemma (or OpenAI) with fast fail on daily 429 quota limits."""
    gemini_key = (
        override_key
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()

    if not gemini_key and not openai_key:
        print("[LLM Info] No Gemini or OpenAI API key provided.", flush=True)
        return None

    if gemini_key:
        for model_name in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it"]:
            for attempt in range(max_retries):
                try:
                    from langchain_google_genai import ChatGoogleGenerativeAI

                    llm = ChatGoogleGenerativeAI(
    model=model_name,
    api_key=gemini_key,
    timeout=30,
)
                    resp = llm.invoke(prompt)
                    text = _extract_llm_text(resp.content)
                    if text:
                        print(f"[LLM] Generated custom coaching text with {model_name}", flush=True)
                        return text
                    break
                except Exception as exc:
                    err_str = str(exc)
                    is_quota_exhausted = (
                        "exceeded your current quota" in err_str.lower()
                        or "per day limit exceeded" in err_str.lower()
                        or "api_key_invalid" in err_str.lower()
                    )
                    is_transient = (
                        not is_quota_exhausted
                        and ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str)
                    )
                    print(
                        f"[LLM Warning] {model_name} (attempt {attempt + 1}/{max_retries}) failed: {exc}",
                        flush=True,
                    )
                    if is_transient and attempt < max_retries - 1:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    break

    if openai_key:
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model="gpt-4o-mini",
                api_key=openai_key,
                temperature=0.65,
                timeout=30,
            )
            resp = llm.invoke(prompt)
            text = _extract_llm_text(resp.content)
            if text:
                print("[LLM] Generated custom coaching text with gpt-4o-mini", flush=True)
                return text
        except Exception as exc:
            print(f"[LLM Warning] gpt-4o-mini failed: {exc}", flush=True)

    return None


def _build_round_cards(
    rounds_data: List[Dict[str, Any]],
    map_name: str,
    agent_name: str,
    coach_callout: str,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Generates all per-round coaching cards in a single batched LLM call."""
    cards: List[Dict[str, Any]] = []
    round_summaries: List[str] = []

    for r in rounds_data:
        r_num = r.get("round_num", len(cards) + 1)
        won = bool(r.get("won"))
        site = r.get("site") or "Mid / Unplanted"
        team_spend = int(r.get("team_spend") or 0)
        enemy_spend = int(r.get("enemy_spend") or 0)
        untraded = int(r.get("untraded_deaths") or 0)
        summary = r.get("what_happened") or (
            f"Round {r_num} ({'Won' if won else 'Lost'} on {site}): "
            f"Team spent {team_spend:,} vs enemy {enemy_spend:,}, {untraded} untraded death(s)."
        )
        round_summaries.append(summary)

        cards.append(
            {
                "round_num": r_num,
                "won": won,
                "site": site,
                "team_spend": team_spend,
                "enemy_spend": enemy_spend,
                "untraded_deaths": untraded,
                "what_happened": summary,
                "you_better": (
                    f"Review Round {r_num} on {site} as {agent_name}—align utility with entry timing and avoid isolated duels without trade support."
                    if not won or untraded > 0
                    else f"Carry the same Round {r_num} utility timing and positioning on {agent_name} into future rounds on {map_name}."
                ),
                "team_better": (
                    f"Check Round {r_num} ({site}) economy and spacing ({untraded} untraded death(s)). {coach_callout}"
                    if not won or untraded > 0
                    else f"Keep coordinated buys and post-round spacing consistent on {map_name}."
                ),
            }
        )

    if not cards:
        return cards

    batch_prompt = (
        f"You are a practical Valorant coach reviewing a completed Ranked match on {map_name} "
        f"where the player played {agent_name}. Do NOT predict future rounds.\n"
        f"Coach focus: {coach_callout}\n\n"
        f"Rounds:\n" + "\n".join(round_summaries) + "\n\n"
        f"Return ONLY a valid JSON array (no markdown fences) with one object per round:\n"
        f'[{{"round_num": 1, "you_better": "1-2 sentences for {agent_name}", "team_better": "1-2 sentences for the team"}}]'
    )
    raw_response = _invoke_coach_llm(batch_prompt, max_retries=1, override_key=api_key)
    if raw_response:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            parsed = json.loads(cleaned.strip())
            if isinstance(parsed, list):
                by_num = {
                    int(item["round_num"]): item
                    for item in parsed
                    if isinstance(item, dict) and "round_num" in item
                }
                for c in cards:
                    item = by_num.get(c["round_num"])
                    if item:
                        if item.get("you_better"):
                            c["you_better"] = str(item["you_better"]).strip()
                        if item.get("team_better"):
                            c["team_better"] = str(item["team_better"]).strip()
        except Exception as exc:
            print(f"[LLM Warning] Could not parse batch round JSON: {exc}", flush=True)

    return cards


def _generate_round_by_round_review(
    round_cards: List[Dict[str, Any]],
    round_timeline: str,
    map_name: str,
    agent_name: str,
    coach_callout: str,
    api_key: Optional[str] = None,
) -> str:
    """Assembles the two-part match summary from the generated round cards without extra LLM calls."""
    you_lines = [f"  • Round {c['round_num']}: {c['you_better']}" for c in round_cards]
    team_lines = [f"  • Round {c['round_num']}: {c['team_better']}" for c in round_cards] + [
        f"  • Coaching Note: {coach_callout}"
    ]
    return (
        f"ROUND-BY-ROUND MATCH REVIEW — {map_name.upper()} ({agent_name})\n\n"
        f"1. ROUND-BY-ROUND: WHAT YOU COULD HAVE DONE BETTER (AS {agent_name.upper()})\n"
        + ("\n".join(you_lines) or "  • No round details available.")
        + "\n\n"
        f"2. ROUND-BY-ROUND: WHAT YOUR TEAM COULD HAVE DONE BETTER\n"
        + ("\n".join(team_lines) or "  • No round details available.")
    )


def db_ingestion_node(state: ValorantState) -> Dict[str, Any]:
    """Saves incoming match telemetry into SQLite and sets initial pipeline_stage."""
    match_id = state["match_id"]
    db = SessionLocal()
    try:
        existing = db.query(MatchModel).filter_by(match_id=match_id).first()
        if not existing:
            new_match = MatchModel(
                match_id=match_id,
                map_name=state.get("map_name", "Unknown"),
                status="Analyzing",
                pipeline_stage="ingested",
                handoff_note=None,
            )
            db.add(new_match)

            for r in state.get("rounds_data", []):
                db.add(
                    RoundModel(
                        match_id=match_id,
                        round_num=r["round_num"],
                        team_spend=r["team_spend"],
                        enemy_spend=r["enemy_spend"],
                        won=r["won"],
                        site=r["site"],
                        untraded_deaths=r["untraded_deaths"],
                        blunder_flagged=r.get("blunder_flagged"),
                    )
                )
            db.commit()
        else:
            existing.status = "Analyzing"
            existing.pipeline_stage = "ingested"
            db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

    return {
        "messages": [HumanMessage(content=f"Match {match_id} loaded for review.")],
    }


def economic_agent_node(state: ValorantState) -> Dict[str, Any]:
    """Step 1 Specialist: Evaluates round economy, writes shared economy findings, and hands off to Spatial."""
    match_id = state["match_id"]
    anomalies: List[str] = []
    flagged_rounds: List[int] = []

    db = SessionLocal()
    try:
        for r in state.get("rounds_data", []):
            eco_result = analyze_economy_discipline.invoke(
                {
                    "team_spend": r["team_spend"],
                    "enemy_spend": r["enemy_spend"],
                    "won": r["won"],
                    "round_num": r["round_num"],
                }
            )
            if "THROW" in eco_result or "Save" in eco_result:
                formatted = f"[Economy Specialist] {eco_result}"
                anomalies.append(formatted)
                flagged_rounds.append(r["round_num"])
                write_shared_finding(
                    actor="economy_analyst",
                    match_id=match_id,
                    kind="economy",
                    body=eco_result,
                    db=db,
                )

        if not anomalies:
            summary_body = "Round buys and saves stayed disciplined across the match."
            anomalies.append(f"[Economy Specialist] {summary_body}")
            write_shared_finding(
                actor="economy_analyst",
                match_id=match_id,
                kind="economy",
                body=summary_body,
                db=db,
            )

        rounds_str = ", ".join(str(n) for n in flagged_rounds) if flagged_rounds else "key buy/save rounds"
        handoff_note = (
            f"Checked rounds [{rounds_str}] for buy discipline; passing to Map Specialist to check site pushes and trades."
        )

        match = db.query(MatchModel).filter_by(match_id=match_id).first()
        if match:
            match.pipeline_stage = "economy_done"
            match.handoff_note = handoff_note
            db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

    return {
        "flagged_anomalies": anomalies,
        "handoff_note": handoff_note,
        "messages": [HumanMessage(content=handoff_note)],
    }


def spatial_agent_node(state: ValorantState) -> Dict[str, Any]:
    """Step 2 Specialist: Reads shared economy findings, writes spatial findings, and corrects if needed."""
    match_id = state["match_id"]
    anomalies: List[str] = list(state.get("flagged_anomalies", []))

    db = SessionLocal()
    try:
        shared_read = read_shared_findings(actor="spatial_analyst", match_id=match_id, db=db)
        economy_findings = [
            f for f in shared_read.get("findings", []) if f.get("kind") == "economy"
        ]

        spatial_issues: List[str] = []
        for r in state.get("rounds_data", []):
            trade_result = evaluate_entry_trades.invoke(
                {
                    "untraded_deaths": r["untraded_deaths"],
                    "site": r["site"],
                    "round_num": r["round_num"],
                }
            )
            if "SPATIAL COLLAPSE" in trade_result:
                spatial_issues.append(trade_result)
                anomalies.append(f"[Map Specialist] {trade_result}")
                write_shared_finding(
                    actor="spatial_analyst",
                    match_id=match_id,
                    kind="spatial",
                    body=trade_result,
                    db=db,
                )

                round_tag = f"Round {r['round_num']}"
                matching_eco = next(
                    (
                        ef
                        for ef in economy_findings
                        if round_tag in ef.get("body", "") and "ECO-THROW" in ef.get("body", "")
                    ),
                    None,
                )
                if matching_eco:
                    correct_shared_finding(
                        actor="spatial_analyst",
                        finding_id=matching_eco["id"],
                        new_body=(
                            f"Round {r['round_num']} on {r['site']}: Lost because {r['untraded_deaths']} players died "
                            f"early without trades on entry, rather than just gun spend."
                        ),
                        new_kind="spatial",
                        db=db,
                    )

        if not spatial_issues:
            clean_body = "Site spacing and trade timing held steady on entry pushes."
            anomalies.append(f"[Map Specialist] {clean_body}")
            write_shared_finding(
                actor="spatial_analyst",
                match_id=match_id,
                kind="spatial",
                body=clean_body,
                db=db,
            )

        next_handoff = (
            f"Found {len(spatial_issues)} site-entry breakdown(s); ready for Head Coach review."
        )
        match = db.query(MatchModel).filter_by(match_id=match_id).first()
        if match:
            match.pipeline_stage = "spatial_done"
            match.handoff_note = next_handoff
            db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

    return {
        "flagged_anomalies": anomalies,
        "handoff_note": next_handoff,
        "messages": [HumanMessage(content=next_handoff)],
    }


def head_coach_node(state: ValorantState) -> Dict[str, Any]:
    """Step 3 Coach: Reads active shared findings, drafts a callout via LLM, and pauses for coach approval."""
    match_id = state["match_id"]
    map_name = state.get("map_name", "Unknown")
    agent_name = state.get("agent_name") or "your agent"
    api_key = state.get("llm_api_key")

    db = SessionLocal()
    try:
        shared_data = read_shared_findings(actor="head_coach", match_id=match_id, db=db)
        active_findings = shared_data.get("findings", [])

        rounds_data = state.get("rounds_data") or []
        lost_summaries = [
            r.get("what_happened")
            for r in rounds_data
            if not r.get("won") and r.get("what_happened")
        ]
        if lost_summaries:
            findings_preview = "\n".join([f"• {line}" for line in lost_summaries[:5]])
        else:
            findings_preview = (
                "\n".join([f"• {f['body']}" for f in active_findings[:4]])
                or "• Standard round pacing."
            )

        ai_callout = _invoke_coach_llm(
            f"In 2 short, natural sentences, write a practical Valorant team callout for {map_name} "
            f"(player is on {agent_name}) based on these match notes:\n{findings_preview}",
            max_retries=1,
            override_key=api_key,
        )
        directive_draft = ai_callout or (
            f"Review {map_name} rounds on {agent_name}, align team buys, and trade opening contact."
        )

        written = write_shared_finding(
            actor="head_coach",
            match_id=match_id,
            kind="directive",
            body=directive_draft,
            db=db,
        )
        directive_id = written["finding"]["id"] if written.get("ok") else None

        match = db.query(MatchModel).filter_by(match_id=match_id).first()
        if match:
            match.pipeline_stage = "awaiting_coach"
            match.status = "Waiting for Coach"
            match.handoff_note = "Suggested game plan ready for your approval."
            db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

    prompt = (
        f"Match Review on {map_name} ({agent_name})\n\n"
        f"Key Round Notes:\n{findings_preview}\n\n"
        f"Suggested Team Callout:\n{directive_draft}"
    )
    coach_decision = interrupt(
        {
            "match_id": match_id,
            "map_name": map_name,
            "directive_id": directive_id,
            "drafted_directive": directive_draft,
            "active_findings_count": len(active_findings),
            "prompt": prompt,
        }
    )

    approved_text = (
        coach_decision
        if isinstance(coach_decision, str) and coach_decision.strip()
        else directive_draft
    )
    if approved_text.strip().lower() == "approved":
        approved_text = directive_draft

    return {
        "coach_feedback": approved_text,
        "drafted_directive": directive_draft,
    }


def synthesis_node(state: ValorantState) -> Dict[str, Any]:
    """Generates a round-by-round coaching review via LLM from actual played rounds."""
    match_id = state["match_id"]
    map_name = state.get("map_name", "Unknown")
    selected_agent = state.get("agent_name") or "Your Selected Agent"
    api_key = state.get("llm_api_key")
    feedback = (
        state.get("coach_feedback")
        or state.get("drafted_directive")
        or "Align utility timing and trade opening contact."
    )

    rounds_data = state.get("rounds_data") or []
    round_cards = _build_round_cards(
        rounds_data, map_name, selected_agent, feedback, api_key=api_key
    )

    round_timeline_lines = [
        r.get("what_happened")
        or (
            f"Round {r['round_num']} ({'WON' if r['won'] else 'LOST'} on {r['site']}): "
            f"Team spent {r['team_spend']:,} vs enemy {r['enemy_spend']:,}, "
            f"{r['untraded_deaths']} untraded death(s)."
        )
        for r in rounds_data
    ]
    round_timeline = "\n".join(round_timeline_lines) or "No round telemetry recorded."

    brief = _generate_round_by_round_review(
        round_cards, round_timeline, map_name, selected_agent, feedback, api_key=api_key
    )

    db = SessionLocal()
    try:
        publish_finding_to_team_memory(
            actor="head_coach",
            team="team_alpha",
            directive_text=feedback,
            match_id=match_id,
            db=db,
        )

        match = db.query(MatchModel).filter_by(match_id=match_id).first()
        if match:
            match.coach_review = feedback
            match.final_brief = brief
            match.status = "Completed"
            match.pipeline_stage = "completed"
            match.handoff_note = "Round-by-round review saved and shared with Team Alpha."
            db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

    return {
        "final_playbook": brief,
        "round_reviews": round_cards,
        "messages": [HumanMessage(content=f"Match {match_id} round-by-round review ready.")],
    }


def _build_sqlite_checkpointer(db_path: str = CHECKPOINT_DB_PATH):
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise ImportError(
            "langgraph-checkpoint-sqlite is required. Install with: uv add langgraph-checkpoint-sqlite"
        ) from exc

    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


workflow = StateGraph(ValorantState)
workflow.add_node("ingest", db_ingestion_node)
workflow.add_node("econ_agent", economic_agent_node)
workflow.add_node("spatial_agent", spatial_agent_node)
workflow.add_node("head_coach", head_coach_node)
workflow.add_node("synthesize", synthesis_node)

workflow.add_edge(START, "ingest")
workflow.add_edge("ingest", "econ_agent")
workflow.add_edge("econ_agent", "spatial_agent")
workflow.add_edge("spatial_agent", "head_coach")
workflow.add_edge("head_coach", "synthesize")
workflow.add_edge("synthesize", END)

checkpointer = _build_sqlite_checkpointer(CHECKPOINT_DB_PATH)
compiled_graph = workflow.compile(checkpointer=checkpointer)