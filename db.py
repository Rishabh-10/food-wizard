import json
import os
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

DB_PATH = Path(__file__).parent / "recipes.db"

# Columns stored as JSON-encoded lists
JSON_COLUMNS = ("input_ingredients", "ingredients_needed", "instructions")

metadata = sa.MetaData()

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    # Google's permanent account ID (OIDC "sub"); email and name can change, this can't
    sa.Column("google_sub", sa.String(255), nullable=False, unique=True),
    sa.Column("email", sa.String(320)),
    sa.Column("name", sa.String(255)),
    sa.Column("created_at", sa.String(19), nullable=False),
)

recipes = sa.Table(
    "recipes",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("created_at", sa.String(19), nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("cuisine", sa.Text),
    sa.Column("input_ingredients", sa.Text, nullable=False),
    sa.Column("ingredients_needed", sa.Text, nullable=False),
    sa.Column("instructions", sa.Text, nullable=False),
    sa.Column("prep_time_minutes", sa.Integer),
    sa.Column("servings", sa.Integer),
    sa.Column("calories_per_serving", sa.Integer),
    sa.Column("protein_g", sa.Float),
    sa.Column("carbs_g", sa.Float),
    sa.Column("fat_g", sa.Float),
    sa.Column("provider", sa.Text),
)

chat_messages = sa.Table(
    "chat_messages",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    sa.Column("role", sa.String(9), sa.CheckConstraint("role IN ('user', 'assistant')"), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("created_at", sa.String(19), nullable=False),
)


class LegacyDatabaseError(RuntimeError):
    """The database was created by the old username/password version of the app."""


def database_url(url: str | None = None) -> str:
    """Postgres when DATABASE_URL is set (e.g. a Neon connection string), else the local SQLite file."""
    url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}"
    # Neon and most hosts hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver for both
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


_engine: sa.Engine | None = None


def _enable_sqlite_foreign_keys(dbapi_conn, _record) -> None:
    dbapi_conn.execute("PRAGMA foreign_keys = ON")


def configure(url: str | None = None) -> sa.Engine:
    """(Re)create the engine. Called by init_db; tests call it to point at a different database."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = sa.create_engine(database_url(url), pool_pre_ping=True)  # pre-ping: Neon drops idle connections
    if _engine.dialect.name == "sqlite":
        sa.event.listen(_engine, "connect", _enable_sqlite_foreign_keys)
    return _engine


def _get_engine() -> sa.Engine:
    return _engine or configure()


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _row_to_dict(row: sa.Row) -> dict:
    recipe = dict(row._mapping)
    for col in JSON_COLUMNS:
        recipe[col] = json.loads(recipe[col])
    return recipe


def init_db(url: str | None = None) -> None:
    engine = configure(url)
    existing = sa.inspect(engine)
    if existing.has_table("users") and "google_sub" not in {c["name"] for c in existing.get_columns("users")}:
        raise LegacyDatabaseError(
            "This database was created by the old username/password version of Food Wizard. "
            "Delete it (or point DATABASE_URL at a new database) to start fresh with Google sign-in."
        )
    metadata.create_all(engine)


# ---------- Users ----------

def get_or_create_user(google_sub: str, email: str | None, name: str | None) -> int:
    """Return the id of the account for this Google account, creating it on first sign-in."""
    with _get_engine().begin() as conn:
        user_id = conn.scalar(sa.select(users.c.id).where(users.c.google_sub == google_sub))
        if user_id is not None:
            conn.execute(sa.update(users).where(users.c.id == user_id).values(email=email, name=name))
            return user_id
    try:
        with _get_engine().begin() as conn:
            return conn.execute(
                sa.insert(users).values(google_sub=google_sub, email=email, name=name, created_at=_now())
            ).inserted_primary_key[0]
    except sa.exc.IntegrityError:
        # The same person signed in from two tabs at once and the other one created the row first
        with _get_engine().connect() as conn:
            return conn.scalar(sa.select(users.c.id).where(users.c.google_sub == google_sub))


# ---------- Recipes (always scoped to a user) ----------

def save_recipe(user_id: int, recipe: dict, input_ingredients: list[str], provider: str) -> int:
    """Store a generated recipe (a Recipe.model_dump()) and return its id."""
    with _get_engine().begin() as conn:
        return conn.execute(
            sa.insert(recipes).values(
                user_id=user_id,
                created_at=_now(),
                title=recipe["title"],
                cuisine=recipe["cuisine"],
                input_ingredients=json.dumps(input_ingredients, ensure_ascii=False),
                ingredients_needed=json.dumps(recipe["ingredients_needed"], ensure_ascii=False),
                instructions=json.dumps(recipe["instructions"], ensure_ascii=False),
                prep_time_minutes=recipe["prep_time_minutes"],
                servings=recipe["servings"],
                calories_per_serving=recipe["calories_per_serving"],
                protein_g=recipe["protein_g"],
                carbs_g=recipe["carbs_g"],
                fat_g=recipe["fat_g"],
                provider=provider,
            )
        ).inserted_primary_key[0]


def get_recipe(user_id: int, recipe_id: int) -> dict | None:
    with _get_engine().connect() as conn:
        row = conn.execute(
            sa.select(recipes).where(recipes.c.id == recipe_id, recipes.c.user_id == user_id)
        ).first()
    return _row_to_dict(row) if row else None


def list_recipes(user_id: int, search: str = "", limit: int | None = None) -> list[dict]:
    """Newest first, optionally filtered by title, cuisine or ingredient (case-insensitive)."""
    query = sa.select(recipes).where(recipes.c.user_id == user_id).order_by(recipes.c.id.desc())
    if search:
        pattern = f"%{search}%"
        query = query.where(
            sa.or_(
                recipes.c.title.ilike(pattern),
                recipes.c.cuisine.ilike(pattern),
                recipes.c.ingredients_needed.ilike(pattern),
            )
        )
    if limit:
        query = query.limit(limit)
    with _get_engine().connect() as conn:
        rows = conn.execute(query).all()
    return [_row_to_dict(row) for row in rows]


def delete_recipe(user_id: int, recipe_id: int) -> None:
    with _get_engine().begin() as conn:
        conn.execute(sa.delete(recipes).where(recipes.c.id == recipe_id, recipes.c.user_id == user_id))


# ---------- Chat history (always scoped to a user) ----------

def list_chat_messages(user_id: int) -> list[dict]:
    """Oldest first, as [{"role": ..., "content": ...}] ready to send to the LLM."""
    with _get_engine().connect() as conn:
        rows = conn.execute(
            sa.select(chat_messages.c.role, chat_messages.c.content)
            .where(chat_messages.c.user_id == user_id)
            .order_by(chat_messages.c.id)
        ).all()
    return [dict(row._mapping) for row in rows]


def add_chat_messages(user_id: int, messages: list[dict]) -> None:
    with _get_engine().begin() as conn:
        conn.execute(
            sa.insert(chat_messages),
            [{"user_id": user_id, "role": m["role"], "content": m["content"], "created_at": _now()} for m in messages],
        )


def clear_chat(user_id: int) -> None:
    with _get_engine().begin() as conn:
        conn.execute(sa.delete(chat_messages).where(chat_messages.c.user_id == user_id))
