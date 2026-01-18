import random
from itertools import combinations
from math import inf
import string
import secrets
import stripe


def make_token(n=10):
    return secrets.token_urlsafe(n)[:n]

def shuffle_players_list(players):
    p = list(players)
    random.shuffle(p)
    half = len(p) // 2
    return p[:half], p[half:]

def greedy_balance(players):
    sorted_p = sorted(players, key=lambda x: x.skill_rating, reverse=True)
    team_a, team_b = [], []
    sum_a, sum_b = 0, 0
    for p in sorted_p:
        if sum_a <= sum_b:
            team_a.append(p); sum_a += p.skill_rating
        else:
            team_b.append(p); sum_b += p.skill_rating
    return team_a, team_b

def optimal_balance(players):
    n = len(players)
    half = n // 2
    best, best_diff = None, inf
    for combo in combinations(players, half):
        team_a = list(combo)
        team_b = [p for p in players if p not in team_a]
        diff = abs(sum(p.skill_rating for p in team_a) - sum(p.skill_rating for p in team_b))
        if diff < best_diff:
            best_diff = diff
            best = (team_a, team_b)
            if best_diff == 0:
                break
    return best

def balance_teams(players):
    n = len(players)
    if n < 2:
        return players, []
    if n <= 10:
        res = optimal_balance(players)
        if res:
            return res
    return greedy_balance(players)
