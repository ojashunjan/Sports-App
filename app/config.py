import os
import stripe
import stripe


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Stripe keys (replace with your test keys)
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'x')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLIC_KEY', 'x')
    APP_COMMISSION = 0.05
