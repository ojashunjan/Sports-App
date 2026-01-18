from flask import current_app as app, render_template, request, redirect, url_for, flash, jsonify, abort
from . import db
from .models import Team, Player, Match, MatchAssignment, Invite, PlayerSkill, Dispute, AdminSettings
from .utils import shuffle_players_list, balance_teams, make_token
from datetime import datetime
from flask import session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from .models import Admin
import json
import random
from .models import Team, Player, Match, PlayerStats
from flask import request, redirect, url_for, flash
from app import db
from app.models import Match, Team, PlayerStats, Transaction, Bet
from flask import render_template, abort
from app.models import Player, Team  # adjust imports
from app.ai_recommendations import generate_ai_recommendations, update_skill_rating
from app.ai_matchmaking import recommend_opponents, recommend_venues
from flask import current_app
import stripe



stripe.api_key = app.config["STRIPE_SECRET_KEY"]


# -------------------------
# Helper: sport -> skill fields
# -------------------------
def skill_fields_for_sport(sport):
    mapping = {
        "soccer": ["Shooting", "Passing", "Defending", "Speed", "Stamina"],
        "basketball": ["Shooting", "Dribbling", "Defense", "Passing", "Rebounding"],
        "volleyball": ["Serving", "Spiking", "Blocking", "Setting", "Passing"],
        "hockey": ["Shooting", "Skating", "Defense", "Checking", "Passing"],
        "football": ["Throwing", "Catching", "Tackling", "Speed", "Awareness"],
        "cricket": ["Bowling", "Batting", "Fielding", "Speed", "Fitness"],
        "default": ["Skill A", "Skill B", "Skill C", "Skill D", "Skill E"]
    }
    if not sport:
        return mapping["default"]
    return mapping.get(sport.lower(), mapping["default"])

# -------------------------
# Helper: recalculate team skill rating
# -------------------------
def recalc_team_skill(team):
    """
    Recalculate team's average skill rating as:
    average of all PlayerSkill.value across all players in the team.
    If no PlayerSkill rows, fallback to average of player.skill_rating values
    or the default 1200.
    """
    # collect all players on team
    players = Player.query.filter_by(team_id=team.id).all()
    total = 0
    count = 0
    for p in players:
        # player skills
        for s in p.skills:
            # s.value is the model field
            total += s.value
            count += 1

    if count > 0:
        avg = total / count
        team.skill_rating = int(round(avg))
        db.session.add(team)
        db.session.commit()
        return team.skill_rating

    # fallback: average player.skill_rating if present
    if players:
        sum_ratings = sum((p.skill_rating or 50) for p in players)
        team.skill_rating = int(round(sum_ratings / len(players)))
        db.session.add(team)
        db.session.commit()
        return team.skill_rating

    # no players: leave default
    team.skill_rating = team.skill_rating or 50
    db.session.add(team)
    db.session.commit()
    return team.skill_rating

@app.route("/create_checkout_session/<int:match_id>", methods=["POST"])
def create_checkout_session(match_id):
    match = Match.query.get_or_404(match_id)
    amount = float(request.form.get("amount", 0))
    player_id = current_user.id

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Stake for Match #{match.id}"},
                "unit_amount": int(amount * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=url_for("payment_success", match_id=match.id, _external=True),
        cancel_url=url_for("payment_cancel", match_id=match.id, _external=True),
    )

    tx = Transaction(match_id=match.id, player_id=player_id, amount=amount,
                     type='stake', status='pending', stripe_payment_id=session.id)
    db.session.add(tx)
    db.session.commit()

    return redirect(session.url, code=303)

@app.route("/mark_result/<int:match_id>", methods=["POST"])
def mark_result(match_id):
    match = Match.query.get_or_404(match_id)
    winner_id = int(request.form.get("winner_id"))
    payout_mode = request.form.get("payout_mode")

    # Identify winner and loser teams
    team1 = match.team1
    team2 = match.team2
    winner = Team.query.get(winner_id) if winner_id != 0 else None

    # Set match result
    match.status = "completed"
    match.winner_id = winner_id
    db.session.commit()

    # 🪙 Calculate winnings
    if winner:
        stake = match.stakes or 0

        # Add winnings to winner
        winner.total_winnings = (winner.total_winnings or 0) + stake

        # Optional: loser stays same
        loser = team1 if winner.id == team2.id else team2

        # Commit winnings update
        db.session.commit()

    flash(f"Match #{match_id} marked as completed. Winnings updated.", "success")
    return redirect(url_for("admin_dashboard"))




@app.route('/match/<int:match_id>/place_stake', methods=['POST'])
def place_stake(match_id):
    match = Match.query.get_or_404(match_id)
    amount = float(request.form.get('amount', 0))

    if amount <= 0:
        flash("Please enter a valid stake amount.", "danger")
        return redirect(url_for('match_detail', match_id=match_id))

    # Add the new amount to the match’s total stakes
    match.stakes += amount
    db.session.commit()

    flash(f"Successfully added ${amount:.2f} to the total stake.", "success")
    return redirect(url_for('match_detail', match_id=match_id))


