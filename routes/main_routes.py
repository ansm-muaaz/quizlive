"""
QuizLive — Main / landing page routes.
"""

from flask import Blueprint, render_template, redirect, url_for
from auth import get_current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Landing page (unauthenticated) or redirect to dashboard."""
    user = get_current_user()
    if user:
        return redirect(url_for("dashboard.dashboard"))
    return render_template("landing.html")


@main_bp.route("/join")
def join():
    """Public join page for live game — enter PIN + nickname, no login needed."""
    return render_template("game/join.html")
