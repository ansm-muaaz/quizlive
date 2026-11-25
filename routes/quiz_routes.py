"""
QuizLive — Quiz CRUD routes (host only).
"""

import logging
import re
import uuid

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
)

from auth import host_required, get_current_user
from config import Config
from supabase_client import supabase_admin

quiz_bp = Blueprint("quizzes", __name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

TITLE_RE = re.compile(r"^[\w\s\-.,!?'\"()&:;]{3,100}$", re.UNICODE)
QUESTION_MAX_LEN = 500
VALID_OPTIONS = {"A", "B", "C", "D"}


def _validate_title(title: str) -> str | None:
    """Return an error message or None."""
    if not title or len(title.strip()) < 2:
        return "Title must be at least 2 characters long."
    if len(title.strip()) > 120:
        return "Title must be under 120 characters."
    return None


def _validate_question_fields(form) -> str | None:
    """Validate question form fields; return error or None."""
    text = form.get("question_text", "").strip()
    if not text or len(text) > QUESTION_MAX_LEN:
        return "Question text is required (max 500 characters)."
    for opt in ("option_a", "option_b", "option_c", "option_d"):
        if not form.get(opt, "").strip():
            return f"All four options are required ({opt.replace('_', ' ').title()})."
    correct = form.get("correct_option", "").strip().upper()
    if correct not in VALID_OPTIONS:
        return "Correct option must be A, B, C, or D."
    time_limit = form.get("time_limit", "30")
    try:
        tl = int(time_limit)
        if tl < 5 or tl > 300:
            return "Time limit must be between 5 and 300 seconds."
    except ValueError:
        return "Time limit must be a number."
    return None


def _upload_image(file_obj) -> str | None:
    """Upload an image to Supabase Storage and return the public URL, or
    None if no file was provided.  Raises ValueError on validation failure."""
    if file_obj is None or file_obj.filename == "":
        return None

    if file_obj.content_type not in Config.ALLOWED_IMAGE_MIME:
        raise ValueError("Only JPG and PNG images are allowed.")

    data = file_obj.read()
    if len(data) > Config.MAX_IMAGE_SIZE:
        raise ValueError("Image must be smaller than 2 MB.")

    ext = "jpg" if file_obj.content_type == "image/jpeg" else "png"
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = f"question-images/{filename}"

    supabase_admin.storage.from_("question-images").upload(
        path=filename,
        file=data,
        file_options={"content-type": file_obj.content_type},
    )

    public_url = supabase_admin.storage.from_("question-images").get_public_url(filename)
    return public_url


def _delete_image(image_url: str | None):
    """Delete an image from Supabase Storage if the URL belongs to our bucket."""
    if not image_url:
        return
    try:
        # Extract filename from URL
        filename = image_url.rstrip("/").split("/")[-1]
        if filename:
            supabase_admin.storage.from_("question-images").remove([filename])
    except Exception as exc:
        logger.warning("Failed to delete image %s from storage: %s", image_url, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@quiz_bp.route("/quizzes")
@host_required
def list_quizzes():
    """List all quizzes owned by the current host."""
    user = get_current_user()
    resp = (
        supabase_admin.table("quizzes")
        .select("*, questions(id)")
        .eq("host_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    quizzes = resp.data or []
    for q in quizzes:
        q["question_count"] = len(q.get("questions", []))
    return render_template("host/quizzes.html", quizzes=quizzes)


@quiz_bp.route("/quizzes/new", methods=["GET", "POST"])
@host_required
def new_quiz():
    """Show the create-quiz form on GET, or process creation on POST."""
    if request.method == "POST":
        return create_quiz()
    return render_template("host/quiz_form.html", quiz=None)


@quiz_bp.route("/quizzes", methods=["GET", "POST"])
@host_required
def create_quiz():
    """Create a new quiz on POST, or list quizzes on GET."""
    if request.method == "GET":
        return list_quizzes()

    user = get_current_user()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    err = _validate_title(title)
    if err:
        flash(err, "danger")
        return redirect(url_for("quizzes.new_quiz"))

    try:
        resp = (
            supabase_admin.table("quizzes")
            .insert(
                {
                    "host_id": user["id"],
                    "title": title,
                    "description": description,
                }
            )
            .execute()
        )
        quiz_id = resp.data[0]["id"]
        flash("Quiz created! Now add some questions.", "success")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))
    except Exception as e:
        flash(f"Error creating quiz: {e}", "danger")
        return redirect(url_for("quizzes.new_quiz"))


@quiz_bp.route("/quizzes/<int:quiz_id>/edit")
@host_required
def edit_quiz(quiz_id):
    """Edit quiz details and manage its questions."""
    user = get_current_user()
    quiz_resp = (
        supabase_admin.table("quizzes")
        .select("*")
        .eq("id", quiz_id)
        .eq("host_id", user["id"])
        .execute()
    )
    if not quiz_resp.data:
        abort(404)

    questions_resp = (
        supabase_admin.table("questions")
        .select("*")
        .eq("quiz_id", quiz_id)
        .order("id")
        .execute()
    )

    return render_template(
        "host/quiz_edit.html",
        quiz=quiz_resp.data[0],
        questions=questions_resp.data,
    )


@quiz_bp.route("/quizzes/<int:quiz_id>/update", methods=["POST"])
@host_required
def update_quiz(quiz_id):
    """Update quiz title / description."""
    user = get_current_user()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    err = _validate_title(title)
    if err:
        flash(err, "danger")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))

    try:
        supabase_admin.table("quizzes").update(
            {"title": title, "description": description}
        ).eq("id", quiz_id).eq("host_id", user["id"]).execute()
        flash("Quiz updated.", "success")
    except Exception as e:
        flash(f"Error updating quiz: {e}", "danger")

    return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))