# Home
@app.route("/")
def index():
    teams = Team.query.order_by(Team.name).all()
    matches = Match.query.order_by(Match.created_at.desc()).all()
    open_matches = [m for m in matches if (not m.team1_id) or (not m.team2_id)]
    return render_template("index.html", teams=teams, matches=matches, open_matches=open_matches)

# -------------------------
# Team creation & detail
# -------------------------
@app.route("/teams/create", methods=["GET", "POST"])
def create_team():
    if request.method == "POST":
        name = request.form.get("name")
        color = request.form.get("color")
        skill = int(request.form.get("skill") or 50)
        captain_name = request.form.get("captain_name") or None

        # sport from form (new). For backward compatibility, if not provided fallback to 'soccer'
        sport = request.form.get("sport") or "soccer"

        team = Team(name=name, color=color, skill_rating=skill, sport=sport)
        db.session.add(team)
        db.session.commit()

        if captain_name:
            captain = Player(name=captain_name, role="Captain", skill_rating=skill, team_id=team.id)
            db.session.add(captain)
            db.session.commit()
            team.captain_id = captain.id
            db.session.commit()

        flash("Team created", "success")
        return redirect(url_for("index"))
    return render_template("register.html")

@app.route("/teams/<int:team_id>")
def team_detail(team_id):
    team = Team.query.get_or_404(team_id)

    skill_names = skill_fields_for_sport(team.sport)
    players = team.players

    # Allow viewing Free Agent Pool always — no redirect
    if team.name == "Free Agent Pool":
        return render_template(
            "team_detail.html",
            team=team,
            players=players,
            skill_names=skill_names
        )

    # Normal access restriction for logged-in teams
    if "team_id" not in session or session["team_id"] != team_id:
        flash("Not allowed.", "danger")
        return redirect(url_for("index"))
    
    return render_template(
        "team_detail.html", 
        team=team, 
        players=players, 
        skill_names=skill_names
    )


# manual add player to team
@app.route("/teams/<int:team_id>/add_player", methods=["POST"])
def team_add_player(team_id):
    team = Team.query.get_or_404(team_id)
    name = request.form.get("name")
    email = request.form.get("email") or None
    role = request.form.get("role") or None
    # legacy single skill field (skill) still supported: treat as skill_rating fallback
    skill = int(request.form.get("skill") or 50)
    if not name:
        flash("Player name required", "danger")
        return redirect(url_for("team_detail", team_id=team_id))

    # create player
    p = Player(name=name, email=email, role=role, skill_rating=skill, team_id=team.id, invited=False)
    db.session.add(p)
    db.session.commit()

    # extract skill_* fields from form and store as PlayerSkill rows
    # expected form inputs: skill_Shooting, skill_Passing, etc.
    skill_names = skill_fields_for_sport(team.sport)
    any_skill_saved = False
    canonical_keys = {f"skill_{sn.replace(' ','_')}" for sn in skill_names}
    for sname in skill_names:
        key = f"skill_{sname.replace(' ','_')}"
        val = request.form.get(key)
        if val is None or val == "":
            continue
        try:
            v = int(val)
        except Exception:
            # ignore invalid entries
            continue
        ps = PlayerSkill(player_id=p.id, sport=(team.sport.lower() if team.sport else "unknown"), name=sname, value=v)
        db.session.add(ps)
        any_skill_saved = True

    # Also support arbitrary skill_ fields not in the canonical set
    for key in request.form:
        if key.startswith("skill_") and key not in canonical_keys:
            v_raw = request.form.get(key)
            if v_raw is None or v_raw == "":
                continue
            try:
                v = int(v_raw)
            except Exception:
                continue
            # name from key after skill_
            name_from_key = key[len("skill_"):].replace("_", " ")
            ps = PlayerSkill(player_id=p.id, sport=(team.sport.lower() if team.sport else "unknown"), name=name_from_key, value=v)
            db.session.add(ps)
            any_skill_saved = True

    db.session.commit()

    # Recalculate team skill rating now that player added
    recalc_team_skill(team)

    flash("Player added", "success")
    return redirect(url_for("team_detail", team_id=team_id))

