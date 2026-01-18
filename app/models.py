from . import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import stripe


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    total_winnings = db.Column(db.Float, default=0)
    color = db.Column(db.String(30), nullable=True)
    skill_rating = db.Column(db.Integer, default=50)
    skill = db.Column(db.Integer, default=50)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sport = db.Column(db.String(50), nullable=True, default="soccer")
    captain_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    matches_played = db.Column(db.Integer, default=0)
    matches_won = db.Column(db.Integer, default=0)
    matches_lost = db.Column(db.Integer, default=0)
    stripe_account_id = db.Column(db.String(255))
    stripe_customer_id = db.Column(db.String(255))
    is_free_agent_pool = db.Column(db.Boolean, default=False)
    players = db.relationship("Player", backref="team", lazy=True, foreign_keys="Player.team_id")
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(80), nullable=True)
    skill_rating = db.Column(db.Integer, default=50)
    invited = db.Column(db.Boolean, default=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    games_played = db.Column(db.Integer, default=0)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    # NEW: admin flag so you can mark a player as an admin
    is_admin = db.Column(db.Boolean, default=False)
    skills = db.relationship("PlayerSkill", backref="player", lazy=True, cascade="all, delete-orphan")

class PlayerStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    sport = db.Column(db.String(80))
    wins = db.Column(db.Integer, default=0, nullable=False)
    losses = db.Column(db.Integer, default=0, nullable=False)
    matches_played = db.Column(db.Integer, default=0, nullable=False)
    skill_rating = db.Column(db.Float, default=50, nullable=False)
    progress_data = db.Column(db.Text)  # JSON of skill rating history
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def win_rate(self):
        return round((self.wins / self.matches_played) * 100, 2) if self.matches_played > 0 else 0



class PlayerSkill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    sport = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    value = db.Column(db.Integer, nullable=False, default=0)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sport = db.Column(db.String(80), nullable=False, default="soccer")
    location = db.Column(db.String(200), nullable=True)
    date = db.Column(db.DateTime, nullable=True)
    team1_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    team2_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    stakes = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    team1 = db.relationship("Team", foreign_keys=[team1_id], lazy=True)
    team2 = db.relationship("Team", foreign_keys=[team2_id], lazy=True)
    winner_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)



class MatchAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    team_side = db.Column(db.String(2), nullable=False)
    match = db.relationship("Match", backref=db.backref("assignments", cascade="all, delete-orphan"))
    player = db.relationship("Player", lazy=True)


class Invite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(120), unique=True, nullable=False)
    context_type = db.Column(db.String(20), nullable=False)
    context_id = db.Column(db.Integer, nullable=False)
    email = db.Column(db.String(200), nullable=True)
    invited_name = db.Column(db.String(120), nullable=True)
    accepted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# -------------------------
# New: AdminSettings & Dispute Models
# -------------------------
class AdminSettings(db.Model):
    """
    Single-row configuration table for admin-managed defaults.
    You can create a single row and update it via the admin UI.
    """
    id = db.Column(db.Integer, primary_key=True)
    default_stake = db.Column(db.Float, default=5.0)      # default stake amount
    payout_multiplier = db.Column(db.Float, default=1.9)  # payout ratio
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Dispute(db.Model):
    """
    Disputes filed by players about match results.
    status: open, resolved, dismissed
    resolution: text or None
    """
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    filed_by_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default="open")
    resolution = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    match = db.relationship("Match", backref=db.backref("disputes", lazy=True))
    filed_by = db.relationship("Player", backref=db.backref("filed_disputes", lazy=True))

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(50))  # 'stake', 'payout', 'commission'
    status = db.Column(db.String(50), default='pending')  # 'pending', 'completed', 'failed'
    stripe_payment_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    match = db.relationship("Match", backref=db.backref("transactions", lazy=True))
    player = db.relationship("Player", backref=db.backref("transactions", lazy=True))


class Bet(db.Model):
    __tablename__ = 'bets'

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)  # ✅ fixed here
    amount = db.Column(db.Float, nullable=False)
    team = db.Column(db.String(100), nullable=False)

    match = db.relationship("Match", backref=db.backref("bets", lazy=True))
    player = db.relationship("Player", backref=db.backref("bets", lazy=True))





class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)