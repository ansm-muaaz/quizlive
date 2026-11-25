"""
QuizLive — Live game mode routes.

Host controls the game pace; players answer in real-time.
Polling-based state synchronisation via JSON endpoints.
"""

import random
import re
from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    jsonify,
    session,
)

from auth import host_required, login_required, get_current_user
from supabase_client import supabase_admin

game_bp = Blueprint("game", __name__)

NICKNAME_RE = re.compile(r"^[\w\s]{2,20}$", re.UNICODE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_pin() -> str:
    """Generate a unique 6-digit PIN not currently in use by active sessions."""
    for _ in range(20):
        pin = f"{random.randint(100000, 999999)}"
        existing = (
            supabase_admin.table("game_sessions")
            .select("id")
            .eq("pin", pin)
            .neq("status", "finished")
            .execute()
        )
        if not existing.data:
            return pin
    # Extremely unlikely fallback
    return f"{random.randint(100000, 999999)}"


def _get_session(session_id: int) -> dict | None:
    resp = (
        supabase_admin.table("game_sessions")
        .select("*")
        .eq("id", session_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _get_questions_for_session(game_session: dict) -> list[dict]:
    resp = (
        supabase_admin.table("questions")
        .select("*")
        .eq("quiz_id", game_session["quiz_id"])
        .order("id")
        .execute()
    )
    return resp.data


def _current_question_data(game_session: dict, questions: list[dict]) -> dict | None:
    idx = game_session.get("current_question", 0)
    if idx < 1 or idx > len(questions):
        return None
    return questions[idx - 1]


def _leaderboard(session_id: int, top_n: int = 10) -> list[dict]:
    resp = (
        supabase_admin.table("participants")
        .select("id, nickname, score")
        .eq("session_id", session_id)
        .order("score", desc=True)
        .limit(top_n)
        .execute()
    )
    return resp.data


def _participant_count(session_id: int) -> int:
    resp = (
        supabase_admin.table("participants")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .execute()
    )
    return resp.count or 0


def _time_remaining(game_session: dict, question: dict | None) -> float | None:
    """Seconds remaining for the current question, or None."""
    if game_session["status"] != "question" or question is None:
        return None
    started_str = game_session.get("question_started_at")
    if not started_str:
        return None
    started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    time_limit = int(question.get("time_limit") or 30)
    remaining = max(0, time_limit - elapsed)
    return round(remaining, 1)


# ---------------------------------------------------------------------------
# Host endpoints
# ---------------------------------------------------------------------------

@game_bp.route("/game/create/<int:quiz_id>", methods=["GET", "POST"])
@host_required
def create_game(quiz_id):
    """Create a new game session for a quiz."""
    user = get_current_user()

    # Verify quiz ownership and that it has questions
    quiz_resp = (
        supabase_admin.table("quizzes")
        .select("id")
        .eq("id", quiz_id)
        .eq("host_id", user["id"])
        .execute()
    )
    if not quiz_resp.data:
        abort(404)

    q_count = (
        supabase_admin.table("questions")
        .select("id", count="exact")
        .eq("quiz_id", quiz_id)
        .execute()
    )
    if not q_count.count:
        flash("Cannot start a game with no questions.", "warning")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))

    pin = _generate_pin()

    try:
        resp = (
            supabase_admin.table("game_sessions")
            .insert(
                {
                    "pin": pin,
                    "quiz_id": quiz_id,
                    "host_id": user["id"],
                    "status": "lobby",
                    "current_question": 0,
                }
            )
            .execute()
        )
        session_id = resp.data[0]["id"]
        return redirect(url_for("game.host_control", session_id=session_id))
    except Exception as e:
        flash(f"Error creating game: {e}", "danger")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))


@game_bp.route("/game/host/<int:session_id>")
@host_required
def host_control(session_id):
    """Host control page — lobby view, then advance-question controls."""
    user = get_current_user()
    gs = _get_session(session_id)
    if not gs or gs["host_id"] != user["id"]:
        abort(404)

    questions = _get_questions_for_session(gs)
    return render_template(
        "game/host_control.html",
        game_session=gs,
        questions=questions,
        total_questions=len(questions),
    )


@game_bp.route("/game/host/<int:session_id>/start", methods=["POST"])
@host_required
def start_game(session_id):
    """Start the game — transition from lobby to the first question."""
    user = get_current_user()
    gs = _get_session(session_id)
    if not gs or gs["host_id"] != user["id"]:
        abort(404)

    if gs["status"] != "lobby":
        flash("Game has already started.", "warning")
        return redirect(url_for("game.host_control", session_id=session_id))

    now = datetime.now(timezone.utc).isoformat()
    supabase_admin.table("game_sessions").update(
        {
            "status": "question",
            "current_question": 1,
            "question_started_at": now,
        }
    ).eq("id", session_id).execute()

    return redirect(url_for("game.host_control", session_id=session_id))


