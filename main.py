"""
NBA Props Lab - Backend API
FastAPI server that fetches real-time NBA data from stats.nba.com
"""

import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import lru_cache
import logging

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# NBA API imports
from nba_api.stats.endpoints import (
    ScoreboardV2,
    BoxScoreTraditionalV2,
    BoxScoreAdvancedV2,
    PlayerDashboardByGeneralSplits,
    PlayerGameLog,
    LeagueHustleStatsPlayer,
    LeagueDashPtStats,
    CommonTeamRoster,
    CommonPlayerInfo,
)
from nba_api.live.nba.endpoints import ScoreBoard as LiveScoreBoard
from nba_api.stats.static import teams, players

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NBA Props Lab API",
    description="Real-time NBA player props analytics and betting insights",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# DATA MODELS
# ============================================================================

class PlayerProps(BaseModel):
    line: float
    over: int
    under: int

class PlayerTracking(BaseModel):
    touches: float
    passes: float
    potential_ast: float
    ast: float
    reb_chances: float
    reb: float
    contested_shots: float
    speed: float

class PlayerStats(BaseModel):
    pts: float
    reb: float
    ast: float
    fg_pct: float
    fg3_pct: float
    min: float
    stl: float = 0
    blk: float = 0

class PlayerSplits(BaseModel):
    home: Dict[str, float]
    away: Dict[str, float]
    vsConf: Dict[str, float]

class GameInfo(BaseModel):
    game: str
    pts: int
    reb: int
    ast: int

class Player(BaseModel):
    id: int
    name: str
    team: int
    position: str
    stats: PlayerStats
    tracking: PlayerTracking
    props: Dict[str, PlayerProps]
    last5: List[GameInfo]
    splits: PlayerSplits

class Game(BaseModel):
    gameId: str
    homeTeamId: int
    awayTeamId: int
    gameTime: str
    gameStatus: int
    spread: Dict[str, float]
    total: float
    moneyline: Dict[str, int]

class DashboardData(BaseModel):
    games: List[Game]
    players: List[Player]
    lastUpdated: str

# ============================================================================
# NBA TEAM DATA
# ============================================================================

NBA_TEAMS = {
    1610612737: {"name": "Hawks", "city": "Atlanta", "abbr": "ATL", "color": "#E03A3E"},
    1610612738: {"name": "Celtics", "city": "Boston", "abbr": "BOS", "color": "#007A33"},
    1610612751: {"name": "Nets", "city": "Brooklyn", "abbr": "BKN", "color": "#000000"},
    1610612766: {"name": "Hornets", "city": "Charlotte", "abbr": "CHA", "color": "#1D1160"},
    1610612741: {"name": "Bulls", "city": "Chicago", "abbr": "CHI", "color": "#CE1141"},
    1610612739: {"name": "Cavaliers", "city": "Cleveland", "abbr": "CLE", "color": "#860038"},
    1610612742: {"name": "Mavericks", "city": "Dallas", "abbr": "DAL", "color": "#00538C"},
    1610612743: {"name": "Nuggets", "city": "Denver", "abbr": "DEN", "color": "#0E2240"},
    1610612765: {"name": "Pistons", "city": "Detroit", "abbr": "DET", "color": "#C8102E"},
    1610612744: {"name": "Warriors", "city": "Golden State", "abbr": "GSW", "color": "#1D428A"},
    1610612745: {"name": "Rockets", "city": "Houston", "abbr": "HOU", "color": "#CE1141"},
    1610612754: {"name": "Pacers", "city": "Indiana", "abbr": "IND", "color": "#002D62"},
    1610612746: {"name": "Clippers", "city": "LA", "abbr": "LAC", "color": "#C8102E"},
    1610612747: {"name": "Lakers", "city": "Los Angeles", "abbr": "LAL", "color": "#552583"},
    1610612763: {"name": "Grizzlies", "city": "Memphis", "abbr": "MEM", "color": "#5D76A9"},
    1610612748: {"name": "Heat", "city": "Miami", "abbr": "MIA", "color": "#98002E"},
    1610612749: {"name": "Bucks", "city": "Milwaukee", "abbr": "MIL", "color": "#00471B"},
    1610612750: {"name": "Timberwolves", "city": "Minnesota", "abbr": "MIN", "color": "#0C2340"},
    1610612740: {"name": "Pelicans", "city": "New Orleans", "abbr": "NOP", "color": "#0C2340"},
    1610612752: {"name": "Knicks", "city": "New York", "abbr": "NYK", "color": "#006BB6"},
    1610612760: {"name": "Thunder", "city": "Oklahoma City", "abbr": "OKC", "color": "#007AC1"},
    1610612753: {"name": "Magic", "city": "Orlando", "abbr": "ORL", "color": "#0077C0"},
    1610612755: {"name": "Sixers", "city": "Philadelphia", "abbr": "PHI", "color": "#006BB6"},
    1610612756: {"name": "Suns", "city": "Phoenix", "abbr": "PHX", "color": "#1D1160"},
    1610612757: {"name": "Trail Blazers", "city": "Portland", "abbr": "POR", "color": "#E03A3E"},
    1610612758: {"name": "Kings", "city": "Sacramento", "abbr": "SAC", "color": "#5A2D81"},
    1610612759: {"name": "Spurs", "city": "San Antonio", "abbr": "SAS", "color": "#C4CED4"},
    1610612761: {"name": "Raptors", "city": "Toronto", "abbr": "TOR", "color": "#CE1141"},
    1610612762: {"name": "Jazz", "city": "Utah", "abbr": "UTA", "color": "#002B5C"},
    1610612764: {"name": "Wizards", "city": "Washington", "abbr": "WAS", "color": "#002B5C"},
}

