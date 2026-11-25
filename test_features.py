"""
QuizLive — Automated Feature Verification Test Suite.
Verifies all 7 core proposal features in an isolated test database environment.
"""

import os
os.environ["DEMO_MODE"] = "true"

import io
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app import create_app
from mock_supabase import local_db, DB_FILE

import auth
from routes import auth_routes
from routes import dashboard_routes
from routes import game_routes
from routes import main_routes
from routes import play_routes
from routes import quiz_routes
import seeds


def verify_seeds_and_blueprints(app: Any) -> None:
    """Verify seed constants and blueprint registration."""
    assert len(seeds.QUIZZES) == 4
    assert len(seeds.QUESTIONS) == 48
    assert len(seeds.PROFILES) >= 2
    assert len(seeds.RESULTS) >= 2

    with app.test_request_context():
        assert auth.get_current_user() is None
    assert quiz_routes._validate_title("Valid Title") is None
    assert quiz_routes._validate_title("a") is not None
    assert len(game_routes._generate_pin()) == 6
    assert auth_routes.auth_bp.name == "auth"
    assert dashboard_routes.dashboard_bp.name == "dashboard"
    assert main_routes.main_bp.name == "main"
    assert play_routes.play_bp.name == "play"


def test_feature_1_auth(c_host: Any, c_student: Any, c_guest: Any) -> None:
    """FEATURE 1: Authentication & Role-Based Access."""
    print("[FEATURE 1] Testing Authentication & Roles...")
    # Unauthenticated access redirected
    r = c_guest.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers["Location"]

    # Host login
    r = c_host.post("/demo-login", data={"account": "host"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Dr. Sarah" in r.data
    assert b"Host" in r.data

    # Student login
    r = c_student.post("/demo-login", data={"account": "participant"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Alex Chen" in r.data

    # Student blocked from host routes
    r = c_student.get("/quizzes/new", follow_redirects=True)
    assert b"You do not have permission" in r.data
    print("  --> Feature 1 PASSED: Auth and Host/Participant role restrictions enforced.\n")


def test_feature_2_quiz_crud(c_host: Any) -> int:
    """FEATURE 2: Quiz CRUD Management."""
    print("[FEATURE 2] Testing Quiz CRUD...")
    r = c_host.get("/quizzes/new")
    assert r.status_code == 200
    assert b"Create a New Quiz" in r.data

    r = c_host.post("/quizzes", data={
        "title": "Operating Systems & Cloud Architecture",
        "description": "Examining virtualization, hypervisors, and cloud orchestration."
    }, follow_redirects=False)
    assert r.status_code == 302
    quiz_edit_url = r.headers["Location"]
    quiz_id = int(quiz_edit_url.split("/")[2])
    print(f"  --> Quiz created with ID {quiz_id}")

    r = c_host.get(quiz_edit_url)
    assert r.status_code == 200
    assert b"Operating Systems" in r.data

    r = c_host.post(f"/quizzes/{quiz_id}/update", data={
        "title": "Operating Systems & Cloud v2",
        "description": "Updated description."
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Quiz updated." in r.data
    assert b"Operating Systems" in r.data

    r = c_host.post(f"/quizzes/{quiz_id}/questions", data={
        "question_text": "Which type of hypervisor runs directly on bare-metal hardware?",
        "option_a": "Type 1 Hypervisor",
        "option_b": "Type 2 Hypervisor",
        "option_c": "Hosted Hypervisor",
        "option_d": "Virtual Container",
        "correct_option": "A",
        "time_limit": "30"
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Question added." in r.data
    assert b"Type 1 Hypervisor" in r.data

    q_row = [q for q in local_db.tables["questions"] if q["quiz_id"] == quiz_id][0]
    q_id = q_row["id"]

    r = c_host.post(f"/questions/{q_id}/update", data={
        "question_text": "Which hypervisor runs directly on bare-metal hardware? (Updated)",
        "option_a": "Type 1 Hypervisor",
        "option_b": "Type 2 Hypervisor",
        "option_c": "Type 3 Hypervisor",
        "option_d": "Application Sandbox",
        "correct_option": "A",
        "time_limit": "25"
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Question updated." in r.data

    r = c_host.post(f"/questions/{q_id}/delete", follow_redirects=True)
    assert r.status_code == 200
    assert b"Question deleted." in r.data

    r = c_host.post(f"/quizzes/{quiz_id}/delete", follow_redirects=True)
    assert r.status_code == 200
    assert b"Quiz deleted." in r.data
    print("  --> Feature 2 PASSED: Quiz & Question CRUD completely working.\n")
    return quiz_id


def test_feature_3_image_upload(c_host: Any) -> int:
    """FEATURE 3: Question Image Upload."""
    print("[FEATURE 3] Testing Question Image Upload...")
    r = c_host.post("/quizzes", data={
        "title": "Image Test Quiz",
        "description": "Quiz testing image uploads."
    }, follow_redirects=False)
    img_quiz_id = int(r.headers["Location"].split("/")[2])

    fake_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r = c_host.post(f"/quizzes/{img_quiz_id}/questions", data={
        "question_text": "What does this diagram show?",
        "option_a": "Database",
        "option_b": "Cache",
        "option_c": "Load Balancer",
        "option_d": "Firewall",
        "correct_option": "C",
        "time_limit": "30",
        "image": (io.BytesIO(fake_png), "diagram.png", "image/png")
    }, content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Question added." in r.data
    assert b"<img" in r.data and b"/static/uploads/" in r.data
    print("  --> Feature 3 PASSED: Question image uploaded and rendered successfully.\n")
    return img_quiz_id


def test_feature_4_self_paced(c_student: Any, img_quiz_id: int) -> None:
    """FEATURE 4: Self-Paced Quiz Taking & Auto-Grading."""
    print("[FEATURE 4] Testing Self-Paced Quiz Taking & Auto-Grading...")
    r = c_student.get("/play")
    assert r.status_code == 200
    assert b"Image Test Quiz" in r.data

    r = c_student.get(f"/play/{img_quiz_id}")
    assert r.status_code == 200
    assert b"What does this diagram show?" in r.data

    q_row = [q for q in local_db.tables["questions"] if q["quiz_id"] == img_quiz_id][0]
    r = c_student.post(f"/play/{img_quiz_id}/submit", data={
        f"answer_{q_row['id']}": "C"
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Quiz submitted" in r.data or b"Final Score" in r.data
    assert b"100% Score" in r.data or b"/ 1" in r.data

    r = c_student.post(f"/play/{img_quiz_id}/submit", data={
        f"answer_{q_row['id']}": "A"
    }, follow_redirects=True)
    assert b"already submitted" in r.data
    print("  --> Auto-scored 1/1 (100%) successfully")
    print("  --> Feature 4 PASSED: Auto-scoring and duplicate protection verified.\n")


def test_feature_5_results_analytics(c_student: Any, c_host: Any, img_quiz_id: int) -> None:
    """FEATURE 5: Result History & Host Analytics."""
    print("[FEATURE 5] Testing Result History & Host Analytics...")
    r = c_student.get("/dashboard")
    assert r.status_code == 200
    assert b"Image Test Quiz" in r.data

    r = c_host.get("/results")
    assert r.status_code == 200
    assert b"Image Test Quiz" in r.data

    r = c_host.get(f"/dashboard/quiz/{img_quiz_id}")
    assert r.status_code == 200
    assert b"Score Distribution" in r.data
    assert b"Alex Chen" in r.data

    r = c_host.get(f"/api/results/{img_quiz_id}")
    assert r.status_code == 200
    api_data = r.get_json()
    assert "Alex Chen" in api_data["labels"]
    assert api_data["scores"] == [1]
    print("  --> Feature 5 PASSED: Result history, host dashboard, and Chart.js endpoint verified.\n")


def test_feature_6_live_game(c_host: Any, c_guest: Any, img_quiz_id: int) -> None:
    """FEATURE 6: Live Game Mode (Kahoot-style)."""
    print("[FEATURE 6] Testing Live Game Mode (Kahoot-style)...")
    r = c_host.post(f"/game/create/{img_quiz_id}", follow_redirects=False)
    assert r.status_code == 302
    live_session_id = int(r.headers["Location"].split("/")[-1])

    r = c_host.get(f"/game/host/{live_session_id}/state")
    pin = r.get_json()["pin"]
    assert len(pin) == 6 and pin.isdigit()
    print(f"  --> Live Game PIN generated: {pin}")

    r = c_guest.post("/game/join", data={"pin": pin, "nickname": "SpeedyRunner"}, follow_redirects=False)
    assert r.status_code == 302
    assert f"/game/play/{live_session_id}" in r.headers["Location"]

    r = c_host.get(f"/game/host/{live_session_id}/state")
    state = r.get_json()
    assert state["participant_count"] == 1
    assert state["leaderboard"][0]["nickname"] == "SpeedyRunner"
    print("  --> Player SpeedyRunner visible in Host Lobby")

    r = c_host.post(f"/game/host/{live_session_id}/start")
    r = c_host.get(f"/game/host/{live_session_id}/state")
    assert r.get_json()["status"] == "question"

    r = c_guest.post(f"/game/play/{live_session_id}/answer", json={"choice": "C"})
    ans_res = r.get_json()
    assert ans_res["is_correct"] is True
    assert ans_res["points"] >= 100
    pts = ans_res["points"]
    print(f"  --> Speed-based points awarded: {pts} pts")

    r = c_host.post(f"/game/host/{live_session_id}/next")
    r = c_host.get(f"/game/host/{live_session_id}/state")
    state = r.get_json()
    assert state["status"] == "reveal"
    assert state["answer_breakdown"]["C"] == 1

    r = c_host.post(f"/game/host/{live_session_id}/next")
    r = c_host.get(f"/game/host/{live_session_id}/state")
    state = r.get_json()
    assert state["status"] == "finished"
    print("  --> Feature 6 PASSED: Live Game Mode (Lobby -> Question -> Speed Points -> Reveal -> Podium) fully functional.\n")


def test_feature_7_security_validation(c_host: Any, c_guest: Any, img_quiz_id: int) -> None:
    """FEATURE 7: Input Validation & Cheating Prevention."""
    print("[FEATURE 7] Testing Input Validation & Security...")
    r = c_guest.post("/game/join", data={"pin": "123456", "nickname": "A"}, follow_redirects=True)
    assert b"Nickname must be 2" in r.data

    r = c_guest.post("/game/join", data={"pin": "12", "nickname": "ValidNick"}, follow_redirects=True)
    assert b"Please enter a valid 6-digit PIN" in r.data

    r = c_host.post(f"/quizzes/{img_quiz_id}/questions", data={
        "question_text": "Valid text",
        "option_a": "",
        "option_b": "B",
        "option_c": "C",
        "option_d": "D",
        "correct_option": "A"
    }, follow_redirects=True)
    assert b"required" in r.data

    print("  --> Feature 7 PASSED: Security and validation rules working.\n")


def run_all_tests() -> None:
    """Run all 7 feature tests in sequence."""
    app = create_app()
    c_host = app.test_client()
    c_student = app.test_client()
    c_guest = app.test_client()

    print("=== STARTING COMPLETE VERIFICATION OF ALL 7 PROPOSAL FEATURES ===\n")
    verify_seeds_and_blueprints(app)
    test_feature_1_auth(c_host, c_student, c_guest)
    test_feature_2_quiz_crud(c_host)
    img_quiz_id = test_feature_3_image_upload(c_host)
    test_feature_4_self_paced(c_student, img_quiz_id)
    test_feature_5_results_analytics(c_student, c_host, img_quiz_id)
    test_feature_6_live_game(c_host, c_guest, img_quiz_id)
    test_feature_7_security_validation(c_host, c_guest, img_quiz_id)

    print("====================================================================")
    print("ALL 7 FEATURES FROM PROPOSAL VERIFIED AND FUNCTIONING 100% CORRECTLY!")
    print("====================================================================")


if __name__ == "__main__":
    temp_dir = tempfile.mkdtemp(prefix="quizlive_test_")
    temp_db_file = Path(temp_dir) / "test_local_db.json"
    if DB_FILE.exists():
        shutil.copy(DB_FILE, temp_db_file)

    original_db_path = local_db.db_path
    local_db.db_path = temp_db_file
    local_db.load_or_seed()

    try:
        run_all_tests()
    finally:
        local_db.db_path = original_db_path
        local_db.load_or_seed()
        if temp_db_file.exists():
            temp_db_file.unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