@game_bp.route("/game/host/<int:session_id>/next", methods=["POST"])
@host_required
def next_step(session_id):
    """Advance the game:
    question → reveal  |  reveal → next question (or finished).
    """
    user = get_current_user()
    gs = _get_session(session_id)
    if not gs or gs["host_id"] != user["id"]:
        abort(404)

    questions = _get_questions_for_session(gs)
    total = len(questions)
    status = gs["status"]
    current = gs["current_question"]

    if status == "question":
        update = {"status": "reveal"}
    elif status == "reveal":
        if current >= total:
            update = {"status": "finished"}
        else:
            update = {
                "status": "question",
                "current_question": current + 1,
                "question_started_at": datetime.now(timezone.utc).isoformat(),
            }
    else:
        flash("Cannot advance from this state.", "warning")
        return redirect(url_for("game.host_control", session_id=session_id))

    supabase_admin.table("game_sessions").update(update).eq("id", session_id).execute()
    return redirect(url_for("game.host_control", session_id=session_id))


@game_bp.route("/game/host/<int:session_id>/state")
@host_required
def host_state(session_id):
    """JSON endpoint: full game state for the host."""
    user = get_current_user()
    gs = _get_session(session_id)
    if not gs or gs["host_id"] != user["id"]:
        return jsonify({"error": "not found"}), 404

    questions = _get_questions_for_session(gs)
    current_q = _current_question_data(gs, questions)

    # Count answers for current question
    answer_count = 0
    answer_breakdown = {"A": 0, "B": 0, "C": 0, "D": 0}
    if current_q:
        ans_resp = (
            supabase_admin.table("answers")
            .select("choice")
            .eq("question_id", current_q["id"])
            .execute()
        )
        answer_count = len(ans_resp.data)
        for a in ans_resp.data:
            ch = a["choice"].upper()
            if ch in answer_breakdown:
                answer_breakdown[ch] += 1

    data = {
        "status": gs["status"],
        "pin": gs["pin"],
        "current_question": gs["current_question"],
        "total_questions": len(questions),
        "participant_count": _participant_count(session_id),
        "leaderboard": _leaderboard(session_id),
        "time_remaining": _time_remaining(gs, current_q),
        "answer_count": answer_count,
        "answer_breakdown": answer_breakdown,
    }

    if current_q:
        data["question"] = {
            "id": current_q["id"],
            "question_text": current_q["question_text"],
            "option_a": current_q["option_a"],
            "option_b": current_q["option_b"],
            "option_c": current_q["option_c"],
            "option_d": current_q["option_d"],
            "correct_option": current_q["correct_option"],
            "image_url": current_q.get("image_url"),
            "time_limit": current_q["time_limit"],
        }

    return jsonify(data)


# ---------------------------------------------------------------------------
# Player endpoints
# ---------------------------------------------------------------------------

@game_bp.route("/game/join", methods=["POST"])
def join_game():
    """Join a live game with PIN + nickname.  No login required."""
    pin = request.form.get("pin", "").strip()
    nickname = request.form.get("nickname", "").strip()

    if not pin or len(pin) != 6 or not pin.isdigit():
        flash("Please enter a valid 6-digit PIN.", "danger")
        return redirect(url_for("main.join"))

    if not NICKNAME_RE.match(nickname):
        flash("Nickname must be 2–20 characters (letters, numbers, spaces).", "danger")
        return redirect(url_for("main.join"))

    # Find active session by PIN
    gs_resp = (
        supabase_admin.table("game_sessions")
        .select("*")
        .eq("pin", pin)
        .neq("status", "finished")
        .execute()
    )
    if not gs_resp.data:
        flash("No active game found with that PIN.", "danger")
        return redirect(url_for("main.join"))

    gs = gs_resp.data[0]

    # Check for duplicate nickname in this session
    dup = (
        supabase_admin.table("participants")
        .select("id")
        .eq("session_id", gs["id"])
        .eq("nickname", nickname)
        .execute()
    )
    if dup.data:
        flash("That nickname is already taken in this game.", "warning")
        return redirect(url_for("main.join"))

    # Determine user_id if logged in
    user = get_current_user()
    user_id = user["id"] if user else None

    try:
        resp = (
            supabase_admin.table("participants")
            .insert(
                {
                    "session_id": gs["id"],
                    "user_id": user_id,
                    "nickname": nickname,
                    "score": 0,
                }
            )
            .execute()
        )
        participant = resp.data[0]
        session["participant_id"] = participant["id"]
        session["participant_session_id"] = gs["id"]
        return redirect(url_for("game.play_game", session_id=gs["id"]))
    except Exception as e:
        flash(f"Error joining game: {e}", "danger")
        return redirect(url_for("main.join"))


@game_bp.route("/game/play/<int:session_id>")
def play_game(session_id):
    """Player game page — polls for state via JS."""
    participant_id = session.get("participant_id")
    p_session = session.get("participant_session_id")

    if not participant_id or p_session != session_id:
        flash("Please join the game first.", "warning")
        return redirect(url_for("main.join"))

    gs = _get_session(session_id)
    if not gs:
        abort(404)

    return render_template(
        "game/play.html",
        game_session=gs,
        participant_id=participant_id,
    )