# route to edit player and their skills
@app.route("/players/<int:player_id>/edit", methods=["GET", "POST"])
def edit_player(player_id):
    player = Player.query.get_or_404(player_id)
    team = player.team
    sport = team.sport if team else None
    skill_names = skill_fields_for_sport(sport)
    if request.method == "POST":
        player.name = request.form.get("name") or player.name
        player.email = request.form.get("email") or player.email
        player.role = request.form.get("role") or player.role
        # optional: update legacy skill_rating if provided
        try:
            player.skill_rating = int(request.form.get("skill_rating") or player.skill_rating)
        except Exception:
            pass
        db.session.add(player)
        db.session.commit()

        # delete old PlayerSkill rows for this player and save new ones
        PlayerSkill.query.filter_by(player_id=player.id).delete()
        db.session.commit()

        canonical_keys = {f"skill_{sn.replace(' ','_')}" for sn in skill_names}
        for sname in skill_names:
            key = f"skill_{sname.replace(' ','_')}"
            val = request.form.get(key)
            if val is None or val == "":
                continue
            try:
                v = int(val)
            except Exception:
                continue
            ps = PlayerSkill(player_id=player.id, sport=(sport.lower() if sport else "unknown"), name=sname, value=v)
            db.session.add(ps)

        # also save arbitrary skill_ fields
        for key in request.form:
            if key.startswith("skill_") and key not in canonical_keys:
                v_raw = request.form.get(key)
                if v_raw is None or v_raw == "":
                    continue
                try:
                    v = int(v_raw)
                except Exception:
                    continue
                name_from_key = key[len("skill_"):].replace("_", " ")
                ps = PlayerSkill(player_id=player.id, sport=(sport.lower() if sport else "unknown"), name=name_from_key, value=v)
                db.session.add(ps)

        db.session.commit()

        # recalc team rating
        if team:
            recalc_team_skill(team)

        flash("Player updated", "success")
        if team:
            return redirect(url_for("team_detail", team_id=team.id))
        return redirect(url_for("index"))

    # GET: render edit form
    # Prepare a dict of existing skill values for this player
    existing_skills = {s.name: s.value for s in player.skills}
    return render_template("edit_player.html", player=player, team=team, skill_names=skill_names, existing_skills=existing_skills)


@app.route("/player/<int:player_id>/delete", methods=["POST", "GET"])
def delete_player(player_id):
    player = Player.query.get_or_404(player_id)
    team = player.team

    # Delete the player's skills first
    PlayerSkill.query.filter_by(player_id=player.id).delete()

    db.session.delete(player)
    db.session.commit()

    # Recalculate team's average after deletion using recalc_team_skill
    if team:
        try:
            recalc_team_skill(team)
        except Exception:
            # if something odd happens, ensure team.skill_rating isn't left None
            team.skill_rating = team.skill_rating or 50
            db.session.add(team)
            db.session.commit()

    flash(f"{player.name} has been deleted{(' from ' + team.name) if team else ''}.", "warning")
    if team:
        return redirect(url_for("team_detail", team_id=team.id))
    return redirect(url_for("index"))

# invite player to a team (creates Invite row and shows a token / page)
@app.route("/teams/<int:team_id>/invite", methods=["GET","POST"])
def team_invite(team_id):
    team = Team.query.get_or_404(team_id)
    if request.method == "POST":
        invited_name = request.form.get("name") or None
        email = request.form.get("email") or None
        token = make_token(12)
        inv = Invite(token=token, context_type="team", context_id=team.id, email=email, invited_name=invited_name)
        db.session.add(inv); db.session.commit()
        # In production you'd email the token link; for MVP we just display a page with the link
        accept_url = url_for("accept_invite", token=token, _external=True)
        return render_template("invite_sent.html", invite=inv, accept_url=accept_url, team=team)
    return render_template("invite_sent.html", team=team, invite=None)

# -------------------------
# Matches: create, detail, join
# -------------------------
@app.route("/matches/create", methods=["GET","POST"])
def create_match():
    teams = Team.query.order_by(Team.name).all()
    if request.method == "POST":
        sport = request.form.get("sport") or "soccer"
        location = request.form.get("location")
        date_raw = request.form.get("date") or None
        team1_id = request.form.get("team1_id") or None
        team2_id = request.form.get("team2_id") or None
        stakes = float(request.form.get("stakes") or 0.0)

        m = Match(sport=sport, location=location, stakes=stakes)

        # If teams were selected, convert to ints
        if team1_id:
            team1_id = int(team1_id)
        if team2_id:
            team2_id = int(team2_id)

        # Validate team sport compatibility if both teams provided
        if team1_id and team2_id:
            team1 = Team.query.get(team1_id)
            team2 = Team.query.get(team2_id)
            # If either team has no sport set (legacy), treat missing sport as equal to m.sport or to other team
            t1_sport = team1.sport or sport
            t2_sport = team2.sport or sport
            if t1_sport != t2_sport:
                flash(f"Cannot create match: teams must have the same sport. {team1.name} plays {t1_sport}, while {team2.name} plays {t2_sport}.", "danger")
                return redirect(url_for("create_match"))
            # ensure match sport aligns with teams
            m.sport = t1_sport

        if team1_id:
            m.team1_id = int(team1_id)
        if team2_id:
            m.team2_id = int(team2_id)
        if date_raw:
            try:
                m.date = datetime.fromisoformat(date_raw)
            except Exception:
                m.date = None
        db.session.add(m); db.session.commit()
        flash("Match created", "success")
        return redirect(url_for("index"))
    return render_template("create_match.html", teams=teams)