@quiz_bp.route("/quizzes/<int:quiz_id>/delete", methods=["POST"])
@host_required
def delete_quiz(quiz_id):
    """Delete a quiz and all its questions (cascade handled by DB, but
    we also clean up images)."""
    user = get_current_user()

    try:
        # Fetch questions to delete their images
        q_resp = (
            supabase_admin.table("questions")
            .select("image_url")
            .eq("quiz_id", quiz_id)
            .execute()
        )
        for q in q_resp.data:
            _delete_image(q.get("image_url"))

        # Delete questions first, then quiz
        supabase_admin.table("questions").delete().eq("quiz_id", quiz_id).execute()
        supabase_admin.table("quizzes").delete().eq("id", quiz_id).eq(
            "host_id", user["id"]
        ).execute()

        flash("Quiz deleted.", "success")
    except Exception as e:
        flash(f"Error deleting quiz: {e}", "danger")

    return redirect(url_for("quizzes.list_quizzes"))


@quiz_bp.route("/quizzes/<int:quiz_id>/duplicate", methods=["POST"])
@host_required
def duplicate_quiz(quiz_id):
    """Duplicate an existing quiz along with all its questions."""
    user = get_current_user()
    quiz_resp = (
        supabase_admin.table("quizzes")
        .select("*")
        .eq("id", quiz_id)
        .eq("host_id", user["id"])
        .execute()
    )
    if not quiz_resp.data:
        abort(404)

    original_quiz = quiz_resp.data[0]
    new_title = f"Copy of {original_quiz['title']}"[:100]

    try:
        ins_quiz = (
            supabase_admin.table("quizzes")
            .insert({
                "host_id": user["id"],
                "title": new_title,
                "description": original_quiz.get("description") or "",
            })
            .execute()
        )
        new_quiz_id = ins_quiz.data[0]["id"]

        q_resp = (
            supabase_admin.table("questions")
            .select("*")
            .eq("quiz_id", quiz_id)
            .order("id")
            .execute()
        )
        for q in q_resp.data or []:
            supabase_admin.table("questions").insert({
                "quiz_id": new_quiz_id,
                "question_text": q["question_text"],
                "option_a": q["option_a"],
                "option_b": q["option_b"],
                "option_c": q["option_c"],
                "option_d": q["option_d"],
                "correct_option": q["correct_option"],
                "time_limit": q.get("time_limit", 30),
                "image_url": q.get("image_url"),
            }).execute()

        flash(f"Quiz duplicated successfully as '{new_title}'.", "success")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=new_quiz_id))
    except Exception as exc:
        flash(f"Error duplicating quiz: {exc}", "danger")
        return redirect(url_for("quizzes.list_quizzes"))


