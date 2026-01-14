"""
NBA Props Lab v4 - Uses NBA CDN (not stats.nba.com)
CDN endpoints don't block cloud servers
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NBA Props Lab API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache: Dict[str, Dict] = {}

def get_cache(key: str, ttl: int = 300):
    if key in cache and datetime.now().timestamp() - cache[key]["ts"] < ttl:
        return cache[key]["data"]
    return None

def set_cache(key: str, data: Any):
    cache[key] = {"data": data, "ts": datetime.now().timestamp()}

NBA_TEAMS = {
    1610612737: {"abbr": "ATL", "name": "Hawks"},
    1610612738: {"abbr": "BOS", "name": "Celtics"},
    1610612751: {"abbr": "BKN", "name": "Nets"},
    1610612766: {"abbr": "CHA", "name": "Hornets"},
    1610612741: {"abbr": "CHI", "name": "Bulls"},
    1610612739: {"abbr": "CLE", "name": "Cavaliers"},
    1610612742: {"abbr": "DAL", "name": "Mavericks"},
    1610612743: {"abbr": "DEN", "name": "Nuggets"},
    1610612765: {"abbr": "DET", "name": "Pistons"},
    1610612744: {"abbr": "GSW", "name": "Warriors"},
    1610612745: {"abbr": "HOU", "name": "Rockets"},
    1610612754: {"abbr": "IND", "name": "Pacers"},
    1610612746: {"abbr": "LAC", "name": "Clippers"},
    1610612747: {"abbr": "LAL", "name": "Lakers"},
    1610612763: {"abbr": "MEM", "name": "Grizzlies"},
    1610612748: {"abbr": "MIA", "name": "Heat"},
    1610612749: {"abbr": "MIL", "name": "Bucks"},
    1610612750: {"abbr": "MIN", "name": "Timberwolves"},
    1610612740: {"abbr": "NOP", "name": "Pelicans"},
    1610612752: {"abbr": "NYK", "name": "Knicks"},
    1610612760: {"abbr": "OKC", "name": "Thunder"},
    1610612753: {"abbr": "ORL", "name": "Magic"},
    1610612755: {"abbr": "PHI", "name": "76ers"},
    1610612756: {"abbr": "PHX", "name": "Suns"},
    1610612757: {"abbr": "POR", "name": "Trail Blazers"},
    1610612758: {"abbr": "SAC", "name": "Kings"},
    1610612759: {"abbr": "SAS", "name": "Spurs"},
    1610612761: {"abbr": "TOR", "name": "Raptors"},
    1610612762: {"abbr": "UTA", "name": "Jazz"},
    1610612764: {"abbr": "WAS", "name": "Wizards"},
}

# Reverse lookup: abbr -> team_id
TEAM_ABBR_TO_ID = {v["abbr"]: k for k, v in NBA_TEAMS.items()}

def get_season():
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[2:]}"
    return f"{now.year - 1}-{str(now.year)[2:]}"

def get_season_year():
    """Get the starting year of the season (e.g., 2025 for 2025-26 season)"""
    now = datetime.now()
    if now.month >= 10:
        return now.year
    return now.year - 1

async def fetch_json(url: str, timeout: float = 15.0) -> Optional[dict]:
    """Fetch JSON from URL"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            logger.warning(f"HTTP {response.status_code} for {url}")
    except Exception as e:
        logger.error(f"Fetch error for {url}: {e}")
    return None

async def fetch_scoreboard():
    """Get today's games from CDN"""
    cached = get_cache("scoreboard", 120)
    if cached:
        return cached
    
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    data = await fetch_json(url)
    
    if data:
        games = data.get("scoreboard", {}).get("games", [])
        result = []
        for g in games:
            home_team = g.get("homeTeam", {})
            away_team = g.get("awayTeam", {})
            result.append({
                "gameId": g.get("gameId"),
                "homeTeamId": home_team.get("teamId"),
                "awayTeamId": away_team.get("teamId"),
                "homeTeamAbbr": home_team.get("teamTricode"),
                "awayTeamAbbr": away_team.get("teamTricode"),
                "homeScore": home_team.get("score", 0),
                "awayScore": away_team.get("score", 0),
                "gameTime": g.get("gameStatusText", "TBD"),
                "gameStatus": g.get("gameStatus", 1),
            })
        set_cache("scoreboard", result)
        return result
    return []

