"""
NBA Props Lab v3 - Game Logs Focus
Redesigned to show L5/L7/L10 game logs with actual per-game stats
"""

import os
import json
import time
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NBA Props Lab API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Browser-like headers to avoid blocking
HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
}

cache: Dict[str, Dict] = {}

def get_cache(key: str, ttl: int = 300):
    if key in cache and datetime.now().timestamp() - cache[key]["ts"] < ttl:
        return cache[key]["data"]
    return None

def set_cache(key: str, data: Any):
    cache[key] = {"data": data, "ts": datetime.now().timestamp()}

NBA_TEAMS = {
    1610612737: {"abbr": "ATL", "name": "Hawks", "city": "Atlanta"},
    1610612738: {"abbr": "BOS", "name": "Celtics", "city": "Boston"},
    1610612751: {"abbr": "BKN", "name": "Nets", "city": "Brooklyn"},
    1610612766: {"abbr": "CHA", "name": "Hornets", "city": "Charlotte"},
    1610612741: {"abbr": "CHI", "name": "Bulls", "city": "Chicago"},
    1610612739: {"abbr": "CLE", "name": "Cavaliers", "city": "Cleveland"},
    1610612742: {"abbr": "DAL", "name": "Mavericks", "city": "Dallas"},
    1610612743: {"abbr": "DEN", "name": "Nuggets", "city": "Denver"},
    1610612765: {"abbr": "DET", "name": "Pistons", "city": "Detroit"},
    1610612744: {"abbr": "GSW", "name": "Warriors", "city": "Golden State"},
    1610612745: {"abbr": "HOU", "name": "Rockets", "city": "Houston"},
    1610612754: {"abbr": "IND", "name": "Pacers", "city": "Indiana"},
    1610612746: {"abbr": "LAC", "name": "Clippers", "city": "LA Clippers"},
    1610612747: {"abbr": "LAL", "name": "Lakers", "city": "Los Angeles"},
    1610612763: {"abbr": "MEM", "name": "Grizzlies", "city": "Memphis"},
    1610612748: {"abbr": "MIA", "name": "Heat", "city": "Miami"},
    1610612749: {"abbr": "MIL", "name": "Bucks", "city": "Milwaukee"},
    1610612750: {"abbr": "MIN", "name": "Timberwolves", "city": "Minnesota"},
    1610612740: {"abbr": "NOP", "name": "Pelicans", "city": "New Orleans"},
    1610612752: {"abbr": "NYK", "name": "Knicks", "city": "New York"},
    1610612760: {"abbr": "OKC", "name": "Thunder", "city": "Oklahoma City"},
    1610612753: {"abbr": "ORL", "name": "Magic", "city": "Orlando"},
    1610612755: {"abbr": "PHI", "name": "76ers", "city": "Philadelphia"},
    1610612756: {"abbr": "PHX", "name": "Suns", "city": "Phoenix"},
    1610612757: {"abbr": "POR", "name": "Trail Blazers", "city": "Portland"},
    1610612758: {"abbr": "SAC", "name": "Kings", "city": "Sacramento"},
    1610612759: {"abbr": "SAS", "name": "Spurs", "city": "San Antonio"},
    1610612761: {"abbr": "TOR", "name": "Raptors", "city": "Toronto"},
    1610612762: {"abbr": "UTA", "name": "Jazz", "city": "Utah"},
    1610612764: {"abbr": "WAS", "name": "Wizards", "city": "Washington"},
}

def get_season():
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[2:]}"
    return f"{now.year - 1}-{str(now.year)[2:]}"

async def nba_api_call(url: str, params: dict = None) -> Optional[dict]:
    """Make NBA API call with proper headers"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=HEADERS, params=params)
            if response.status_code == 200:
                return response.json()
            logger.warning(f"NBA API returned {response.status_code}")
    except Exception as e:
        logger.error(f"NBA API error: {e}")
    return None

async def fetch_scoreboard():
    """Fetch today's games"""
    cached = get_cache("scoreboard", 120)
    if cached:
        return cached
    
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                games = data.get("scoreboard", {}).get("games", [])
                result = []
                for g in games:
                    result.append({
                        "gameId": g.get("gameId"),
                        "homeTeamId": g.get("homeTeam", {}).get("teamId"),
                        "awayTeamId": g.get("awayTeam", {}).get("teamId"),
                        "homeScore": g.get("homeTeam", {}).get("score", 0),
                        "awayScore": g.get("awayTeam", {}).get("score", 0),
                        "gameTime": g.get("gameStatusText", "TBD"),
                        "gameStatus": g.get("gameStatus", 1),
                    })
                set_cache("scoreboard", result)
                return result
    except Exception as e:
        logger.error(f"Scoreboard error: {e}")
    return []