# ---------------------------------------------------------------------------
# Question management
# ---------------------------------------------------------------------------

@quiz_bp.route("/quizzes/<int:quiz_id>/questions", methods=["POST"])
@host_required
def add_question(quiz_id):
    """Add a question to a quiz."""
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
        abort(404)

    err = _validate_question_fields(request.form)
    if err:
        flash(err, "danger")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))

    image_url = None
    try:
        image_url = _upload_image(request.files.get("image"))
    except ValueError as ve:
        flash(str(ve), "danger")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))

    try:
        correct_choice = request.form["correct_option"].strip().upper()
        supabase_admin.table("questions").insert(
            {
                "quiz_id": quiz_id,
                "question_text": request.form["question_text"].strip(),
                "option_a": request.form["option_a"].strip(),
                "option_b": request.form["option_b"].strip(),
                "option_c": request.form["option_c"].strip(),
                "option_d": request.form["option_d"].strip(),
                "correct_option": correct_choice,
                "image_url": image_url,
                "time_limit": int(request.form.get("time_limit", 30)),
            }
        ).execute()
        flash("Question added.", "success")
    except Exception as e:
        flash(f"Error adding question: {e}", "danger")

    return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))


@quiz_bp.route("/questions/<int:question_id>/update", methods=["POST"])
@quiz_bp.route("/quizzes/<int:quiz_id>/questions/<int:question_id>/update", methods=["POST"])
@host_required
def update_question(question_id, quiz_id=None):
    """Update an existing question."""
    user = get_current_user()

    # Fetch existing question & verify ownership via quiz
    q_resp = (
        supabase_admin.table("questions").select("*, quizzes!inner(host_id)").eq("id", question_id).execute()
    )
    if not q_resp.data or q_resp.data[0]["quizzes"]["host_id"] != user["id"]:
        abort(404)

    question = q_resp.data[0]
    quiz_id = question["quiz_id"]

    err = _validate_question_fields(request.form)
    if err:
        flash(err, "danger")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))

    correct_choice = request.form["correct_option"].strip().upper()
    update_data = {
        "question_text": request.form["question_text"].strip(),
        "option_a": request.form["option_a"].strip(),
        "option_b": request.form["option_b"].strip(),
        "option_c": request.form["option_c"].strip(),
        "option_d": request.form["option_d"].strip(),
        "correct_option": correct_choice,
        "time_limit": int(request.form.get("time_limit", 30)),
    }

    # Handle image replacement
    new_file = request.files.get("image")
    try:
        new_url = _upload_image(new_file)
        if new_url:
            _delete_image(question.get("image_url"))
            update_data["image_url"] = new_url
    except ValueError as ve:
        flash(str(ve), "danger")
        return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))

    # Handle explicit image removal
    if request.form.get("remove_image") == "1" and not update_data.get("image_url"):
        _delete_image(question.get("image_url"))
        update_data["image_url"] = None

    try:
        supabase_admin.table("questions").update(update_data).eq("id", question_id).execute()
        flash("Question updated.", "success")
    except Exception as e:
        flash(f"Error updating question: {e}", "danger")

    return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))


@quiz_bp.route("/questions/<int:question_id>/delete", methods=["POST"])
@quiz_bp.route("/quizzes/<int:quiz_id>/questions/<int:question_id>/delete", methods=["POST"])
@host_required
def delete_question(question_id, quiz_id=None):
    """Delete a question and its image (if any)."""
    user = get_current_user()

    q_resp = (
        supabase_admin.table("questions").select("*, quizzes!inner(host_id)").eq("id", question_id).execute()
    )
    if not q_resp.data or q_resp.data[0]["quizzes"]["host_id"] != user["id"]:
        abort(404)

    question = q_resp.data[0]
    quiz_id = question["quiz_id"]

    try:
        _delete_image(question.get("image_url"))
        supabase_admin.table("questions").delete().eq("id", question_id).execute()
        flash("Question deleted.", "success")
    except Exception as e:
        flash(f"Error deleting question: {e}", "danger")

    return redirect(url_for("quizzes.edit_quiz", quiz_id=quiz_id))
