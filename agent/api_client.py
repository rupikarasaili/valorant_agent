import requests
from typing import Dict, Any, List, Optional

BASE_URL = "https://api.henrikdev.xyz/valorant/v3/matches"


def fetch_player_matches(
    region: str, name: str, tag: str, api_key: str, size: int = 5
) -> List[Dict[str, Any]]:
    """Fetches recent matches for a given player using the HenrikDev API."""
    url = f"{BASE_URL}/{region}/{name}/{tag}"
    params = {"size": size}
    headers = {"Authorization": api_key.strip()}

    response = requests.get(url, headers=headers, params=params, timeout=20)
    if response.status_code != 200:
        raise Exception(f"HenrikDev API Error [{response.status_code}]: {response.text}")

    data = response.json()
    return data.get("data", [])


def parse_henrik_match(
    match_data: Dict[str, Any],
    player_name: Optional[str] = None,
    player_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Parses live HenrikDev match JSON into real round-by-round telemetry."""
    metadata = match_data.get("metadata", {})
    match_id = metadata.get("matchid", "unknown_match")
    map_name = metadata.get("map", "Unknown")

    all_players = (match_data.get("players") or {}).get("all_players") or []
    target_name = (player_name or "").strip().lower()
    target_tag = (player_tag or "").strip().lower()

    user_team = "Blue"
    user_puuid = None
    for p in all_players:
        p_name = (p.get("name") or "").strip().lower()
        p_tag = (p.get("tag") or "").strip().lower()
        if target_name and p_name == target_name and (not target_tag or p_tag == target_tag):
            user_team = p.get("team") or "Blue"
            user_puuid = p.get("puuid")
            break
    else:
        if all_players:
            user_team = all_players[0].get("team") or "Blue"
            user_puuid = all_players[0].get("puuid")

    rounds_data: List[Dict[str, Any]] = []
    rounds = match_data.get("rounds") or []

    for idx, r in enumerate(rounds):
        round_num = idx + 1
        winning_team = r.get("winning_team") or ""
        won = winning_team.strip().lower() == user_team.strip().lower()
        end_type = r.get("end_type") or "Eliminated"

        plant_events = r.get("plant_events") or {}
        site = plant_events.get("plant_site") or r.get("plant_site") or "No Plant / Mid"

        team_spend = 0
        enemy_spend = 0
        user_kills = 0
        user_spent = 0
        user_died = False

        for ps in r.get("player_stats") or []:
            p_team = (ps.get("player_team") or "").strip().lower()
            econ = ps.get("economy") or {}
            spent = int(econ.get("spent") or 0)
            if p_team == user_team.strip().lower():
                team_spend += spent
            else:
                enemy_spend += spent

            if user_puuid and ps.get("player_puuid") == user_puuid:
                user_kills = len(ps.get("kill_events") or [])
                user_spent = spent

        # Sort kill events chronologically to count untraded deaths and track player survival
        kill_events = sorted(
            r.get("kill_events") or [],
            key=lambda k: int(k.get("kill_time_in_round") or 0),
        )
        untraded_deaths = 0
        for k_idx, ke in enumerate(kill_events):
            victim_team = (ke.get("victim_team") or "").strip().lower()
            victim_puuid = ke.get("victim_puuid")
            killer_puuid = ke.get("killer_puuid")
            kill_time = int(ke.get("kill_time_in_round") or 0)

            if user_puuid and victim_puuid == user_puuid:
                user_died = True

            if victim_team == user_team.strip().lower():
                traded = any(
                    other.get("victim_puuid") == killer_puuid
                    and 0 <= (int(other.get("kill_time_in_round") or 0) - kill_time) <= 5000
                    for other in kill_events[k_idx + 1 :]
                )
                if not traded:
                    untraded_deaths += 1

        outcome = "WON" if won else "LOST"
        what_happened = (
            f"Round {round_num} ({outcome} — {end_type}, Site: {site}): "
            f"Team spent {team_spend:,} credits vs enemy {enemy_spend:,}. "
            f"You spent {user_spent:,}, got {user_kills} kill(s), "
            f"{'and died' if user_died else 'and survived'}; "
            f"team suffered {untraded_deaths} untraded death(s)."
        )

        rounds_data.append(
            {
                "round_num": round_num,
                "team_spend": team_spend,
                "enemy_spend": enemy_spend,
                "won": won,
                "site": site,
                "untraded_deaths": untraded_deaths,
                "blunder_flagged": None if won else what_happened,
                "what_happened": what_happened,
            }
        )

    return {
        "match_id": match_id,
        "map_name": map_name,
        "rounds_data": rounds_data,
        "flagged_anomalies": [],
        "coach_feedback": None,
        "final_playbook": "",
    }