async def fetch_team_roster(team_id: int):
    """Get team roster from CDN"""
    cache_key = f"roster_{team_id}"
    cached = get_cache(cache_key, 3600)  # 1 hour cache
    if cached:
        return cached
    
    season_year = get_season_year()
    url = f"https://cdn.nba.com/static/json/staticData/roster/teamId_{team_id}.json"
    
    data = await fetch_json(url)
    if data:
        players = data.get("roster", {}).get("players", [])
        result = []
        for p in players:
            result.append({
                "id": p.get("personId"),
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "jersey": p.get("jersey"),
                "position": p.get("position"),
            })
        set_cache(cache_key, result)
        return result
    
    return []

async def fetch_player_profile(player_id: int):
    """Get player season stats from CDN"""
    cache_key = f"profile_{player_id}"
    cached = get_cache(cache_key, 600)  # 10 min cache
    if cached:
        return cached
    
    url = f"https://cdn.nba.com/static/json/liveData/playerprofile/playerpro_{player_id}.json"
    
    data = await fetch_json(url)
    if data:
        # Get current season stats
        seasons = data.get("playerProfile", {}).get("seasonStats", [])
        current_season = get_season()
        
        season_stats = None
        for s in seasons:
            if s.get("seasonYear") == current_season.split("-")[0]:
                # Get regular season stats
                for st in s.get("regularSeason", []):
                    if st.get("teamId"):
                        season_stats = st
                        break
        
        if not season_stats:
            # Try to get most recent
            if seasons:
                for st in seasons[-1].get("regularSeason", []):
                    if st.get("teamId"):
                        season_stats = st
                        break
        
        if season_stats:
            result = {
                "gp": season_stats.get("gamesPlayed", 0),
                "min": season_stats.get("min", 0),
                "pts": season_stats.get("pts", 0),
                "reb": season_stats.get("reb", 0),
                "ast": season_stats.get("ast", 0),
                "stl": season_stats.get("stl", 0),
                "blk": season_stats.get("blk", 0),
                "tov": season_stats.get("tov", 0),
                "fg3m": season_stats.get("tpm", 0),
                "fg3a": season_stats.get("tpa", 0),
                "fg3_pct": season_stats.get("tppct", 0),
                "fgm": season_stats.get("fgm", 0),
                "fga": season_stats.get("fga", 0),
                "fg_pct": season_stats.get("fgpct", 0),
                "ftm": season_stats.get("ftm", 0),
                "fta": season_stats.get("fta", 0),
            }
            set_cache(cache_key, result)
            return result
    
    return None