# ============================================================================
# CACHING LAYER
# ============================================================================

class DataCache:
    """Simple in-memory cache with TTL"""
    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}
    
    def get(self, key: str, ttl_seconds: int = 300) -> Optional[Any]:
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now().timestamp() - entry["timestamp"] < ttl_seconds:
                return entry["data"]
        return None
    
    def set(self, key: str, data: Any):
        self.cache[key] = {
            "data": data,
            "timestamp": datetime.now().timestamp()
        }
    
    def clear(self):
        self.cache = {}

cache = DataCache()

# ============================================================================
# NBA API HELPERS
# ============================================================================

def safe_api_call(func, *args, **kwargs):
    """Wrapper for NBA API calls with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            time.sleep(0.6)  # Rate limiting
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"API call failed (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # Exponential backoff
    return None

def get_current_season() -> str:
    """Get current NBA season string (e.g., '2025-26')"""
    now = datetime.now()
    year = now.year
    month = now.month
    
    # NBA season starts in October
    if month >= 10:
        return f"{year}-{str(year + 1)[2:]}"
    else:
        return f"{year - 1}-{str(year)[2:]}"

# ============================================================================
# DATA FETCHING FUNCTIONS
# ============================================================================

def fetch_todays_games() -> List[Dict]:
    """Fetch today's NBA games from the scoreboard"""
    cache_key = "todays_games"
    cached = cache.get(cache_key, ttl_seconds=120)  # 2 min cache
    if cached:
        return cached
    
    try:
        # Try live scoreboard first
        scoreboard = safe_api_call(LiveScoreBoard)
        if scoreboard and scoreboard.games:
            games_data = scoreboard.games.get_dict()
            games = []
            for game in games_data:
                games.append({
                    "gameId": game.get("gameId", ""),
                    "homeTeamId": game.get("homeTeam", {}).get("teamId", 0),
                    "awayTeamId": game.get("awayTeam", {}).get("teamId", 0),
                    "gameTime": game.get("gameStatusText", "TBD"),
                    "gameStatus": game.get("gameStatus", 1),
                    "homeScore": game.get("homeTeam", {}).get("score", 0),
                    "awayScore": game.get("awayTeam", {}).get("score", 0),
                })
            cache.set(cache_key, games)
            return games
    except Exception as e:
        logger.error(f"Error fetching live scoreboard: {e}")
    
    # Fallback to stats scoreboard
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        scoreboard = safe_api_call(ScoreboardV2, game_date=today)
        if scoreboard:
            games_header = scoreboard.game_header.get_data_frame()
            games = []
            for _, row in games_header.iterrows():
                games.append({
                    "gameId": row.get("GAME_ID", ""),
                    "homeTeamId": row.get("HOME_TEAM_ID", 0),
                    "awayTeamId": row.get("VISITOR_TEAM_ID", 0),
                    "gameTime": row.get("GAME_STATUS_TEXT", "TBD"),
                    "gameStatus": row.get("GAME_STATUS_ID", 1),
                })
            cache.set(cache_key, games)
            return games
    except Exception as e:
        logger.error(f"Error fetching scoreboard: {e}")
    
    return []