@app.route("/matches/<int:match_id>")
def match_detail(match_id):
    match = Match.query.get_or_404(match_id)
    # pool: players from team1 and team2 (if present), plus any standalone players
    pool = []
    if match.team1_id:
        pool += Player.query.filter_by(team_id=match.team1_id).all()
    if match.team2_id:
        pool += Player.query.filter_by(team_id=match.team2_id).all()
    # assigned players:
    assignments = MatchAssignment.query.filter_by(match_id=match.id).all()
    assigned_a = [a.player for a in assignments if a.team_side == 'A']
    assigned_b = [a.player for a in assignments if a.team_side == 'B']
    locked = (match.status == "locked")
    return render_template("match_detail.html", match=match, pool=pool, assigned_a=assigned_a, assigned_b=assigned_b, locked=locked)

# invite team to match (creates Invite linking to match)
@app.route("/matches/<int:match_id>/invite_team", methods=["POST"])
def invite_team_to_match(match_id):
    match = Match.query.get_or_404(match_id)
    team_id = request.form.get("team_id")
    token = make_token(12)
    inv = Invite(token=token, context_type="match", context_id=match.id, email=None, invited_name=None)
    db.session.add(inv); db.session.commit()
    accept_url = url_for("accept_invite", token=token, _external=True)
    flash(f"Invite created. Share this link to accept: {accept_url}", "info")
    return redirect(url_for("match_detail", match_id=match.id))

# accept invite via token (either join team or accept match invite)
@app.route("/invite/<token>", methods=["GET","POST"])
def accept_invite(token):
    inv = Invite.query.filter_by(token=token).first_or_404()
    if request.method == "POST":
        # user provides a name (and optional email) to accept
        name = request.form.get("name")
        email = request.form.get("email") or None
        if inv.context_type == "team":
            # add player into the team
            p = Player(name=name or inv.invited_name or "Guest", email=email, invited=False, team_id=inv.context_id)
            db.session.add(p); db.session.commit()
            inv.accepted = True; db.session.commit()
            flash("You joined the team!", "success")
            # recalc team rating (no skills from invite accepted player until they edit)
            try:
                team = Team.query.get(inv.context_id)
                recalc_team_skill(team)
            except Exception:
                pass
            return redirect(url_for("team_detail", team_id=inv.context_id))
        else:
            # match invite - join as a player assigned to match pool (we create a player w/o team)
            p = Player(name=name or "Guest", email=email, invited=False, team_id=None)
            db.session.add(p); db.session.commit()
            # create assignment on the match (unassigned side: 'A' or 'B' chosen later)
            # For simplicity, add assignment with team_side = 'A' by default (captain can reassign)
            ma = MatchAssignment(match_id=inv.context_id, player_id=p.id, team_side='A')
            db.session.add(ma)
            inv.accepted = True; db.session.commit()
            flash("You joined the match pool!", "success")
            return redirect(url_for("match_detail", match_id=inv.context_id))
    # GET: render accept form
    return render_template("invite_accept.html", invite=inv)

# open challenge join (team fills a blank slot)
@app.route("/matches/<int:match_id>/join/<int:team_id>", methods=["POST"])
def join_open_match(match_id, team_id):
    match = Match.query.get_or_404(match_id)
    if match.status == "locked":
        flash("Match is locked", "danger"); return redirect(url_for("match_detail", match_id=match_id))
    if not match.team1_id:
        match.team1_id = team_id
    elif not match.team2_id:
        match.team2_id = team_id
    else:
        flash("Both slots filled", "danger")
        return redirect(url_for("match_detail", match_id=match_id))
    db.session.commit()
    flash("Team joined the match", "success")
    return redirect(url_for("match_detail", match_id=match_id))

# -------------------------
# Balancing & shuffle endpoints (AJAX-friendly JSON)
# -------------------------
@app.route("/matches/<int:match_id>/auto_balance", methods=["POST"])
def match_auto_balance(match_id):
    match = Match.query.get_or_404(match_id)
    if match.status == "locked":
        return jsonify({"error": "match locked"}), 400
    pool = []
    if match.team1_id:
        pool += Player.query.filter_by(team_id=match.team1_id).all()
    if match.team2_id:
        pool += Player.query.filter_by(team_id=match.team2_id).all()
    if not pool:
        pool = Player.query.all()
    team_a, team_b = balance_teams(pool)
    # remove old assignments for match
    MatchAssignment.query.filter_by(match_id=match.id).delete()
    db.session.commit()
    for p in team_a:
        db.session.add(MatchAssignment(match_id=match.id, player_id=p.id, team_side='A'))
    for p in team_b:
        db.session.add(MatchAssignment(match_id=match.id, player_id=p.id, team_side='B'))
    db.session.commit()
    return jsonify({"team_a":[p.name for p in team_a],"team_b":[p.name for p in team_b]})