async def fetch_league_stats():
    """Get all player season stats in one call"""
    cached = get_cache("league_stats", 600)
    if cached:
        return cached
    
    season = get_season()
    url = "https://stats.nba.com/stats/leaguedashplayerstats"
    params = {
        "Conference": "", "DateFrom": "", "DateTo": "", "Division": "",
        "GameScope": "", "GameSegment": "", "Height": "", "LastNGames": 0,
        "LeagueID": "00", "Location": "", "MeasureType": "Base", "Month": 0,
        "OpponentTeamID": 0, "Outcome": "", "PORound": 0, "PaceAdjust": "N",
        "PerMode": "PerGame", "Period": 0, "PlayerExperience": "",
        "PlayerPosition": "", "PlusMinus": "N", "Rank": "N", "Season": season,
        "SeasonSegment": "", "SeasonType": "Regular Season", "ShotClockRange": "",
        "StarterBench": "", "TeamID": 0, "TwoWay": 0, "VsConference": "", 
        "VsDivision": "", "Weight": "",
    }
    
    data = await nba_api_call(url, params)
    if data:
        result = {}
        headers = data.get("resultSets", [{}])[0].get("headers", [])
        rows = data.get("resultSets", [{}])[0].get("rowSet", [])
        
        for row in rows:
            p = dict(zip(headers, row))
            pid = p.get("PLAYER_ID")
            if pid:
                result[pid] = {
                    "name": p.get("PLAYER_NAME"),
                    "team_id": p.get("TEAM_ID"),
                    "team_abbr": p.get("TEAM_ABBREVIATION"),
                    "gp": p.get("GP", 0),
                    "min": p.get("MIN", 0),
                    "pts": p.get("PTS", 0),
                    "reb": p.get("REB", 0),
                    "ast": p.get("AST", 0),
                    "stl": p.get("STL", 0),
                    "blk": p.get("BLK", 0),
                    "tov": p.get("TOV", 0),
                    "fg3m": p.get("FG3M", 0),
                    "fg3a": p.get("FG3A", 0),
                    "fg3_pct": p.get("FG3_PCT", 0),
                    "fgm": p.get("FGM", 0),
                    "fga": p.get("FGA", 0),
                    "fg_pct": p.get("FG_PCT", 0),
                    "ftm": p.get("FTM", 0),
                    "fta": p.get("FTA", 0),
                    "ft_pct": p.get("FT_PCT", 0),
                    "oreb": p.get("OREB", 0),
                    "dreb": p.get("DREB", 0),
                    "pf": p.get("PF", 0),
                    "plus_minus": p.get("PLUS_MINUS", 0),
                }
        set_cache("league_stats", result)
        return result
    return {}

async def fetch_player_game_log(player_id: int, num_games: int = 15):
    """Fetch detailed game log for a player"""
    cache_key = f"gamelog_{player_id}"
    cached = get_cache(cache_key, 300)
    if cached:
        return cached
    
    season = get_season()
    url = "https://stats.nba.com/stats/playergamelog"
    params = {
        "PlayerID": player_id,
        "Season": season,
        "SeasonType": "Regular Season",
    }
    
    data = await nba_api_call(url, params)
    if data:
        result = []
        headers = data.get("resultSets", [{}])[0].get("headers", [])
        rows = data.get("resultSets", [{}])[0].get("rowSet", [])[:num_games]
        
        for row in rows:
            g = dict(zip(headers, row))
            result.append({
                "date": g.get("GAME_DATE", ""),
                "matchup": g.get("MATCHUP", ""),
                "wl": g.get("WL", ""),
                "min": g.get("MIN", 0),
                "pts": g.get("PTS", 0),
                "reb": g.get("REB", 0),
                "oreb": g.get("OREB", 0),
                "dreb": g.get("DREB", 0),
                "ast": g.get("AST", 0),
                "stl": g.get("STL", 0),
                "blk": g.get("BLK", 0),
                "tov": g.get("TOV", 0),
                "pf": g.get("PF", 0),
                "fg3m": g.get("FG3M", 0),
                "fg3a": g.get("FG3A", 0),
                "fgm": g.get("FGM", 0),
                "fga": g.get("FGA", 0),
                "ftm": g.get("FTM", 0),
                "fta": g.get("FTA", 0),
                "plus_minus": g.get("PLUS_MINUS", 0),
                # Calculated fields
                "pra": g.get("PTS", 0) + g.get("REB", 0) + g.get("AST", 0),
                "pr": g.get("PTS", 0) + g.get("REB", 0),
                "pa": g.get("PTS", 0) + g.get("AST", 0),
                "ra": g.get("REB", 0) + g.get("AST", 0),
                "stl_blk": g.get("STL", 0) + g.get("BLK", 0),
            })
        set_cache(cache_key, result)
        return result
    return []

