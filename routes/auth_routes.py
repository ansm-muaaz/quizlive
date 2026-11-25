"""
QuizLive — Authentication routes (Google OAuth via Supabase Auth + Local Demo Mode).
"""

import logging
from flask import (
    Blueprint,
    redirect,
    url_for,
    session,
    request,
    render_template,
    flash,
    g,
)
from auth import get_current_user
from config import Config
from supabase_client import supabase, supabase_admin, IS_DEMO_MODE

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login")
def login():
    """Sign-in entry point with explicit role selection.
    
    If `role` is provided (?role=host or ?role=participant), the chosen role
    is remembered in the session and the authentication flow starts immediately.
    Otherwise, renders the role selection page.
    """
    role = request.args.get("role")

    if role in ("host", "participant"):
        session["auth_intent_role"] = role

        if IS_DEMO_MODE:
            # One-click demo sign-in with chosen role
            user_id = "host-1" if role == "host" else "student-1"
            email = "host@quizlive.edu" if role == "host" else "alex@quizlive.edu"
            name = "Dr. Sarah Jenkins" if role == "host" else "Alex Chen"

            prof_resp = supabase_admin.table("profiles").select("*").eq("user_id", user_id).execute()
            if not prof_resp.data:
                supabase_admin.table("profiles").insert(
                    {"user_id": user_id, "email": email, "name": name, "role": role}
                ).execute()
            else:
                supabase_admin.table("profiles").update({"role": role, "name": name}).eq("user_id", user_id).execute()

            session["access_token"] = f"demo-token:{user_id}"
            session["user"] = {
                "id": user_id,
                "email": email,
                "name": name,
                "role": role,
            }
            if hasattr(g, "_current_user"):
                delattr(g, "_current_user")
            flash(f"Signed in as {name} ({role.title()}).", "success")
            return redirect(url_for("dashboard.dashboard"))

        # Supabase Cloud OAuth flow
        try:
            resp = supabase.auth.sign_in_with_oauth(
                {
                    "provider": "google",
                    "options": {
                        "redirect_to": Config.SITE_URL + "/callback",
                    },
                }
            )
            # Store PKCE code_verifier in session so code exchange works across server threads
            stored_verifier = getattr(supabase.auth, "_storage", None)
            if stored_verifier:
                verifier_val = stored_verifier.get_item(f"{supabase.auth._storage_key}-code-verifier")
                if verifier_val:
                    session["code_verifier"] = verifier_val
            return redirect(resp.url)
        except Exception as e:
            flash(f"Could not start OAuth login: {e}. Switching to Local Demo Login.", "warning")
            return redirect(url_for("auth.demo_login"))

    return render_template("login.html", is_demo=IS_DEMO_MODE)


@auth_bp.route("/demo-login", methods=["GET", "POST"])
def demo_login():
    """Instant one-click demo login without requiring external Supabase or Google OAuth."""
    if request.method == "POST":
        account = request.form.get("account", "host")

        if account == "host":
            user_id = "host-1"
            email = "host@quizlive.edu"
            name = "Dr. Sarah Jenkins"
            role = "host"
        elif account == "participant":
            user_id = "student-1"
            email = "alex@quizlive.edu"
            name = "Alex Chen"
            role = "participant"
        else:
            # Custom user
            custom_name = request.form.get("custom_name", "Demo User").strip() or "Demo User"
            custom_role = request.form.get("custom_role", "participant")
            user_id = f"custom-{abs(hash(custom_name)) % 10000}"
            email = f"{custom_name.lower().replace(' ', '')}@demo.local"
            name = custom_name
            role = "host" if custom_role == "host" else "participant"

        # Ensure profile exists in local DB and reflects chosen role
        prof_resp = supabase_admin.table("profiles").select("*").eq("user_id", user_id).execute()
        if not prof_resp.data:
            supabase_admin.table("profiles").insert(
                {"user_id": user_id, "email": email, "name": name, "role": role}
            ).execute()
        else:
            supabase_admin.table("profiles").update({"role": role, "name": name}).eq("user_id", user_id).execute()

        # Set Flask session
        session["access_token"] = f"demo-token:{user_id}"
        session["user"] = {
            "id": user_id,
            "email": email,
            "name": name,
            "role": role,
        }
        flash(f"Signed in as {name} ({role.title()}).", "success")
        return redirect(url_for("dashboard.dashboard"))

    return render_template("demo_login.html")


@auth_bp.route("/switch-role/<role>")
def switch_role(role):
    """Switch user role between host and participant in both Cloud and Demo modes."""
    if role not in ("host", "participant"):
        role = "participant"

    user = get_current_user()
    if not user:
        if IS_DEMO_MODE:
            return redirect(url_for("auth.demo_login"))
        return redirect(url_for("auth.login"))

    user_id = user["id"]
    name = user.get("name") or user.get("email") or "User"
    email = user.get("email") or ""

    try:
        # Update role in Supabase database
        supabase_admin.table("profiles").update({"role": role}).eq("user_id", user_id).execute()
    except Exception as exc:
        flash(f"Could not update database role: {exc}", "warning")

    # Keep Flask session in sync
    if "user" not in session or not isinstance(session["user"], dict):
        session["user"] = {}
    session["user"]["role"] = role
    session["user"]["id"] = user_id
    session["user"]["name"] = name
    session["user"]["email"] = email

    # Clear cached user on request context so subsequent calls re-evaluate
    if hasattr(g, "_current_user"):
        delattr(g, "_current_user")

    flash(f"Switched role to {role.title()} mode.", "info")
    return redirect(url_for("dashboard.dashboard"))


