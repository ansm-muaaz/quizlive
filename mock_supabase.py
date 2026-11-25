"""
QuizLive — Local Mock Supabase Client.

Enables QuizLive to run 100% locally with zero external dependencies (no Supabase account
or Google Cloud OAuth setup required).  Supports local persistence via `local_db.json`,
local image uploads in `static/uploads/`, and simulated authentication.
"""

import copy
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from seeds import DATABASE_STATE

logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "local_db.json"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"


class MockUser:
    """Simulates a Supabase Auth user object."""

    def __init__(self, user_id: str, email: str, name: str, role: str = "participant"):
        self.id = user_id
        self.email = email
        self.user_metadata = {"full_name": name, "name": name}
        self.role = role


class MockResponse:
    """Simulates PostgREST query execution response."""

    def __init__(self, data=None, count=None):
        self.data = data if data is not None else []
        self.count = count if count is not None else len(self.data)


class MockTableQuery:
    """Simulates Supabase Python client fluent query builder."""

    def __init__(self, db: "LocalDatabase", table_name: str):
        self.db = db
        self.table_name = table_name
        self.op = "select"
        self.select_columns = "*"
        self.count_mode = None
        self.filters = []  # tuples: (col, op, val)
        self.order_col = None
        self.order_desc = False
        self.limit_n = None
        self.mutation_data = None

    def select(self, columns="*", count=None):
        self.op = "select"
        self.select_columns = columns
        self.count_mode = count
        return self

    def insert(self, data):
        self.op = "insert"
        self.mutation_data = copy.deepcopy(data)
        return self

    def update(self, data):
        self.op = "update"
        self.mutation_data = copy.deepcopy(data)
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column: str, value):
        self.filters.append((column, "eq", value))
        return self

    def neq(self, column: str, value):
        self.filters.append((column, "neq", value))
        return self

    def order(self, column: str, desc: bool = False):
        self.order_col = column
        self.order_desc = desc
        return self

    def limit(self, n: int):
        self.limit_n = n
        return self

    def _matches(self, row: dict) -> bool:
        for col, op, val in self.filters:
            row_val = row.get(col)
            if op == "eq":
                if str(row_val) != str(val):
                    return False
            elif op == "neq":
                if str(row_val) == str(val):
                    return False
        return True

    def _execute_insert(self, table: list[dict]) -> MockResponse:
        inserted = []
        items = (
            self.mutation_data
            if isinstance(self.mutation_data, list)
            else [self.mutation_data]
        )
        for item in items:
            row = copy.deepcopy(item)
            if "id" not in row:
                row["id"] = self.db.next_id(self.table_name)
            if "created_at" not in row and self.table_name == "quizzes":
                row["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if "submitted_at" not in row and self.table_name == "results":
                row["submitted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            table.append(row)
            inserted.append(row)
        self.db.save()
        return MockResponse(data=inserted, count=len(inserted))

    def _execute_update(self, table: list[dict]) -> MockResponse:
        updated = []
        for row in table:
            if self._matches(row):
                for k, v in self.mutation_data.items():
                    row[k] = v
                updated.append(copy.deepcopy(row))
        self.db.save()
        return MockResponse(data=updated, count=len(updated))

    def _execute_delete(self, table: list[dict]) -> MockResponse:
        deleted = []
        kept = []
        for row in table:
            if self._matches(row):
                deleted.append(copy.deepcopy(row))
            else:
                kept.append(row)
        self.db.tables[self.table_name] = kept

        # Cascade delete matching PostgreSQL foreign keys
        if self.table_name == "quizzes":
            for d in deleted:
                qid = d.get("id")
                self.db.tables["questions"] = [q for q in self.db.tables.get("questions", []) if q.get("quiz_id") != qid]
                self.db.tables["results"] = [r for r in self.db.tables.get("results", []) if r.get("quiz_id") != qid]
                self.db.tables["game_sessions"] = [s for s in self.db.tables.get("game_sessions", []) if s.get("quiz_id") != qid]

        self.db.save()
        return MockResponse(data=deleted, count=len(deleted))

    def _execute_select(self, table: list[dict]) -> MockResponse:
        results = [copy.deepcopy(r) for r in table if self._matches(r)]

        # Sorting
        if self.order_col:
            results.sort(
                key=lambda x: (x.get(self.order_col) is None, x.get(self.order_col)),
                reverse=self.order_desc,
            )

        if self.limit_n is not None:
            results = results[: self.limit_n]

        # Handle relation joins used in QuizLive
        for r in results:
            self.db.resolve_relations(self.table_name, r, self.select_columns)

        count_val = len(results) if self.count_mode == "exact" else None
        return MockResponse(data=results, count=count_val)

    def execute(self) -> MockResponse:
        table = self.db.get_table(self.table_name)
        if self.op == "insert":
            return self._execute_insert(table)
        elif self.op == "update":
            return self._execute_update(table)
        elif self.op == "delete":
            return self._execute_delete(table)
        return self._execute_select(table)


class LocalStorageBucket:
    """Simulates Supabase Storage bucket operations using local static/uploads/."""

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def upload(self, path: str, file, file_options=None):
        filename = Path(path).name
        target = UPLOAD_DIR / filename
        if isinstance(file, bytes):
            with open(target, "wb") as f:
                f.write(file)
        elif hasattr(file, "read"):
            with open(target, "wb") as f:
                f.write(file.read())
        return {"Key": filename}

    def get_public_url(self, path: str) -> str:
        filename = Path(path).name
        return f"/static/uploads/{filename}"

    def remove(self, filenames: list[str]):
        for fname in filenames:
            target = UPLOAD_DIR / Path(fname).name
            if target.exists():
                try:
                    target.unlink()
                except Exception as e:
                    logger.warning("Failed to remove upload file %s: %s", fname, e)
        return True


class MockStorage:
    def from_(self, bucket_name: str) -> LocalStorageBucket:
        return LocalStorageBucket(bucket_name)


class OAuthURL:
    def __init__(self, url: str):
        self.url = url


class AuthUserResponse:
    def __init__(self, user):
        self.user = user


class MockAuth:
    """Simulates Supabase Auth operations for local demo mode."""

    def __init__(self, db: "LocalDatabase"):
        self.db = db

    def sign_in_with_oauth(self, options: dict) -> OAuthURL:
        return OAuthURL("/demo-login")

    def get_user(self, access_token: str) -> AuthUserResponse | MockResponse:
        # access_token format in demo: "demo-token:<user_id>"
        if not access_token:
            return MockResponse(data=None)

        user_id = access_token.replace("demo-token:", "").strip()
        profiles = self.db.get_table("profiles")
        for p in profiles:
            if str(p.get("user_id")) == user_id:
                user = MockUser(
                    user_id=p["user_id"],
                    email=p["email"],
                    name=p["name"],
                    role=p.get("role", "participant"),
                )
                return AuthUserResponse(user)

        # Fallback default host
        fallback_user = MockUser(
            user_id="host-1",
            email="host@quizlive.edu",
            name="Dr. Sarah Jenkins",
            role="host",
        )
        return AuthUserResponse(fallback_user)


class LocalDatabase:
    """In-memory + JSON-persisted relational database simulating Supabase."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_FILE
        self.tables = {
            "profiles": [],
            "quizzes": [],
            "questions": [],
            "results": [],
            "game_sessions": [],
            "participants": [],
            "answers": [],
        }
        self.load_or_seed()

    def get_table(self, name: str) -> list[dict]:
        if name not in self.tables:
            self.tables[name] = []
        return self.tables[name]

    def next_id(self, table_name: str) -> int:
        table = self.get_table(table_name)
        existing_ids = [r["id"] for r in table if isinstance(r.get("id"), int)]
        return max(existing_ids, default=0) + 1

    def resolve_relations(self, table_name: str, row: dict, select_columns: str):
        """Resolves join lookups such as profiles(name, email), quizzes(title), etc."""
        # 1. quizzes -> profiles(name), results(id), questions(id)
        if table_name == "quizzes":
            # profiles
            if "profiles" in select_columns:
                host_id = row.get("host_id")
                profile = next(
                    (p for p in self.tables["profiles"] if str(p.get("user_id")) == str(host_id)),
                    None,
                )
                if profile:
                    row["profiles"] = {"name": profile.get("name"), "email": profile.get("email")}

            # results
            if "results" in select_columns:
                q_id = row.get("id")
                row["results"] = [
                    {"id": r["id"], "score": r.get("score"), "total": r.get("total")}
                    for r in self.tables["results"]
                    if r.get("quiz_id") == q_id
                ]

            # questions
            if "questions" in select_columns:
                q_id = row.get("id")
                row["questions"] = [
                    {"id": q["id"]}
                    for q in self.tables["questions"]
                    if q.get("quiz_id") == q_id
                ]

            # game_sessions
            if "game_sessions" in select_columns:
                q_id = row.get("id")
                row["game_sessions"] = [
                    {"id": s["id"]}
                    for s in self.tables["game_sessions"]
                    if s.get("quiz_id") == q_id
                ]

        # 2. results -> profiles(name, email), quizzes(title)
        elif table_name == "results":
            if "profiles" in select_columns:
                u_id = row.get("user_id")
                profile = next(
                    (p for p in self.tables["profiles"] if str(p.get("user_id")) == str(u_id)),
                    None,
                )
                if profile:
                    row["profiles"] = {"name": profile.get("name"), "email": profile.get("email")}
            if "quizzes" in select_columns:
                q_id = row.get("quiz_id")
                quiz = next(
                    (q for q in self.tables["quizzes"] if q.get("id") == q_id),
                    None,
                )
                if quiz:
                    row["quizzes"] = {"title": quiz.get("title")}

        # 3. questions -> quizzes!inner(host_id)
        elif table_name == "questions":
            if "quizzes" in select_columns:
                q_id = row.get("quiz_id")
                quiz = next(
                    (q for q in self.tables["quizzes"] if q.get("id") == q_id),
                    None,
                )
                if quiz:
                    row["quizzes"] = {"host_id": quiz.get("host_id")}

        # 4. game_sessions -> participants
        elif table_name == "game_sessions":
            if "participants" in select_columns:
                s_id = row.get("id")
                row["participants"] = [
                    {"id": p["id"], "nickname": p.get("nickname"), "score": p.get("score", 0)}
                    for p in self.tables["participants"]
                    if p.get("session_id") == s_id
                ]

    def save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.tables, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("[LocalDatabase] Error saving DB: %s", e)

    def load_or_seed(self):
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in self.tables:
                        if k in data:
                            self.tables[k] = data[k]
                return
            except Exception as e:
                logger.warning("Error loading %s: %s. Using default seed.", self.db_path, e)

        # Seed with initial rich demonstration data
        self.seed_defaults()
        self.save()

    def seed_defaults(self):
        """Pre-seeds demonstration data for immediate zero-config demoing."""
        for k, v in DATABASE_STATE.items():
            self.tables[k] = copy.deepcopy(v)


class MockSupabaseClient:
    """Mock Supabase client providing .table(), .storage, and .auth interfaces."""

    def __init__(self, db: LocalDatabase):
        self.db = db
        self.storage = MockStorage()
        self.auth = MockAuth(db)

    def table(self, table_name: str) -> MockTableQuery:
        return MockTableQuery(self.db, table_name)


# Global singleton instance for local demo mode
local_db = LocalDatabase()
mock_supabase_client = MockSupabaseClient(local_db)