@game_bp.route("/game/play/<int:session_id>/answer", methods=["POST"])
def submit_answer(session_id):
    """Submit an answer for the current question in a live game."""
    participant_id = session.get("participant_id")
    p_session = session.get("participant_session_id")

    if not participant_id or p_session != session_id:
        return jsonify({"error": "Not in this game"}), 403

    gs = _get_session(session_id)
    if not gs or gs["status"] != "question":
        return jsonify({"error": "Not accepting answers right now"}), 400

    questions = _get_questions_for_session(gs)
    current_q = _current_question_data(gs, questions)
    if not current_q:
        return jsonify({"error": "No current question"}), 400

    # Check for duplicate answer
    dup = (
        supabase_admin.table("answers")
        .select("id")
        .eq("participant_id", participant_id)
        .eq("question_id", current_q["id"])
        .execute()
    )
    if dup.data:
        return jsonify({"error": "Already answered this question"}), 409

    data = request.get_json(silent=True) or {}
    choice = data.get("choice", "").upper()
    if choice not in {"A", "B", "C", "D"}:
        return jsonify({"error": "Invalid choice"}), 400

    # Calculate time taken
    started_str = gs.get("question_started_at")
    if started_str:
        started = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
        time_taken = round(
            (datetime.now(timezone.utc) - started).total_seconds(), 2
        )
    else:
        time_taken = 0

    is_correct = choice == current_q["correct_option"]

    # Points: if correct → max(100, round(1000 - time_taken * 100)), else 0
    if is_correct:
        points = max(100, round(1000 - time_taken * 100))
    else:
        points = 0

    try:
        supabase_admin.table("answers").insert(
            {
                "participant_id": participant_id,
                "question_id": current_q["id"],
                "choice": choice,
                "is_correct": is_correct,
                "points": points,
                "time_taken": time_taken,
            }
        ).execute()

        # Update participant total score
        p_resp = (
            supabase_admin.table("participants")
            .select("score")
            .eq("id", participant_id)
            .execute()
        )
        new_score = (p_resp.data[0]["score"] or 0) + points
        supabase_admin.table("participants").update(
            {"score": new_score}
        ).eq("id", participant_id).execute()

        return jsonify(
            {
                "is_correct": is_correct,
                "points": points,
                "total_score": new_score,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@game_bp.route("/game/play/<int:session_id>/state")
def player_state(session_id):
    """JSON endpoint: game state for a player (no correct answers exposed
    while status == 'question')."""
    participant_id = session.get("participant_id")
    p_session = session.get("participant_session_id")

    if not participant_id or p_session != session_id:
        return jsonify({"error": "Not in this game"}), 403

    gs = _get_session(session_id)
    if not gs:
        return jsonify({"error": "not found"}), 404

    questions = _get_questions_for_session(gs)
    current_q = _current_question_data(gs, questions)

    # Has this player answered the current question?
    already_answered = False
    if current_q:
        ans_check = (
            supabase_admin.table("answers")
            .select("id")
            .eq("participant_id", participant_id)
            .eq("question_id", current_q["id"])
            .execute()
        )
        already_answered = bool(ans_check.data)

    # Player's current score
    p_resp = (
        supabase_admin.table("participants")
        .select("score, nickname")
        .eq("id", participant_id)
        .execute()
    )
    my_score = p_resp.data[0]["score"] if p_resp.data else 0
    my_nickname = p_resp.data[0]["nickname"] if p_resp.data else ""

    data = {
        "status": gs["status"],
        "current_question": gs["current_question"],
        "total_questions": len(questions),
        "my_score": my_score,
        "my_nickname": my_nickname,
        "already_answered": already_answered,
        "leaderboard": _leaderboard(session_id, top_n=5),
        "time_remaining": _time_remaining(gs, current_q),
    }

    if current_q:
        q_data = {
            "id": current_q["id"],
            "question_text": current_q["question_text"],
            "option_a": current_q["option_a"],
            "option_b": current_q["option_b"],
            "option_c": current_q["option_c"],
            "option_d": current_q["option_d"],
            "image_url": current_q.get("image_url"),
            "time_limit": current_q["time_limit"],
        }
        # Only reveal correct answer during 'reveal' or 'finished'
        if gs["status"] in ("reveal", "finished"):
            q_data["correct_option"] = current_q["correct_option"]
        data["question"] = q_data

    return jsonify(data)


@game_bp.route("/game/<int:session_id>/podium")
def game_podium(session_id):
    """View final game podium and standings."""
    gs = _get_session(session_id)
    if not gs:
        abort(404)
    podium = _leaderboard(session_id, top_n=10)
    return render_template("game/podium.html", game_session=gs, podium=podium)
