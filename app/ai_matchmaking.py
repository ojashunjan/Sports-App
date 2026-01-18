# ai_matchmaking.py
import random
from app.models import Team  # adjust import path as needed
import stripe


def recommend_opponents(team):
    """Suggest teams close in skill rating to the given team."""
    if not team:
        return []
    all_teams = Team.query.filter(Team.id != team.id).all()
    # compute average or existing skill rating on teams
    candidates = [t for t in all_teams if abs((t.skill_rating or 1000) - (team.skill_rating or 1000)) < 300]
    if not candidates:
        return random.sample(all_teams, min(len(all_teams), 3))
    return random.sample(candidates, min(len(candidates), 3))

def recommend_venues(team):
    """Suggest venues — prioritise same city if team has a ‘city’ attribute."""
    venues = Venue.query.all()
    if hasattr(team, "city") and team.city:
        same_city = [v for v in venues if getattr(v, "city", None) == team.city]
        if len(same_city) >= 3:
            return random.sample(same_city, 3)
    # fallback
    return random.sample(venues, min(len(venues), 3))
