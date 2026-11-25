"""
QuizLive — Authentication helpers and decorators.
"""

from functools import wraps
from typing import Any, Callable

from flask import session, redirect, url_for, flash, g
from supabase_client import supabase, supabase_admin


def get_current_user() -> dict[str, Any] | None:
    """Return the current authenticated user dict or None.

    Checks for an access_token in the Flask session, verifies it against
    Supabase Auth, and caches the result on Flask's ``g`` object so
    repeated calls within the same request are free.
    """
    if hasattr(g, "_current_user"):
        return g._current_user

    access_token = session.get("access_token")
    if not access_token:
        g._current_user = None
        return None

    try:
        # Verify token with Supabase Auth
        user_response = supabase.auth.get_user(access_token)
        user = user_response.user
        if user is None:
            g._current_user = None
            return None

        # Fetch profile from profiles table
        profile_resp = (
            supabase_admin.table("profiles")
            .select("*")
            .eq("user_id", user.id)
            .execute()
        )
        profile = profile_resp.data[0] if profile_resp.data else None

        # Auto-create profile if missing for authenticated Supabase user
        if not profile:
            full_name = (
                user.user_metadata.get("full_name")
                or user.user_metadata.get("name")
                or user.email
            )
            try:
                ins_resp = (
                    supabase_admin.table("profiles")
                    .insert({
                        "user_id": user.id,
                        "email": user.email,
                        "name": full_name,
                        "role": "participant",
                    })
                    .execute()
                )
                profile = ins_resp.data[0] if ins_resp.data else {"role": "participant", "name": full_name}
            except Exception:
                profile = {"role": "participant", "name": full_name}

        user_data = {
            "id": user.id,
            "email": user.email,
            "profile": profile,
            "role": profile.get("role", "participant"),
            "name": profile.get("name") or user.email,
        }
        g._current_user = user_data
        return user_data

    except Exception:
        # Token invalid / expired — clear session
        session.pop("access_token", None)
        session.pop("refresh_token", None)
        session.pop("user", None)
        g._current_user = None
        return None


def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: redirect unauthenticated users to the login page."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        user = get_current_user()
        if user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def host_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: require the user to be authenticated **and** have the
    ``host`` role.  Stacks on top of authentication check."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        user = get_current_user()
        if user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if user.get("role") != "host":
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)

    return decorated