async def fetch_player_game_log(player_id: int):
    """Get player's recent games from CDN"""
    cache_key = f"gamelog_{player_id}"
    cached = get_cache(cache_key, 300)  # 5 min cache
    if cached:
        return cached
    
    url = f"https://cdn.nba.com/static/json/liveData/playergamelog/playergamelog_{player_id}.json"
    
    data = await fetch_json(url)
    if data:
        season = get_season()
        games_data = data.get("playerGameLog", {}).get("seasons", [])
        
        # Find current season
        current_games = []
        for s in games_data:
            if season.split("-")[0] in str(s.get("seasonYear", "")):
                for game_type in s.get("gameTypes", []):
                    if game_type.get("gameTypeId") == "Regular Season":
                        current_games = game_type.get("games", [])[:15]
                        break
        
        result = []
        for g in current_games:
            result.append({
                "date": g.get("gameDateUTC", "")[:10],
                "matchup": g.get("matchup", ""),
                "wl": g.get("wl", ""),
                "min": g.get("min", 0),
                "pts": g.get("pts", 0),
                "reb": g.get("reb", 0),
                "oreb": g.get("oreb", 0),
                "dreb": g.get("dreb", 0),
                "ast": g.get("ast", 0),
                "stl": g.get("stl", 0),
                "blk": g.get("blk", 0),
                "tov": g.get("tov", 0),
                "pf": g.get("pf", 0),
                "fg3m": g.get("tpm", 0),
                "fg3a": g.get("tpa", 0),
                "fgm": g.get("fgm", 0),
                "fga": g.get("fga", 0),
                "ftm": g.get("ftm", 0),
                "fta": g.get("fta", 0),
                "plus_minus": g.get("plusMinus", 0),
                # Calculated
                "pra": g.get("pts", 0) + g.get("reb", 0) + g.get("ast", 0),
                "pr": g.get("pts", 0) + g.get("reb", 0),
                "pa": g.get("pts", 0) + g.get("ast", 0),
                "ra": g.get("reb", 0) + g.get("ast", 0),
            })
        
        set_cache(cache_key, result)
        return result
    
    return []

def calc_averages(games: List[dict], n: int):
    """Calculate averages for last N games"""
    subset = games[:n] if len(games) >= n else games
    if not subset:
        return None
    
    count = len(subset)
    return {
        "games": count,
        "pts": round(sum(g["pts"] for g in subset) / count, 1),
        "reb": round(sum(g["reb"] for g in subset) / count, 1),
        "ast": round(sum(g["ast"] for g in subset) / count, 1),
        "fg3m": round(sum(g["fg3m"] for g in subset) / count, 1),
        "stl": round(sum(g["stl"] for g in subset) / count, 1),
        "blk": round(sum(g["blk"] for g in subset) / count, 1),
        "min": round(sum(g["min"] for g in subset) / count, 1),
        "pra": round(sum(g["pra"] for g in subset) / count, 1),
        "pr": round(sum(g["pr"] for g in subset) / count, 1),
        "pa": round(sum(g["pa"] for g in subset) / count, 1),
        "ra": round(sum(g["ra"] for g in subset) / count, 1),
        "tov": round(sum(g["tov"] for g in subset) / count, 1),
    }

def analyze_trend(games: List[dict], stat: str):
    """Analyze trend for a stat"""
    if len(games) < 3:
        return {"trend": "neutral", "note": "Not enough data"}
    
    values = [g[stat] for g in games[:10]]
    l3 = values[:3]
    l10 = values
    
    avg_l3 = sum(l3) / len(l3)
    avg_l10 = sum(l10) / len(l10)
    
    if avg_l10 == 0:
        return {"trend": "neutral", "note": "No data", "avg_l3": 0, "avg_l10": 0}
    
    pct_diff = ((avg_l3 - avg_l10) / avg_l10) * 100
    
    if pct_diff > 15:
        trend = "hot"
        note = f"L3 ({avg_l3:.1f}) up {pct_diff:.0f}% vs L10 ({avg_l10:.1f})"
    elif pct_diff < -15:
        trend = "cold"
        note = f"L3 ({avg_l3:.1f}) down {abs(pct_diff):.0f}% vs L10 ({avg_l10:.1f})"
    else:
        trend = "stable"
        note = f"Consistent: L3 {avg_l3:.1f}, L10 {avg_l10:.1f}"
    
    return {
        "trend": trend,
        "note": note,
        "avg_l3": round(avg_l3, 1),
        "avg_l5": round(sum(values[:5]) / min(5, len(values)), 1) if len(values) >= 5 else avg_l3,
        "avg_l10": round(avg_l10, 1),
        "high_l10": max(l10),
        "low_l10": min(l10),
    }

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "NBA Props Lab API",
        "version": "4.0.0",
        "season": get_season(),
        "note": "Using CDN endpoints"
    }

