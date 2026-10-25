import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "recipes.db"

# Columns stored as JSON-encoded lists
JSON_COLUMNS = ("input_ingredients", "ingredients_needed", "instructions")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> dict:
    recipe = dict(row)
    for col in JSON_COLUMNS:
        recipe[col] = json.loads(recipe[col])
    return recipe


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recipes (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER REFERENCES users(id) ON DELETE CASCADE,
                created_at           TEXT NOT NULL,
                title                TEXT NOT NULL,
                cuisine              TEXT,
                input_ingredients    TEXT NOT NULL,
                ingredients_needed   TEXT NOT NULL,
                instructions         TEXT NOT NULL,
                prep_time_minutes    INTEGER,
                servings             INTEGER,
                calories_per_serving INTEGER,
                protein_g            REAL,
                carbs_g              REAL,
                fat_g                REAL,
                provider             TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Migrate databases created before accounts existed
        recipe_columns = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
        if "user_id" not in recipe_columns:
            conn.execute("ALTER TABLE recipes ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_recipes_user ON recipes(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_user ON chat_messages(user_id)")


# ---------- Users ----------

def create_user(username: str, password_hash: str) -> int | None:
    """Return the new user's id, or None if the username is taken."""
    with closing(_connect()) as conn, conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, _now()),
            )
        except sqlite3.IntegrityError:
            return None
        # Recipes saved before accounts existed belong to whoever set the app up: the first account
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1:
            conn.execute("UPDATE recipes SET user_id = ? WHERE user_id IS NULL", (cur.lastrowid,))
        return cur.lastrowid


def get_user(username: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


# ---------- Recipes (always scoped to a user) ----------

def save_recipe(user_id: int, recipe: dict, input_ingredients: list[str], provider: str) -> int:
    """Store a generated recipe (a Recipe.model_dump()) and return its id."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            """
            INSERT INTO recipes (
                user_id, created_at, title, cuisine, input_ingredients, ingredients_needed,
                instructions, prep_time_minutes, servings, calories_per_serving,
                protein_g, carbs_g, fat_g, provider
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                _now(),
                recipe["title"],
                recipe["cuisine"],
                json.dumps(input_ingredients),
                json.dumps(recipe["ingredients_needed"]),
                json.dumps(recipe["instructions"]),
                recipe["prep_time_minutes"],
                recipe["servings"],
                recipe["calories_per_serving"],
                recipe["protein_g"],
                recipe["carbs_g"],
                recipe["fat_g"],
                provider,
            ),
        )
        return cur.lastrowid


def get_recipe(user_id: int, recipe_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM recipes WHERE id = ? AND user_id = ?", (recipe_id, user_id)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_recipes(user_id: int, search: str = "", limit: int | None = None) -> list[dict]:
    """Newest first, optionally filtered by title, cuisine or ingredient."""
    query = "SELECT * FROM recipes WHERE user_id = ?"
    params: list = [user_id]
    if search:
        query += " AND (title LIKE ? OR cuisine LIKE ? OR ingredients_needed LIKE ?)"
        params += [f"%{search}%"] * 3
    query += " ORDER BY id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def delete_recipe(user_id: int, recipe_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM recipes WHERE id = ? AND user_id = ?", (recipe_id, user_id))


# ---------- Chat history (always scoped to a user) ----------

def list_chat_messages(user_id: int) -> list[dict]:
    """Oldest first, as [{"role": ..., "content": ...}] ready to send to the LLM."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_messages WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def add_chat_messages(user_id: int, messages: list[dict]) -> None:
    with closing(_connect()) as conn, conn:
        conn.executemany(
            "INSERT INTO chat_messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            [(user_id, m["role"], m["content"], _now()) for m in messages],
        )


def clear_chat(user_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
