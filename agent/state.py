import operator
from typing import TypedDict, List, Dict, Any, Annotated, Optional
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ValorantState(TypedDict):
    match_id: str
    map_name: str
    agent_name: Optional[str]
    llm_api_key: Optional[str]
    rounds_data: List[Dict[str, Any]]
    round_reviews: Optional[List[Dict[str, Any]]]
    flagged_anomalies: Annotated[List[str], operator.add]
    messages: Annotated[List[AnyMessage], add_messages]
    handoff_note: Optional[str]
    drafted_directive: Optional[str]
    coach_feedback: Optional[str]
    final_playbook: Optional[str]