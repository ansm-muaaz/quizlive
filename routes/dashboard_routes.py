"""
QuizLive — Dashboard and results routes.
"""

import csv
import io
from flask import (
    Blueprint,
    render_template,
    abort,
    jsonify,
    Response,
)

from auth import login_required, host_required, get_current_user
from supabase_client import supabase_admin

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    """Role-aware dashboard.

    Hosts  → list of their quizzes with stats and quick actions.
    Participants → their own result history.
    """
    user = get_current_user()

    if user["role"] == "host":
        quizzes_resp = (
            supabase_admin.table("quizzes")
            .select("*, results(id), questions(id)")
            .eq("host_id", user["id"])
            .order("created_at", desc=True)
            .execute()
        )
        quizzes = quizzes_resp.data or []
        for q in quizzes:
            q["result_count"] = len(q.get("results", []))
            q["question_count"] = len(q.get("questions", []))

        # Count active live games
        active_resp = (
            supabase_admin.table("game_sessions")
            .select("id")
            .eq("host_id", user["id"])
            .neq("status", "finished")
            .execute()
        )
        active_games = len(active_resp.data or [])

        total_quizzes = len(quizzes)
        total_results = sum(q["result_count"] for q in quizzes)

        return render_template(
            "host/dashboard.html",
            quizzes=quizzes,
            user=user,
            total_quizzes=total_quizzes,
            total_results=total_results,
            active_games=active_games,
        )

    # Participant dashboard
    results_resp = (
        supabase_admin.table("results")
        .select("*, quizzes(title)")
        .eq("user_id", user["id"])
        .order("submitted_at", desc=True)
        .execute()
    )
    results = results_resp.data or []
    for r in results:
        q_data = r.get("quizzes")
        if isinstance(q_data, dict):
            r["quiz_title"] = q_data.get("title") or f"Quiz #{r.get('quiz_id')}"
        elif isinstance(q_data, list) and q_data and isinstance(q_data[0], dict):
            r["quiz_title"] = q_data[0].get("title") or f"Quiz #{r.get('quiz_id')}"
        else:
            r["quiz_title"] = f"Quiz #{r.get('quiz_id')}"

    return render_template(
        "participant/dashboard.html",
        results=results,
        user=user,
    )