@app.get("/api/games")
async def get_games():
    games = await fetch_scoreboard()
    return {"games": games, "teams": NBA_TEAMS}

@app.get("/api/player/{player_id}")
async def get_player(player_id: int):
    """Get full player details"""
    profile = await fetch_player_profile(player_id)
    game_log = await fetch_player_game_log(player_id)
    
    if not profile and not game_log:
        raise HTTPException(status_code=404, detail="Player not found")
    
    return {
        "id": player_id,
        "season": profile,
        "game_log": game_log,
        "l5": calc_averages(game_log, 5),
        "l7": calc_averages(game_log, 7),
        "l10": calc_averages(game_log, 10),
        "trends": {
            "pts": analyze_trend(game_log, "pts"),
            "reb": analyze_trend(game_log, "reb"),
            "ast": analyze_trend(game_log, "ast"),
            "fg3m": analyze_trend(game_log, "fg3m"),
        } if game_log else {}
    }

@app.get("/api/dashboard")
async def get_dashboard():
    """Get full dashboard with all players from today's games"""
    logger.info("Building dashboard v4 (CDN)...")
    
    # Get today's games
    games = await fetch_scoreboard()
    if not games:
        logger.info("No games today")
        return {"games": [], "players": [], "teams": NBA_TEAMS}
    
    logger.info(f"Found {len(games)} games")
    
    # Get team IDs
    team_ids = set()
    for g in games:
        team_ids.add(g["homeTeamId"])
        team_ids.add(g["awayTeamId"])
    
    # Get rosters for all teams
    all_players = []
    for team_id in team_ids:
        await asyncio.sleep(0.2)  # Small delay
        roster = await fetch_team_roster(team_id)
        logger.info(f"Team {team_id}: {len(roster)} players")
        
        for p in roster[:10]:  # Top 10 per team
            all_players.append({
                "id": p["id"],
                "name": p["name"],
                "team_id": team_id,
                "team_abbr": NBA_TEAMS.get(team_id, {}).get("abbr", ""),
                "position": p.get("position", ""),
            })
    
    logger.info(f"Total players to fetch: {len(all_players)}")
    
    # Get stats and game logs for each player
    players = []
    for p in all_players:
        await asyncio.sleep(0.3)  # Rate limiting
        
        try:
            profile = await fetch_player_profile(p["id"])
            game_log = await fetch_player_game_log(p["id"])
            
            # Skip players with no data or low minutes
            if not profile or profile.get("min", 0) < 10:
                continue
            
            l5 = calc_averages(game_log, 5)
            l10 = calc_averages(game_log, 10)
            
            trends = {}
            if game_log and len(game_log) >= 3:
                trends = {
                    "pts": analyze_trend(game_log, "pts"),
                    "reb": analyze_trend(game_log, "reb"),
                    "ast": analyze_trend(game_log, "ast"),
                    "fg3m": analyze_trend(game_log, "fg3m"),
                }
            
            players.append({
                "id": p["id"],
                "name": p["name"],
                "team_id": p["team_id"],
                "team_abbr": p["team_abbr"],
                "position": p.get("position", ""),
                "season": profile,
                "l5": l5,
                "l10": l10,
                "game_log": game_log[:10] if game_log else [],
                "trends": trends,
            })
            
            logger.info(f"✓ {p['name']}: {len(game_log)} games")
            
        except Exception as e:
            logger.error(f"Error fetching {p['name']}: {e}")
            continue
    
    logger.info(f"Dashboard built: {len(games)} games, {len(players)} players")
    
    return {
        "games": games,
        "players": players,
        "teams": NBA_TEAMS,
        "updated": datetime.now().isoformat(),
    }

@app.post("/api/refresh")
async def refresh():
    global cache
    cache = {}
    return {"status": "cache_cleared"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
