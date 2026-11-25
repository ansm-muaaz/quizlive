"""
QuizLive — Main Flask application entry point.
"""

from flask import Flask, render_template, url_for as flask_url_for

from config import Config, load_environment
from auth import get_current_user
from supabase_client import IS_DEMO_MODE

# Blueprint imports
from routes.auth_routes import auth_bp
from routes.main_routes import main_bp
from routes.quiz_routes import quiz_bp
from routes.play_routes import play_bp
from routes.game_routes import game_bp
from routes.dashboard_routes import dashboard_bp


import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app() -> Flask:
    """Application factory."""
    load_environment()
    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )

    # --- Configuration ---------------------------------------------------
    app.config.from_object(Config)
    app.secret_key = Config.SECRET_KEY

    # --- Register blueprints ---------------------------------------------
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(play_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(dashboard_bp)

    # --- URL endpoint aliasing for templates -----------------------------
    endpoint_aliases = {
        # Main
        "index": "main.index",
        "join_game": "main.join",
        "join": "main.join",
        # Auth
        "login": "auth.login",
        "demo_login": "auth.demo_login",
        "logout": "auth.logout",
        "callback": "auth.callback",
        # Dashboard
        "dashboard": "dashboard.dashboard",
        "host_dashboard": "dashboard.dashboard",
        "participant_dashboard": "dashboard.dashboard",
        "host_results": "dashboard.results_overview",
        "quiz_results": "dashboard.quiz_results",
        # Quizzes
        "host_quizzes": "quizzes.list_quizzes",
        "list_quizzes": "quizzes.list_quizzes",
        "create_quiz": "quizzes.new_quiz",
        "new_quiz": "quizzes.new_quiz",
        "edit_quiz": "quizzes.edit_quiz",
        "update_quiz": "quizzes.update_quiz",
        "delete_quiz": "quizzes.delete_quiz",
        "duplicate_quiz": "quizzes.duplicate_quiz",
        "add_question": "quizzes.add_question",
        "update_question": "quizzes.update_question",
        "delete_question": "quizzes.delete_question",
        # Participant Self-Paced Play
        "browse_quizzes": "play.browse",
        "browse": "play.browse",
        "take_quiz": "play.take_quiz",
        "submit_quiz": "play.submit_quiz",
        # Live Game
        "start_game": "game.create_game",
        "create_game": "game.create_game",
        "host_control": "game.host_control",
        "play_game": "game.play_game",
        "game_podium": "game.game_podium",
        "export_quiz_results": "dashboard.export_quiz_results",
    }

    orig_url_for = flask_url_for

    def smart_url_for(endpoint, **values):
        target = endpoint_aliases.get(endpoint, endpoint)
        try:
            return orig_url_for(target, **values)
        except Exception:
            try:
                return orig_url_for(endpoint, **values)
            except Exception:
                return f"#{endpoint}"

    app.jinja_env.globals["url_for"] = smart_url_for

    # --- Context processor ------------------------------------------------
    @app.context_processor
    def inject_globals():
        """Make ``current_user`` and ``is_demo_mode`` available in every Jinja2 template."""
        return {
            "current_user": get_current_user(),
            "is_demo_mode": IS_DEMO_MODE,
        }

    # --- Error Handlers ---------------------------------------------------
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template("errors/500.html"), 500

    return app


# When running directly: python app.py
if __name__ == "__main__":
    application = create_app()
    application.run(debug=True, host="0.0.0.0", port=5000)