@dashboard_bp.route("/results")
@dashboard_bp.route("/dashboard/results")
@host_required
def results_overview():
    """Host results overview listing all quizzes with attempt counts,
    session counts, and average scores."""
    user = get_current_user()

    quizzes_resp = (
        supabase_admin.table("quizzes")
        .select("*, questions(id), results(score, total), game_sessions(id)")
        .eq("host_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    quizzes = quizzes_resp.data or []

    for q in quizzes:
        q["question_count"] = len(q.get("questions", []))
        results = q.get("results", [])
        q["attempt_count"] = len(results)
        q["session_count"] = len(q.get("game_sessions", []))

        if results:
            percentages = [
                (r["score"] / r["total"] * 100) if r.get("total", 0) > 0 else 0
                for r in results
            ]
            q["avg_score"] = sum(percentages) / len(percentages)
        else:
            q["avg_score"] = None

    return render_template("host/results.html", quizzes=quizzes)


@dashboard_bp.route("/dashboard/quiz/<int:quiz_id>")
@host_required
def quiz_results(quiz_id):
    """Detailed results for a single quiz (host only)."""
    user = get_current_user()

    # Verify ownership
    quiz_resp = (
        supabase_admin.table("quizzes")
        .select("*, questions(id)")
        .eq("id", quiz_id)
        .eq("host_id", user["id"])
        .execute()
    )
    if not quiz_resp.data:
        abort(404)

    quiz_data = quiz_resp.data[0]
    quiz_data["question_count"] = len(quiz_data.get("questions", []))

    # Self-paced results
    results_resp = (
        supabase_admin.table("results")
        .select("*, profiles(name, email)")
        .eq("quiz_id", quiz_id)
        .order("score", desc=True)
        .execute()
    )
    self_paced_results = []
    for r in results_resp.data or []:
        p_data = r.get("profiles")
        if isinstance(p_data, dict):
            p_name = p_data.get("name") or p_data.get("email")
        elif isinstance(p_data, list) and p_data and isinstance(p_data[0], dict):
            p_name = p_data[0].get("name") or p_data[0].get("email")
        else:
            p_name = "Participant"

        self_paced_results.append(
            {
                "id": r["id"],
                "participant_name": p_name or "Anonymous",
                "score": r["score"],
                "total": r["total"],
                "completed_at": r.get("submitted_at", ""),
            }
        )

    # Live game sessions
    sessions_resp = (
        supabase_admin.table("game_sessions")
        .select("*, participants(id, nickname, score)")
        .eq("quiz_id", quiz_id)
        .order("id", desc=True)
        .execute()
    )
    game_sessions = sessions_resp.data or []
    for s in game_sessions:
        s["participants"] = sorted(
            s.get("participants", []),
            key=lambda p: p.get("score", 0),
            reverse=True,
        )

    return render_template(
        "host/quiz_results.html",
        quiz=quiz_data,
        results=results_resp.data or [],
        self_paced_results=self_paced_results,
        game_sessions=game_sessions,
    )


@dashboard_bp.route("/dashboard/quiz/<int:quiz_id>/export")
@host_required
def export_quiz_results(quiz_id):
    """Export self-paced quiz attempts to a downloadable CSV file."""
    user = get_current_user()
    quiz_resp = (
        supabase_admin.table("quizzes")
        .select("title")
        .eq("id", quiz_id)
        .eq("host_id", user["id"])
        .execute()
    )
    if not quiz_resp.data:
        abort(404)
    quiz_title = quiz_resp.data[0]["title"]

    results_resp = (
        supabase_admin.table("results")
        .select("*, profiles(name, email)")
        .eq("quiz_id", quiz_id)
        .order("score", desc=True)
        .execute()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rank", "Participant Name", "Email", "Score", "Total", "Percentage", "Submitted At"])

    for idx, r in enumerate(results_resp.data or [], 1):
        p_data = r.get("profiles")
        if isinstance(p_data, dict):
            p_name = p_data.get("name") or "Anonymous"
            p_email = p_data.get("email") or ""
        elif isinstance(p_data, list) and p_data and isinstance(p_data[0], dict):
            p_name = p_data[0].get("name") or "Anonymous"
            p_email = p_data[0].get("email") or ""
        else:
            p_name = "Anonymous"
            p_email = ""

        score = r.get("score", 0)
        total = r.get("total", 0)
        pct = f"{(score / total * 100):.1f}%" if total > 0 else "0%"
        submitted_at = r.get("submitted_at") or ""
        writer.writerow([idx, p_name, p_email, score, total, pct, submitted_at])

    safe_title = "".join(c for c in quiz_title if c.isalnum() or c in ("-", "_")).rstrip() or f"quiz_{quiz_id}"
    filename = f"{safe_title}_results.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@dashboard_bp.route("/api/results/<int:quiz_id>")
@host_required
def api_results(quiz_id):
    """JSON endpoint returning result data for Chart.js visualisation."""
    user = get_current_user()

    # Verify ownership
    quiz_resp = (
        supabase_admin.table("quizzes")
        .select("id")
        .eq("id", quiz_id)
        .eq("host_id", user["id"])
        .execute()
    )
    if not quiz_resp.data:
        return jsonify({"error": "not found"}), 404

    results_resp = (
        supabase_admin.table("results")
        .select("score, total, profiles(name)")
        .eq("quiz_id", quiz_id)
        .order("score", desc=True)
        .execute()
    )

    labels = []
    scores = []
    totals = []
    for r in results_resp.data or []:
        p_data = r.get("profiles")
        if isinstance(p_data, dict):
            name = p_data.get("name") or "Participant"
        elif isinstance(p_data, list) and p_data and isinstance(p_data[0], dict):
            name = p_data[0].get("name") or "Participant"
        else:
            name = "Participant"
        labels.append(name)
        scores.append(r["score"])
        totals.append(r["total"])

    return jsonify(
        {
            "labels": labels,
            "scores": scores,
            "totals": totals,
        }
    )