@auth_bp.route("/callback")
def callback():
    """Handle OAuth callback:
    1. If `error` is present, display error and redirect.
    2. If `code` is present (Supabase PKCE flow), exchange it server-side.
    3. If neither, render callback.html to read hash fragment tokens (implicit flow fallback).
    """
    error = request.args.get("error_description") or request.args.get("error")
    if error:
        flash(f"Sign in failed: {error}", "danger")
        return redirect(url_for("main.index"))

    code = request.args.get("code")
    if code:
        code_verifier = session.pop("code_verifier", None)
        params = {"auth_code": code}
        if code_verifier:
            params["code_verifier"] = code_verifier

        try:
            auth_resp = supabase.auth.exchange_code_for_session(params)
            if not auth_resp.user or not auth_resp.session:
                flash("Sign in failed — could not establish user session.", "danger")
                return redirect(url_for("main.index"))

            user = auth_resp.user
            session["access_token"] = auth_resp.session.access_token
            session["refresh_token"] = auth_resp.session.refresh_token
            session["user"] = {
                "id": user.id,
                "email": user.email,
            }

            intended_role = session.pop("auth_intent_role", None)

            # Upsert profile in Supabase database
            profile_resp = (
                supabase_admin.table("profiles")
                .select("*")
                .eq("user_id", user.id)
                .execute()
            )
            name = (
                user.user_metadata.get("full_name")
                or user.user_metadata.get("name")
                or user.email
            )
            if not profile_resp.data:
                role = intended_role if intended_role in ("host", "participant") else "participant"
                supabase_admin.table("profiles").insert(
                    {
                        "user_id": user.id,
                        "email": user.email,
                        "name": name,
                        "role": role,
                    }
                ).execute()
            else:
                if intended_role in ("host", "participant"):
                    role = intended_role
                    try:
                        supabase_admin.table("profiles").update({"role": role, "name": name}).eq("user_id", user.id).execute()
                    except Exception as exc:
                        logger.warning("Could not update profile role in callback: %s", exc)
                else:
                    role = profile_resp.data[0].get("role") or "participant"
                    name = profile_resp.data[0].get("name") or name

            session["user"]["role"] = role
            session["user"]["name"] = name
            if hasattr(g, "_current_user"):
                delattr(g, "_current_user")
            flash(f"Signed in as {name} ({role.title()}).", "success")
            return redirect(url_for("dashboard.dashboard"))

        except Exception as exc:
            flash(f"Authentication exchange error: {exc}", "danger")
            return redirect(url_for("main.index"))

    return render_template("callback.html")


@auth_bp.route("/callback/process", methods=["POST"])
def callback_process():
    """Receive access_token + refresh_token from the client-side JS,
    store them in the session, and ensure a profile row exists."""
    data = request.get_json(silent=True) or {}
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token:
        flash("Login failed — no token received.", "danger")
        return {"redirect": url_for("main.index")}, 400

    try:
        # Verify token
        user_response = supabase.auth.get_user(access_token)
        user = user_response.user
        if user is None:
            flash("Login failed — invalid token.", "danger")
            return {"redirect": url_for("main.index")}, 401

        # Store in session
        session["access_token"] = access_token
        session["refresh_token"] = refresh_token
        session["user"] = {
            "id": user.id,
            "email": user.email,
        }

        intended_role = session.pop("auth_intent_role", None)

        # Upsert profile (use service-role client to bypass RLS)
        profile_resp = (
            supabase_admin.table("profiles")
            .select("*")
            .eq("user_id", user.id)
            .execute()
        )
        name = (
            user.user_metadata.get("full_name")
            or user.user_metadata.get("name")
            or user.email
        )

        if not profile_resp.data:
            role = intended_role if intended_role in ("host", "participant") else "participant"
            supabase_admin.table("profiles").insert(
                {
                    "user_id": user.id,
                    "email": user.email,
                    "name": name,
                    "role": role,
                }
            ).execute()
        else:
            if intended_role in ("host", "participant"):
                role = intended_role
                try:
                    supabase_admin.table("profiles").update({"role": role, "name": name}).eq("user_id", user.id).execute()
                except Exception as exc:
                    logger.warning("Could not update profile role in callback_process: %s", exc)
            else:
                role = profile_resp.data[0]["role"]
                name = profile_resp.data[0].get("name") or name

        session["user"]["role"] = role
        session["user"]["name"] = name
        if hasattr(g, "_current_user"):
            delattr(g, "_current_user")

        # Redirect based on role
        dest = url_for("dashboard.dashboard")
        return {"redirect": dest}, 200

    except Exception as e:
        flash(f"Login error: {e}", "danger")
        return {"redirect": url_for("main.index")}, 500


@auth_bp.route("/logout")
def logout():
    """Clear session and redirect to home."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))