def fetch_team_roster(team_id: int) -> List[Dict]:
    """Fetch roster for a specific team"""
    cache_key = f"roster_{team_id}"
    cached = cache.get(cache_key, ttl_seconds=3600)  # 1 hour cache
    if cached:
        return cached
    
    try:
        season = get_current_season()
        roster = safe_api_call(CommonTeamRoster, team_id=team_id, season=season)
        if roster:
            df = roster.common_team_roster.get_data_frame()
            players_list = []
            for _, row in df.iterrows():
                players_list.append({
                    "id": row.get("PLAYER_ID"),
                    "name": row.get("PLAYER"),
                    "position": row.get("POSITION", ""),
                    "height": row.get("HEIGHT", ""),
                    "weight": row.get("WEIGHT", ""),
                    "experience": row.get("EXP", ""),
                })
            cache.set(cache_key, players_list)
            return players_list
    except Exception as e:
        logger.error(f"Error fetching roster for team {team_id}: {e}")
    
    return []

def fetch_player_stats(player_id: int, team_id: int) -> Dict:
    """Fetch comprehensive player stats"""
    cache_key = f"player_stats_{player_id}"
    cached = cache.get(cache_key, ttl_seconds=600)  # 10 min cache
    if cached:
        return cached
    
    season = get_current_season()
    stats = {
        "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0,
        "fg_pct": 0, "fg3_pct": 0, "ft_pct": 0, "min": 0
    }
    
    try:
        dashboard = safe_api_call(
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season
        )
        if dashboard:
            overall = dashboard.overall_player_dashboard.get_data_frame()
            if not overall.empty:
                row = overall.iloc[0]
                stats = {
                    "pts": float(row.get("PTS", 0) or 0),
                    "reb": float(row.get("REB", 0) or 0),
                    "ast": float(row.get("AST", 0) or 0),
                    "stl": float(row.get("STL", 0) or 0),
                    "blk": float(row.get("BLK", 0) or 0),
                    "fg_pct": float(row.get("FG_PCT", 0) or 0),
                    "fg3_pct": float(row.get("FG3_PCT", 0) or 0),
                    "ft_pct": float(row.get("FT_PCT", 0) or 0),
                    "min": float(row.get("MIN", 0) or 0),
                }
        cache.set(cache_key, stats)
    except Exception as e:
        logger.error(f"Error fetching stats for player {player_id}: {e}")
    
    return stats

def fetch_player_last5(player_id: int) -> List[Dict]:
    """Fetch last 5 games for a player"""
    cache_key = f"player_last5_{player_id}"
    cached = cache.get(cache_key, ttl_seconds=600)
    if cached:
        return cached
    
    season = get_current_season()
    last5 = []
    
    try:
        game_log = safe_api_call(
            PlayerGameLog,
            player_id=player_id,
            season=season
        )
        if game_log:
            df = game_log.player_game_log.get_data_frame()
            for i, row in df.head(5).iterrows():
                last5.append({
                    "game": row.get("MATCHUP", ""),
                    "pts": int(row.get("PTS", 0) or 0),
                    "reb": int(row.get("REB", 0) or 0),
                    "ast": int(row.get("AST", 0) or 0),
                })
        cache.set(cache_key, last5)
    except Exception as e:
        logger.error(f"Error fetching last 5 for player {player_id}: {e}")
    
    return last5

