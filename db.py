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
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    recipe = dict(row)
    for col in JSON_COLUMNS:
        recipe[col] = json.loads(recipe[col])
    return recipe


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recipes (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
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
            )
            """
        )


def save_recipe(recipe: dict, input_ingredients: list[str], provider: str) -> int:
    """Store a generated recipe (a Recipe.model_dump()) and return its id."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            """
            INSERT INTO recipes (
                created_at, title, cuisine, input_ingredients, ingredients_needed,
                instructions, prep_time_minutes, servings, calories_per_serving,
                protein_g, carbs_g, fat_g, provider
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(sep=" ", timespec="seconds"),
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


def get_recipe(recipe_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_recipes(search: str = "", limit: int | None = None) -> list[dict]:
    """Newest first, optionally filtered by title, cuisine or ingredient."""
    query = "SELECT * FROM recipes"
    params: list = []
    if search:
        query += " WHERE title LIKE ? OR cuisine LIKE ? OR ingredients_needed LIKE ?"
        params += [f"%{search}%"] * 3
    query += " ORDER BY id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def delete_recipe(recipe_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