def calculate_averages(games: List[dict], num: int):
    """Calculate averages for last N games"""
    subset = games[:num] if len(games) >= num else games
    if not subset:
        return None
    
    n = len(subset)
    return {
        "games": n,
        "pts": round(sum(g["pts"] for g in subset) / n, 1),
        "reb": round(sum(g["reb"] for g in subset) / n, 1),
        "ast": round(sum(g["ast"] for g in subset) / n, 1),
        "fg3m": round(sum(g["fg3m"] for g in subset) / n, 1),
        "stl": round(sum(g["stl"] for g in subset) / n, 1),
        "blk": round(sum(g["blk"] for g in subset) / n, 1),
        "min": round(sum(g["min"] for g in subset) / n, 1),
        "pra": round(sum(g["pra"] for g in subset) / n, 1),
        "pr": round(sum(g["pr"] for g in subset) / n, 1),
        "pa": round(sum(g["pa"] for g in subset) / n, 1),
        "ra": round(sum(g["ra"] for g in subset) / n, 1),
        "tov": round(sum(g["tov"] for g in subset) / n, 1),
        "fga": round(sum(g["fga"] for g in subset) / n, 1),
        "fg3a": round(sum(g["fg3a"] for g in subset) / n, 1),
        "fta": round(sum(g["fta"] for g in subset) / n, 1),
    }

def analyze_trends(games: List[dict], stat: str):
    """Analyze trends for a specific stat"""
    if len(games) < 3:
        return {"trend": "neutral", "streak": 0, "note": "Not enough data"}
    
    values = [g[stat] for g in games[:10]]
    l3 = values[:3]
    l10 = values
    
    avg_l3 = sum(l3) / len(l3)
    avg_l10 = sum(l10) / len(l10)
    
    # Check for hot/cold streak
    streak = 0
    direction = None
    threshold = avg_l10 * 0.15  # 15% above/below average
    
    for v in values:
        if direction is None:
            if v > avg_l10 + threshold:
                direction = "over"
                streak = 1
            elif v < avg_l10 - threshold:
                direction = "under"
                streak = 1
        else:
            if direction == "over" and v > avg_l10:
                streak += 1
            elif direction == "under" and v < avg_l10:
                streak += 1
            else:
                break
    
    # Determine trend
    if avg_l3 > avg_l10 * 1.15:
        trend = "hot"
        note = f"L3 avg ({avg_l3:.1f}) is {((avg_l3/avg_l10)-1)*100:.0f}% above L10 ({avg_l10:.1f})"
    elif avg_l3 < avg_l10 * 0.85:
        trend = "cold"
        note = f"L3 avg ({avg_l3:.1f}) is {(1-(avg_l3/avg_l10))*100:.0f}% below L10 ({avg_l10:.1f})"
    else:
        trend = "stable"
        note = f"L3 ({avg_l3:.1f}) consistent with L10 ({avg_l10:.1f})"
    
    # Hit rates for common lines
    hit_rates = {}
    for line in [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 
                 15.5, 20.5, 25.5, 30.5]:
        hits = sum(1 for v in l10 if v > line)
        if 2 <= hits <= 8:  # Only show relevant lines
            hit_rates[line] = {"over": hits, "under": 10 - hits, "pct": hits * 10}
    
    return {
        "trend": trend,
        "streak": streak,
        "streak_direction": direction,
        "note": note,
        "avg_l3": round(avg_l3, 1),
        "avg_l5": round(sum(values[:5]) / min(5, len(values)), 1) if len(values) >= 5 else None,
        "avg_l10": round(avg_l10, 1),
        "high_l10": max(l10),
        "low_l10": min(l10),
        "hit_rates": hit_rates,
    }

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "NBA Props Lab API",
        "version": "3.0.0",
        "season": get_season(),
        "features": ["game_logs", "L5_L7_L10", "hit_rates", "trends"]
    }

