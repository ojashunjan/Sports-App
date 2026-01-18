from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .config import Config
import os
import stripe

db = SQLAlchemy()

def create_free_agent_team():
    from .models import Team  # avoid circular import

    free_agents = Team.query.filter_by(name="Free Agent Pool").first()
    if not free_agents:
        free_agents = Team(
            name="Free Agent Pool",
            email="freeagents@system.internal",
            color="grey",
            skill=50,
            sport="All"
        )
        free_agents.set_password("freeagents")  # just required by model
        db.session.add(free_agents)
        db.session.commit()


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Load config
    app.config.from_object(Config)

    # Core config
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sports.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'dev-secret'

    # Stripe config
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY')
    app.config['STRIPE_PUBLIC_KEY'] = os.environ.get('STRIPE_PUBLIC_KEY')
    app.config['APP_COMMISSION'] = 0.05

    # Init DB
    db.init_app(app)

    with app.app_context():
        # import routes + models
        from . import routes, models

        # Create tables
        db.create_all()

        # ⭐ Create Free Agent Pool here (Flask 3.1-compatible)
        create_free_agent_team()

    return app