@app.route("/matches/<int:match_id>/shuffle", methods=["POST"])
def match_shuffle(match_id):
    match = Match.query.get_or_404(match_id)
    if match.status == "locked": return jsonify({"error":"match locked"}), 400
    pool = []
    if match.team1_id:
        pool += Player.query.filter_by(team_id=match.team1_id).all()
    if match.team2_id:
        pool += Player.query.filter_by(team_id=match.team2_id).all()
    if not pool:
        pool = Player.query.all()
    a, b = shuffle_players_list(pool)
    MatchAssignment.query.filter_by(match_id=match.id).delete()
    db.session.commit()
    for p in a:
        db.session.add(MatchAssignment(match_id=match.id, player_id=p.id, team_side='A'))
    for p in b:
        db.session.add(MatchAssignment(match_id=match.id, player_id=p.id, team_side='B'))
    db.session.commit()
    return jsonify({"team_a":[p.name for p in a],"team_b":[p.name for p in b]})

@app.route("/matches/<int:match_id>/toggle_lock", methods=["POST"])
def match_toggle_lock(match_id):
    match = Match.query.get_or_404(match_id)
    # require at least one assignment to lock
    if match.status == "locked":
        match.status = "pending"
    else:
        if not MatchAssignment.query.filter_by(match_id=match.id).count():
            return jsonify({"error":"no assignments to lock"}), 400
        match.status = "locked"
    db.session.commit()
    return jsonify({"status":match.status})

# manual assignment (AJAX POST) - assign/remove players to side
@app.route("/matches/<int:match_id>/assign", methods=["POST"])
def match_assign_player(match_id):
    match = Match.query.get_or_404(match_id)
    if match.status == "locked":
        return jsonify({"error":"match locked"}), 400
    player_id = int(request.form.get("player_id"))
    side = request.form.get("team_side")  # 'A' or 'B', or 'remove'
    if request.form.get("remove") == "1" or side == "remove":
        MatchAssignment.query.filter_by(match_id=match.id, player_id=player_id).delete()
        db.session.commit()
        return jsonify({"ok":True})
    # remove existing then add
    MatchAssignment.query.filter_by(match_id=match.id, player_id=player_id).delete()
    db.session.commit()
    ma = MatchAssignment(match_id=match.id, player_id=player_id, team_side=side)
    db.session.add(ma); db.session.commit()
    return jsonify({"ok":True})

# -------------------------
# NEW: Admin dashboard, disputes, payouts, and dispute resolution
# -------------------------

def get_admin_settings():
    """Get the singleton AdminSettings row; create default if not found."""
    s = AdminSettings.query.first()
    if not s:
        s = AdminSettings(default_stake=5.0, payout_multiplier=1.9)
        db.session.add(s)
        db.session.commit()
    return s

def admin_required_check(player_id=None):
    """
    Lightweight helper to determine admin status.
    In a real app you'd use proper auth. Here we accept:
    - query param 'admin=true' or
    - player_id (for convenience) and player.is_admin True.
    This is a convenience fallback so you can test quickly.
    """
    # First check request args for admin flag (for local testing)
    if request.args.get("admin") == "true":
        return True
    # If player_id provided, check DB
    if player_id:
        p = Player.query.get(player_id)
        if p and getattr(p, "is_admin", False):
            return True
    return False

@app.route("/admin/dashboard")
def admin_dashboard():
    # ✅ Allow local testing with ?admin=true
    if request.args.get("admin") == "true":
        session["admin"] = True

    # ✅ Check session state
    if not session.get("admin"):
        return "Admin access required. For quick local testing add ?admin=true", 403

    # ✅ Proceed to render dashboard
    settings = get_admin_settings()
    matches = Match.query.order_by(Match.created_at.desc()).all()
    disputes = Dispute.query.order_by(Dispute.created_at.desc()).all()
    players = Player.query.order_by(Player.name).all()
    return render_template(
        "admin_dashboard.html",
        settings=settings,
        matches=matches,
        disputes=disputes,
        players=players,
    )


@app.route("/admin/settings", methods=["POST"])
def admin_update_settings():
    if not admin_required_check():
        return jsonify({"error":"admin required"}), 403
    settings = get_admin_settings()
    try:
        settings.default_stake = float(request.form.get("default_stake") or settings.default_stake)
        settings.payout_multiplier = float(request.form.get("payout_multiplier") or settings.payout_multiplier)
        db.session.add(settings)
        db.session.commit()
        flash("Admin settings updated", "success")
    except Exception as e:
        db.session.rollback()
        flash("Failed to update settings: " + str(e), "danger")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/matches/<int:match_id>/add_stakes", methods=["POST"])
def admin_add_stakes(match_id):
    if not admin_required_check():
        return jsonify({"error":"admin required"}), 403
    match = Match.query.get_or_404(match_id)
    amount = float(request.form.get("amount") or 0.0)
    match.stakes = (match.stakes or 0.0) + amount
    db.session.add(match)
    db.session.commit()
    flash(f"Added {amount} stakes to match #{match.id}.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/matches/<int:match_id>/approve_result", methods=["POST"])