@app.get("/api/games")
async def get_games():
    games = await fetch_scoreboard()
    return {"games": games, "teams": NBA_TEAMS}

@app.get("/api/player/{player_id}")
async def get_player_detail(player_id: int):
    """Get detailed player data with full game logs"""
    
    # Get season stats
    all_stats = await fetch_league_stats()
    player_info = all_stats.get(player_id)
    if not player_info:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Get game logs (last 15 games)
    game_log = await fetch_player_game_log(player_id, 15)
    
    # Calculate averages
    averages = {
        "l5": calculate_averages(game_log, 5),
        "l7": calculate_averages(game_log, 7),
        "l10": calculate_averages(game_log, 10),
        "season": {
            "pts": player_info["pts"],
            "reb": player_info["reb"],
            "ast": player_info["ast"],
            "fg3m": player_info["fg3m"],
            "min": player_info["min"],
        }
    }
    
    # Analyze trends for key props
    trends = {
        "pts": analyze_trends(game_log, "pts"),
        "reb": analyze_trends(game_log, "reb"),
        "ast": analyze_trends(game_log, "ast"),
        "fg3m": analyze_trends(game_log, "fg3m"),
        "pra": analyze_trends(game_log, "pra"),
        "stl": analyze_trends(game_log, "stl"),
        "blk": analyze_trends(game_log, "blk"),
    }
    
    return {
        "id": player_id,
        "name": player_info["name"],
        "team_id": player_info["team_id"],
        "team_abbr": player_info["team_abbr"],
        "season_stats": player_info,
        "game_log": game_log,
        "averages": averages,
        "trends": trends,
    }

@app.get("/api/dashboard")
async def get_dashboard():
    """Get dashboard data with game logs for all players in today's games"""
    logger.info("Building dashboard v3...")
    
    games = await fetch_scoreboard()
    if not games:
        return {"games": [], "players": [], "teams": NBA_TEAMS}
    
    # Get team IDs
    team_ids = set()
    for g in games:
        team_ids.add(g["homeTeamId"])
        team_ids.add(g["awayTeamId"])
    
    # Get all player stats
    all_stats = await fetch_league_stats()
    
    # Filter to today's teams, sort by minutes
    players_by_team = {tid: [] for tid in team_ids}
    for pid, p in all_stats.items():
        if p["team_id"] in team_ids and p["min"] >= 15:  # At least 15 min/game
            players_by_team[p["team_id"]].append({"id": pid, **p})
    
    # Get top 8 per team by minutes
    players = []
    for tid in team_ids:
        team_players = sorted(players_by_team[tid], key=lambda x: x["min"], reverse=True)[:8]
        
        for p in team_players:
            await asyncio.sleep(0.4)  # Rate limiting
            game_log = await fetch_player_game_log(p["id"], 10)
            
            # Quick averages
            l5 = calculate_averages(game_log, 5)
            l10 = calculate_averages(game_log, 10)
            
            players.append({
                "id": p["id"],
                "name": p["name"],
                "team_id": p["team_id"],
                "team_abbr": p["team_abbr"],
                "season": {
                    "gp": p["gp"],
                    "min": p["min"],
                    "pts": p["pts"],
                    "reb": p["reb"],
                    "ast": p["ast"],
                    "fg3m": p["fg3m"],
                    "fg3_pct": p["fg3_pct"],
                },
                "l5": l5,
                "l10": l10,
                "game_log": game_log[:10],
                "trends": {
                    "pts": analyze_trends(game_log, "pts") if game_log else None,
                    "reb": analyze_trends(game_log, "reb") if game_log else None,
                    "ast": analyze_trends(game_log, "ast") if game_log else None,
                    "fg3m": analyze_trends(game_log, "fg3m") if game_log else None,
                },
            })
    
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