def fetch_player_splits(player_id: int) -> Dict:
    """Fetch home/away splits for a player"""
    cache_key = f"player_splits_{player_id}"
    cached = cache.get(cache_key, ttl_seconds=1800)  # 30 min cache
    if cached:
        return cached
    
    season = get_current_season()
    splits = {
        "home": {"pts": 0, "reb": 0},
        "away": {"pts": 0, "reb": 0},
        "vsConf": {"pts": 0, "reb": 0}
    }
    
    try:
        dashboard = safe_api_call(
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season
        )
        if dashboard:
            location_df = dashboard.location_player_dashboard.get_data_frame()
            for _, row in location_df.iterrows():
                loc = row.get("GROUP_VALUE", "")
                if loc == "Home":
                    splits["home"] = {
                        "pts": float(row.get("PTS", 0) or 0),
                        "reb": float(row.get("REB", 0) or 0)
                    }
                elif loc == "Road":
                    splits["away"] = {
                        "pts": float(row.get("PTS", 0) or 0),
                        "reb": float(row.get("REB", 0) or 0)
                    }
            
            # Get conference splits if available
            try:
                conf_df = dashboard.vs_conference_player_dashboard.get_data_frame()
                if not conf_df.empty:
                    row = conf_df.iloc[0]
                    splits["vsConf"] = {
                        "pts": float(row.get("PTS", 0) or 0),
                        "reb": float(row.get("REB", 0) or 0)
                    }
            except:
                pass
                
        cache.set(cache_key, splits)
    except Exception as e:
        logger.error(f"Error fetching splits for player {player_id}: {e}")
    
    return splits

def fetch_tracking_stats() -> Dict[int, Dict]:
    """Fetch league-wide tracking stats for passing/rebounding"""
    cache_key = "tracking_stats"
    cached = cache.get(cache_key, ttl_seconds=1800)
    if cached:
        return cached
    
    season = get_current_season()
    tracking_data = {}
    
    try:
        # Fetch passing tracking data
        passing = safe_api_call(
            LeagueDashPtStats,
            season=season,
            pt_measure_type="Passing",
            player_or_team="Player",
            per_mode_simple="PerGame"
        )
        if passing:
            df = passing.get_data_frames()[0]
            for _, row in df.iterrows():
                player_id = row.get("PLAYER_ID")
                if player_id:
                    tracking_data[player_id] = {
                        "passes": float(row.get("PASSES_MADE", 0) or 0),
                        "potential_ast": float(row.get("POTENTIAL_AST", 0) or 0),
                        "ast": float(row.get("AST", 0) or 0),
                        "ast_pts_created": float(row.get("AST_PTS_CREATED", 0) or 0),
                    }
        
        time.sleep(0.6)
        
        # Fetch rebounding tracking data
        rebounding = safe_api_call(
            LeagueDashPtStats,
            season=season,
            pt_measure_type="Rebounding",
            player_or_team="Player",
            per_mode_simple="PerGame"
        )
        if rebounding:
            df = rebounding.get_data_frames()[0]
            for _, row in df.iterrows():
                player_id = row.get("PLAYER_ID")
                if player_id:
                    if player_id not in tracking_data:
                        tracking_data[player_id] = {}
                    tracking_data[player_id].update({
                        "reb_chances": float(row.get("REB_CHANCES", 0) or 0),
                        "reb": float(row.get("REB", 0) or 0),
                        "contested_reb": float(row.get("REB_CONTEST", 0) or 0),
                        "uncontested_reb": float(row.get("REB_UNCONTEST", 0) or 0),
                    })
        
        time.sleep(0.6)
        
        # Fetch speed/distance tracking
        speed = safe_api_call(
            LeagueDashPtStats,
            season=season,
            pt_measure_type="SpeedDistance",
            player_or_team="Player",
            per_mode_simple="PerGame"
        )
        if speed:
            df = speed.get_data_frames()[0]
            for _, row in df.iterrows():
                player_id = row.get("PLAYER_ID")
                if player_id:
                    if player_id not in tracking_data:
                        tracking_data[player_id] = {}
                    tracking_data[player_id].update({
                        "speed": float(row.get("AVG_SPEED", 0) or 0),
                        "distance": float(row.get("DIST_MILES", 0) or 0),
                    })
        
        time.sleep(0.6)
        
        # Fetch touches/possessions
        possessions = safe_api_call(
            LeagueDashPtStats,
            season=season,
            pt_measure_type="Possessions",
            player_or_team="Player",
            per_mode_simple="PerGame"
        )
        if possessions:
            df = possessions.get_data_frames()[0]
            for _, row in df.iterrows():
                player_id = row.get("PLAYER_ID")
                if player_id:
                    if player_id not in tracking_data:
                        tracking_data[player_id] = {}
                    tracking_data[player_id].update({
                        "touches": float(row.get("TOUCHES", 0) or 0),
                        "time_of_poss": float(row.get("TIME_OF_POSS", 0) or 0),
                    })
        
        cache.set(cache_key, tracking_data)
    except Exception as e:
        logger.error(f"Error fetching tracking stats: {e}")
    
    return tracking_data