def admin_approve_result(match_id):
    """
    Admin approves a match result. For MVP we expect a form field
    'winning_side' = 'A' or 'B'. When approved, we set match.status='completed'
    and (optionally) compute mock payouts according to AdminSettings.
    """
    if not admin_required_check():
        return jsonify({"error":"admin required"}), 403

    match = Match.query.get_or_404(match_id)
    winning_side = request.form.get("winning_side")
    note = request.form.get("note") or ""
    settings = get_admin_settings()

    if winning_side not in ("A", "B"):
        flash("Invalid winning side", "danger")
        return redirect(url_for("admin_dashboard"))

    # Simple payout example: total_stake * multiplier -> distributed to winning team's players evenly.
    total_stake = match.stakes or 0.0
    payout_pool = total_stake * settings.payout_multiplier

    # who is on side A/B? use MatchAssignment for this match
    assignments = MatchAssignment.query.filter_by(match_id=match.id).all()
    winners = [a.player for a in assignments if a.team_side == winning_side]
    losers = [a.player for a in assignments if a.team_side != winning_side]

    # mark match as completed and save admin note in status (or extended storage)
    match.status = "completed"
    db.session.add(match)
    db.session.commit()

    # Distribute payouts (this is placeholder behavior)
    per_winner = (payout_pool / len(winners)) if winners else 0.0

    # --- NEW: Update total winnings for the winning team ---
    if winning_side == "A":
        winning_team = match.team1
    else:
        winning_team = match.team2

    if winning_team:
        winning_team.total_winnings = (winning_team.total_winnings or 0) + payout_pool
        db.session.commit()

    # In real app you'd record transactions. For MVP, add flash messages:
    flash(f"Match #{match.id} approved. Winning side: {winning_side}. Each winner receives ~{per_winner:.2f}. Note: {note}", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/matches/<int:match_id>/dispute", methods=["GET","POST"])
def submit_dispute(match_id):
    match = Match.query.get_or_404(match_id)
    if request.method == "POST":
        # For MVP, require 'filed_by_id' and 'reason' from the form
        filed_by_id = request.form.get("filed_by_id")
        reason = request.form.get("reason")
        if not filed_by_id or not reason:
            flash("You must provide your player id and a reason", "danger")
            return redirect(url_for("match_detail", match_id=match.id))
        filed_by = Player.query.get(int(filed_by_id))
        if not filed_by:
            flash("Invalid filing player id", "danger")
            return redirect(url_for("match_detail", match_id=match.id))
        d = Dispute(match_id=match.id, filed_by_id=filed_by.id, reason=reason, status="open")
        db.session.add(d)
        db.session.commit()
        flash("Dispute submitted. Admins will review.", "info")
        return redirect(url_for("match_detail", match_id=match.id))
    # GET: show dispute form
    players = Player.query.order_by(Player.name).all()
    return render_template("dispute_form.html", match=match, players=players)

@app.route("/admin/disputes/<int:dispute_id>")
def admin_view_dispute(dispute_id):
    if not admin_required_check():
        return "admin required", 403
    d = Dispute.query.get_or_404(dispute_id)
    return render_template("dispute_detail.html", dispute=d)

@app.route("/admin/disputes/<int:dispute_id>/resolve", methods=["POST"])
def admin_resolve_dispute(dispute_id):
    if not admin_required_check():
        return jsonify({"error":"admin required"}), 403
    d = Dispute.query.get_or_404(dispute_id)
    action = request.form.get("action")  # 'approve', 'dismiss', 'void_match'
    resolution_text = request.form.get("resolution") or ""
    if action == "approve":
        d.status = "resolved"
        d.resolution = resolution_text or "Admin resolved in favor of filer."
        # you might apply effects (e.g., change match result) here
        flash("Dispute resolved in favor of filer", "success")
    elif action == "dismiss":
        d.status = "dismissed"
        d.resolution = resolution_text or "Admin dismissed the dispute."
        flash("Dispute dismissed", "info")
    elif action == "void_match":
        d.status = "resolved"
        d.resolution = resolution_text or "Admin voided the match."
        # void the match: set status to 'void' and optionally refund stakes
        m = d.match
        m.status = "void"
        db.session.add(m)
        flash("Match voided", "warning")
    else:
        flash("Unknown action", "danger")
        return redirect(url_for("admin_view_dispute", dispute_id=dispute_id))

    db.session.add(d)
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

# --- Admin login required decorator ---
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in as admin to access this page.", "warning")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# --- Admin login route ---
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session["admin_id"] = True
            flash("Logged in successfully.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("admin_login.html")


# --- Admin logout route ---
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin_login"))


# --- Admin dashboard ---
@app.route("/admin/dashboard")
def admin_dashboard_view():
    # ✅ Allow local testing with ?admin=true
    if request.args.get("admin") == "true":
        session["admin"] = True

    # ✅ Check session state
    if not session.get("admin"):
        return "Admin access required. For quick local testing add ?admin=true", 403

    # ✅ Proceed to render dashboard
    settings = get_admin_settings()
    matches = Match.query.order_by(Match.created_at.desc()).all()
    disputes = Dispute.query.order_by(Dispute.created_at.desc()).all()
    players = Player.query.order_by(Player.name).all()
    return render_template(
        "admin_dashboard.html",
        settings=settings,
        matches=matches,
        disputes=disputes,
        players=players,
    )


# ============================
# 🛡️ Admin Authentication System
# ============================

from werkzeug.security import generate_password_hash, check_password_hash

# Optional: only if not already imported
from flask import session, redirect, url_for, flash, render_template, request

# Create a single admin account (you can extend this to a DB later)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("admin123")  # default password: admin123

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin"] = True
            flash("Welcome, Admin!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid credentials. Please try again.", "danger")
            return redirect(url_for("admin_login"))

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout_page():
    session.pop("admin", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
def admin_dashboard_page():
    # ✅ Allow local testing with ?admin=true
    if request.args.get("admin") == "true":
        session["admin"] = True

    # ✅ Check session state
    if not session.get("admin"):
        return "Admin access required. For quick local testing add ?admin=true", 403

    # ✅ Proceed to render dashboard
    settings = get_admin_settings()
    matches = Match.query.order_by(Match.created_at.desc()).all()
    disputes = Dispute.query.order_by(Dispute.created_at.desc()).all()
    players = Player.query.order_by(Player.name).all()
    return render_template(
        "admin_dashboard.html",
        settings=settings,
        matches=matches,
        disputes=disputes,
        players=players,
    )

def generate_ai_recommendations(player_stats):
    # Basic AI logic (you can expand this later)
    tips_pool = {
        "soccer": [
            "Focus on your first touch and passing accuracy.",
            "Work on stamina and field awareness drills.",
            "Try agility ladder drills to improve footwork."
        ],
        "basketball": [
            "Improve your shooting consistency.",
            "Work on defensive positioning and reaction time.",
            "Focus on upper body strength training."
        ],
        "tennis": [
            "Improve your serve accuracy.",
            "Enhance lateral quickness and court coverage.",
            "Focus on backhand consistency drills."
        ]
    }

    sport = player_stats.sport.lower() if player_stats.sport else "general"
    suggestions = tips_pool.get(sport, [
        "Maintain consistent training habits.",
        "Analyze your match footage for improvements.",
        "Focus on nutrition and rest for performance gains."
    ])

    return random.sample(suggestions, min(2, len(suggestions)))


@app.route("/player/<int:player_id>/update_stats", methods=["POST"])
def update_player_stats(player_id):
    stats = PlayerStats.query.filter_by(player_id=player_id).first()
    if not stats:
        stats = PlayerStats(player_id=player_id)
        db.session.add(stats)

    result = request.form.get("result")  # "win" or "loss"
    if result == "win":
        stats.wins += 1
        stats.skill_rating += 25
    elif result == "loss":
        stats.losses += 1
        stats.skill_rating = max(800, stats.skill_rating - 15)

    stats.matches_played += 1
    history = json.loads(stats.progress_data) if stats.progress_data else []
    history.append({"match": stats.matches_played, "rating": stats.skill_rating})
    stats.progress_data = json.dumps(history)
    stats.last_updated = datetime.utcnow()
    db.session.commit()

    flash("Player stats updated successfully!", "success")
    return redirect(url_for("player_stats", player_id=player_id))

@app.route("/player/<int:player_id>")
def view_player(player_id):
    player = Player.query.get(player_id)

    stats = {
        "wins": player.wins,
        "losses": player.losses,
        "rating": player.rating,
        "past_ratings": [player.rating - 40, player.rating - 20, player.rating]
    }

    ai_tips = generate_ai_recommendations(player.name, player.sport, stats)

    return render_template("player_stats.html", player=player, ai_tips=ai_tips)

@app.route("/player/<int:player_id>/stats")
def player_stats(player_id):
    from app.models import Player, Team, Match  # local import to avoid circulars
    from app import db
    from app.ai_recommendations import update_skill_rating, generate_ai_recommendations

    player = Player.query.get(player_id)
    if not player:
        abort(404, description="Player not found")

    team = Team.query.get(player.team_id) if player.team_id else None

    # --- Compute average skill ---
    if hasattr(player, "skills") and player.skills:
        skill_values = [s.value if hasattr(s, "value") else 0 for s in player.skills]
        avg_skill = sum(skill_values) / len(skill_values) if skill_values else 0
    else:
        avg_skill = getattr(player, "skill_rating", 1000)

    # --- Gather match data ---
    matches_played = Match.query.filter(
        (Match.team1_id == player.team_id) | (Match.team2_id == player.team_id)
    ).all() if player.team_id else []

    wins = sum(1 for m in matches_played if m.winner_team_id == player.team_id)
    total_matches = len(matches_played)
    win_rate = (wins / total_matches * 100) if total_matches else 0

    # --- Update player’s skill dynamically ---
    new_rating = update_skill_rating(player, wins, total_matches)
    db.session.commit()

    # --- Prepare stats object for AI ---
    stats_obj = {
        "win_rate": win_rate,
        "skill_rating": new_rating
    }

    ai_tips = generate_ai_recommendations(
        player,
        stats=stats_obj,
        sport=team.sport if team and hasattr(team, "sport") else None
    )

    # --- Render Template ---
    return render_template(
        "player_stats.html",
        player=player,
        team=team,
        matches_played=total_matches,
        wins=wins,
        avg_skill=new_rating,
        win_rate=win_rate,
        ai_tips=ai_tips
    )



@app.route("/dashboard")
def dashboard():
    current_team = ...  # however you determine the logged-in user’s team
    opponents = recommend_opponents(current_team)
    suggested_venues = recommend_venues(current_team)
    return render_template(
        "dashboard.html",
        current_team=current_team,
        opponents=opponents,
        suggested_venues=suggested_venues
    )


@app.route("/admin/match/<int:match_id>/set_result", methods=["POST"])
def admin_set_match_result(match_id):
    match = Match.query.get_or_404(match_id)
    winner_team_id = request.form.get("winner_team_id")

    if not winner_team_id:
        flash("No team selected as winner", "danger")
        return redirect(url_for("admin_dashboard"))

    winner_team_id = int(winner_team_id)
    winner_team = Team.query.get(winner_team_id)
    loser_team = match.team1 if match.team2_id == winner_team_id else match.team2

    # Update match result
    match.status = "completed"
    match.winner_team_id = winner_team_id

    # Update team stats
    winner_team.matches_played = (winner_team.matches_played or 0) + 1
    winner_team.matches_won = (winner_team.matches_won or 0) + 1

    loser_team.matches_played = (loser_team.matches_played or 0) + 1
    loser_team.matches_lost = (loser_team.matches_lost or 0) + 1

    db.session.commit()
    flash(f"Match result updated: {winner_team.name} won!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/player/<int:player_id>/update_stats", methods=["GET", "POST"])
def admin_update_player_stats(player_id):
    from .models import Player, PlayerStats, db

    player = Player.query.get_or_404(player_id)
    stats = PlayerStats.query.filter_by(player_id=player_id).first()
    if not stats:
        stats = PlayerStats(player_id=player.id, sport=player.role or "Unknown")
        db.session.add(stats)
        db.session.commit()

    if request.method == "POST":
        stats.matches_played = int(request.form.get("matches_played", stats.matches_played))
        stats.wins = int(request.form.get("wins", stats.wins))
        stats.losses = int(request.form.get("losses", stats.losses))
        stats.skill_rating = float(request.form.get("skill_rating", stats.skill_rating))
        db.session.commit()
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_update_player_stats.html", player=player, stats=stats)

@app.route("/api/team/<int:team_id>/winnings")
def api_get_team_winnings(team_id):
    """Return the total winnings for a team (used by team_detail auto-refresh)."""
    team = Team.query.get_or_404(team_id)
    return jsonify({"total_winnings": round(team.total_winnings or 0, 2)})

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        # Check if email already exists
        if Team.query.filter_by(email=email).first():
            flash("Email already in use.", "danger")
            return redirect(url_for("register"))

        team = Team(
            name=name,
            email=email,                 # ✅ FIXED
            color=request.form.get("color"),
            skill=request.form.get("skill", 50),
            sport=request.form.get("sport"),
        )

        team.set_password(password)

        db.session.add(team)
        db.session.commit()

        

        flash("Team registered successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        team = Team.query.filter_by(email=email).first()

        if not team or not team.check_password(password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

        session["team_id"] = team.id
        flash("Logged in successfully!", "success")
        return redirect(url_for("team_detail", team_id=team.id))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("team_id", None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))

@app.route("/free_agents")
def free_agents():
    pool = Team.query.filter_by(is_free_agent_pool=True).first_or_404()
    players = Player.query.filter_by(team_id=pool.id).all()
    return render_template("free_agents.html", pool=pool, players=players)

@app.route("/free_agents/add", methods=["POST"])
def add_free_agent():
    pool = Team.query.filter_by(is_free_agent_pool=True).first_or_404()

    name = request.form["name"]
    sport = request.form.get("sport", "Unknown")
    role = request.form.get("role", None)
    skill = request.form.get("skill", 50)

    player = Player(
        name=name,
        role=role,
        sport=sport,
        skill_rating=skill,
        team_id=pool.id
    )

    db.session.add(player)
    db.session.commit()

    flash("You have been added to the Free Agent Pool!", "success")
    return redirect(url_for("free_agents"))










# end of file
