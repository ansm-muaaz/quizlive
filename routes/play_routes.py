"""
QuizLive — Self-paced quiz-taking routes (participants, login required).
"""

import json
import logging
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    jsonify,
)

from auth import login_required, get_current_user
from supabase_client import supabase_admin

logger = logging.getLogger(__name__)
play_bp = Blueprint("play", __name__)


@play_bp.route("/play")
@login_required
def browse():
    """Browse all available quizzes."""
    resp = (
        supabase_admin.table("quizzes")
        .select("*, questions(id)")
        .order("created_at", desc=True)
        .execute()
    )
    # Only show quizzes that have at least one question
    quizzes = [q for q in resp.data if q.get("questions")]
    # Attach question count
    for q in quizzes:
        q["question_count"] = len(q["questions"])

    return render_template("participant/browse.html", quizzes=quizzes)


@play_bp.route("/play/<int:quiz_id>")
@login_required
def take_quiz(quiz_id: int):
    """Show a quiz for the participant. If they already submitted,
    display their comprehensive breakdown result instead."""
    user = get_current_user()

    # Check for existing result
    result_resp = (
        supabase_admin.table("results")
        .select("*")
        .eq("user_id", user["id"])
        .eq("quiz_id", quiz_id)
        .execute()
    )
    if result_resp.data:
        result = result_resp.data[0]
        quiz_resp = (
            supabase_admin.table("quizzes").select("*").eq("id", quiz_id).execute()
        )
        quiz = quiz_resp.data[0] if quiz_resp.data else None

        questions_resp = (
            supabase_admin.table("questions")
            .select("id, question_text, option_a, option_b, option_c, option_d, correct_option, image_url, time_limit")
            .eq("quiz_id", quiz_id)
            .order("id")
            .execute()
        )
        questions = questions_resp.data or []
        user_answers = result.get("answers") or {}
        if isinstance(user_answers, str):
            try:
                user_answers = json.loads(user_answers)
            except Exception:
                user_answers = {}

        correct_count = 0
        incorrect_count = 0
        unanswered_count = 0

        has_answers = bool(user_answers) and isinstance(user_answers, dict)
        for q in questions:
            raw_user_ans = user_answers.get(str(q["id"])) if has_answers else None
            user_ans = (str(raw_user_ans) if raw_user_ans is not None else "").strip().upper()
            q["user_answer"] = user_ans
            correct_opt = (str(q.get("correct_option") or "")).strip().upper()
            q["correct_option"] = correct_opt

            if not has_answers:
                # Answer breakdown not stored in DB — show answer key mode
                q["status"] = "revealed"
            elif not user_ans:
                q["status"] = "unanswered"
                unanswered_count += 1
            elif user_ans == correct_opt:
                q["status"] = "correct"
                correct_count += 1
            else:
                q["status"] = "incorrect"
                incorrect_count += 1

        return render_template(
            "participant/result.html",
            result=result,
            quiz_id=quiz_id,
            quiz=quiz,
            questions=questions,
            correct_count=correct_count,
            incorrect_count=incorrect_count,
            unanswered_count=unanswered_count,
        )

    # Fetch quiz + questions
    quiz_resp = (
        supabase_admin.table("quizzes").select("*").eq("id", quiz_id).execute()
    )
    if not quiz_resp.data:
        abort(404)

    questions_resp = (
        supabase_admin.table("questions")
        .select("id, question_text, option_a, option_b, option_c, option_d, image_url, time_limit")
        .eq("quiz_id", quiz_id)
        .order("id")
        .execute()
    )
    if not questions_resp.data:
        flash("This quiz has no questions yet.", "warning")
        return redirect(url_for("play.browse"))

    return render_template(
        "participant/take_quiz.html",
        quiz=quiz_resp.data[0],
        questions=questions_resp.data,
    )


@play_bp.route("/play/<int:quiz_id>/submit", methods=["POST"])
@login_required
def submit_quiz(quiz_id: int):
    """Submit answers for a self-paced quiz. Score is calculated
    server-side with full answer tracking. Duplicate submissions are blocked."""
    user = get_current_user()

    # Block duplicate submission
    existing = (
        supabase_admin.table("results")
        .select("id")
        .eq("user_id", user["id"])
        .eq("quiz_id", quiz_id)
        .execute()
    )
    if existing.data:
        flash("You have already submitted this quiz.", "info")
        return redirect(url_for("play.take_quiz", quiz_id=quiz_id))

    # Fetch correct answers
    questions_resp = (
        supabase_admin.table("questions")
        .select("id, correct_option")
        .eq("quiz_id", quiz_id)
        .order("id")
        .execute()
    )
    if not questions_resp.data:
        abort(404)

    questions = questions_resp.data
    total = len(questions)
    score = 0
    user_answers = {}

    for q in questions:
        submitted = request.form.get(f"answer_{q['id']}", "").strip().upper()
        user_answers[str(q["id"])] = submitted
        if submitted == q["correct_option"]:
            score += 1

    # Save result with answers breakdown
    payload = {
        "user_id": user["id"],
        "quiz_id": quiz_id,
        "score": score,
        "total": total,
        "answers": user_answers,
    }
    try:
        supabase_admin.table("results").insert(payload).execute()
    except Exception as e:
        # Fallback if 'answers' column has not been added to PostgreSQL schema yet
        if "answers" in str(e).lower():
            logger.warning("Supabase 'results' table missing 'answers' column. Saving without breakdown: %s", e)
            payload_fallback = {
                "user_id": user["id"],
                "quiz_id": quiz_id,
                "score": score,
                "total": total,
            }
            try:
                supabase_admin.table("results").insert(payload_fallback).execute()
            except Exception as inner_e:
                flash(f"Error saving result: {inner_e}", "danger")
                return redirect(url_for("play.browse"))
        else:
            flash(f"Error saving result: {e}", "danger")
            return redirect(url_for("play.browse"))

    flash(f"Quiz submitted! You scored {score}/{total}.", "success")
    return redirect(url_for("play.take_quiz", quiz_id=quiz_id))