def fetch_hustle_stats() -> Dict[int, Dict]:
    """Fetch hustle stats (contested shots, deflections, etc.)"""
    cache_key = "hustle_stats"
    cached = cache.get(cache_key, ttl_seconds=1800)
    if cached:
        return cached
    
    season = get_current_season()
    hustle_data = {}
    
    try:
        hustle = safe_api_call(
            LeagueHustleStatsPlayer,
            season=season,
            per_mode_time="PerGame"
        )
        if hustle:
            df = hustle.get_data_frames()[0]
            for _, row in df.iterrows():
                player_id = row.get("PLAYER_ID")
                if player_id:
                    hustle_data[player_id] = {
                        "contested_shots": float(row.get("CONTESTED_SHOTS", 0) or 0),
                        "deflections": float(row.get("DEFLECTIONS", 0) or 0),
                        "loose_balls": float(row.get("LOOSE_BALLS_RECOVERED", 0) or 0),
                        "screen_assists": float(row.get("SCREEN_ASSISTS", 0) or 0),
                        "charges_drawn": float(row.get("CHARGES_DRAWN", 0) or 0),
                    }
        cache.set(cache_key, hustle_data)
    except Exception as e:
        logger.error(f"Error fetching hustle stats: {e}")
    
    return hustle_data

def generate_props_lines(stats: Dict) -> Dict[str, Dict]:
    """Generate realistic prop lines based on season averages"""
    def round_to_half(x):
        return round(x * 2) / 2
    
    def generate_odds(avg, line):
        """Generate realistic odds based on line vs average"""
        diff = avg - line
        if diff > 0.5:
            return {"over": -130, "under": 110}
        elif diff < -0.5:
            return {"over": 110, "under": -130}
        else:
            return {"over": -110, "under": -110}
    
    pts_line = round_to_half(stats.get("pts", 15))
    reb_line = round_to_half(stats.get("reb", 5))
    ast_line = round_to_half(stats.get("ast", 3))
    
    # 3-pointers based on FG3% and minutes
    fg3_pct = stats.get("fg3_pct", 0.33)
    min_played = stats.get("min", 25)
    estimated_3pa = min_played * 0.2  # Rough estimate
    estimated_3pm = estimated_3pa * fg3_pct
    threes_line = max(0.5, round_to_half(estimated_3pm))
    
    return {
        "pts": {"line": pts_line, **generate_odds(stats.get("pts", 15), pts_line)},
        "reb": {"line": reb_line, **generate_odds(stats.get("reb", 5), reb_line)},
        "ast": {"line": ast_line, **generate_odds(stats.get("ast", 3), ast_line)},
        "threes": {"line": threes_line, **generate_odds(estimated_3pm, threes_line)},
    }

# ============================================================================
# MAIN DATA AGGREGATION
# ============================================================================

def build_dashboard_data() -> Dict:
    """Build complete dashboard data from NBA API"""
    logger.info("Building dashboard data...")
    
    # Fetch today's games
    games_raw = fetch_todays_games()
    
    if not games_raw:
        logger.warning("No games found for today")
        return {"games": [], "players": [], "lastUpdated": datetime.now().isoformat()}
    
    # Fetch tracking stats (league-wide, do this first)
    logger.info("Fetching tracking stats...")
    tracking_stats = fetch_tracking_stats()
    hustle_stats = fetch_hustle_stats()
    
    games = []
    all_players = []
    team_ids = set()
    
    for game in games_raw:
        home_id = game.get("homeTeamId")
        away_id = game.get("awayTeamId")
        
        if not home_id or not away_id:
            continue
        
        team_ids.add(home_id)
        team_ids.add(away_id)
        
        # Generate game odds (in production, fetch from odds API)
        home_team = NBA_TEAMS.get(home_id, {})
        away_team = NBA_TEAMS.get(away_id, {})
        
        games.append({
            "gameId": game.get("gameId", ""),
            "homeTeamId": home_id,
            "awayTeamId": away_id,
            "gameTime": game.get("gameTime", "TBD"),
            "gameStatus": game.get("gameStatus", 1),
            "spread": {"home": -5.5, "away": 5.5},  # Placeholder
            "total": 220.5,  # Placeholder
            "moneyline": {"home": -200, "away": 170},  # Placeholder
        })
    
    # Fetch rosters and player data for each team
    for team_id in team_ids:
        logger.info(f"Fetching roster for team {team_id}...")
        roster = fetch_team_roster(team_id)
        
        # Get top players (by experience/position)
        top_players = roster[:8]  # Top 8 players per team
        
        for player in top_players:
            player_id = player.get("id")
            if not player_id:
                continue
            
            logger.info(f"Fetching data for {player.get('name')}...")
            
            # Fetch individual stats
            stats = fetch_player_stats(player_id, team_id)
            last5 = fetch_player_last5(player_id)
            splits = fetch_player_splits(player_id)
            
            # Get tracking data for this player
            player_tracking = tracking_stats.get(player_id, {})
            player_hustle = hustle_stats.get(player_id, {})
            
            # Build tracking object with defaults
            tracking = {
                "touches": player_tracking.get("touches", stats.get("min", 25) * 2),
                "passes": player_tracking.get("passes", stats.get("ast", 3) * 8),
                "potential_ast": player_tracking.get("potential_ast", stats.get("ast", 3) * 2.2),
                "ast": stats.get("ast", 0),
                "reb_chances": player_tracking.get("reb_chances", stats.get("reb", 5) * 1.4),
                "reb": stats.get("reb", 0),
                "contested_shots": player_hustle.get("contested_shots", 3),
                "speed": player_tracking.get("speed", 4.0),
            }
            
            # Generate prop lines
            props = generate_props_lines(stats)
            
            all_players.append({
                "id": player_id,
                "name": player.get("name", "Unknown"),
                "team": team_id,
                "position": player.get("position", ""),
                "stats": stats,
                "tracking": tracking,
                "props": props,
                "last5": last5 if last5 else [{"game": "N/A", "pts": 0, "reb": 0, "ast": 0}] * 5,
                "splits": splits,
            })
    
    return {
        "games": games,
        "players": all_players,
        "lastUpdated": datetime.now().isoformat()
    }

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "NBA Props Lab API",
        "version": "1.0.0",
        "season": get_current_season()
    }

@app.get("/api/dashboard")
async def get_dashboard():
    """Get complete dashboard data"""
    cache_key = "dashboard_data"
    cached = cache.get(cache_key, ttl_seconds=300)  # 5 min cache
    
    if cached:
        return JSONResponse(content=cached)
    
    try:
        data = build_dashboard_data()
        cache.set(cache_key, data)
        return JSONResponse(content=data)
    except Exception as e:
        logger.error(f"Error building dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/games")
async def get_games():
    """Get today's games"""
    try:
        games = fetch_todays_games()
        return JSONResponse(content={"games": games})
    except Exception as e:
        logger.error(f"Error fetching games: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/player/{player_id}")
async def get_player(player_id: int):
    """Get detailed player data"""
    try:
        # Find player info
        player_info = players.find_player_by_id(player_id)
        if not player_info:
            raise HTTPException(status_code=404, detail="Player not found")
        
        # Get team ID from player info
        team_id = 0  # Would need to look up
        
        stats = fetch_player_stats(player_id, team_id)
        last5 = fetch_player_last5(player_id)
        splits = fetch_player_splits(player_id)
        
        return JSONResponse(content={
            "id": player_id,
            "name": player_info.get("full_name", "Unknown"),
            "stats": stats,
            "last5": last5,
            "splits": splits,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching player {player_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tracking")
async def get_tracking():
    """Get league-wide tracking stats"""
    try:
        tracking = fetch_tracking_stats()
        hustle = fetch_hustle_stats()
        return JSONResponse(content={
            "tracking": tracking,
            "hustle": hustle
        })
    except Exception as e:
        logger.error(f"Error fetching tracking: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/refresh")
async def refresh_data(background_tasks: BackgroundTasks):
    """Force refresh all cached data"""
    cache.clear()
    background_tasks.add_task(build_dashboard_data)
    return {"status": "refresh_started"}

@app.get("/api/teams")
async def get_teams():
    """Get all NBA teams"""
    return JSONResponse(content={"teams": NBA_TEAMS})

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )
