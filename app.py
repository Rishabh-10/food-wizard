import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import auth
import db
import llm

load_dotenv(Path(__file__).parent / ".local.env", override=True)

st.set_page_config(page_title="Food Wizard", page_icon="🥗", layout="wide")
db.init_db()

# Env vars checked (in order) when no key is typed into the sidebar
ENV_KEYS = {
    llm.GEMINI: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    llm.CLAUDE: ("ANTHROPIC_API_KEY",),
}
RECIPE_CONTEXT_LIMIT = 50  # most recent recipes sent to the nutritionist as context
CHAT_CONTEXT_MESSAGES = 40  # most recent chat messages sent back to the model (kept even: user/assistant pairs)


def env_api_key(provider: str) -> str:
    return next((os.environ[name] for name in ENV_KEYS[provider] if os.environ.get(name)), "")


def render_recipe(recipe: dict, show_title: bool = True) -> None:
    if show_title:
        st.subheader(recipe["title"])
        st.caption(f"{recipe['cuisine'] or 'Any cuisine'} · made with {', '.join(recipe['input_ingredients'])}")

    cols = st.columns(6)
    cols[0].metric("Prep", f"{recipe['prep_time_minutes']} min")
    cols[1].metric("Servings", recipe["servings"])
    cols[2].metric("Calories", f"{recipe['calories_per_serving']} kcal")
    cols[3].metric("Protein", f"{recipe['protein_g']:g} g")
    cols[4].metric("Carbs", f"{recipe['carbs_g']:g} g")
    cols[5].metric("Fat", f"{recipe['fat_g']:g} g")
    st.caption("Nutrition is an AI estimate per serving.")

    left, right = st.columns([2, 3])
    with left:
        st.markdown("**Ingredients**")
        st.markdown("\n".join(f"- {item}" for item in recipe["ingredients_needed"]))
    with right:
        st.markdown("**Instructions**")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(recipe["instructions"], 1)))


def login_screen() -> None:
    st.title("🥗 Food Wizard")
    st.caption("Log in to see your recipes and chat with your nutritionist. Each account's data is private.")
    login_tab, signup_tab = st.tabs(["Log in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary"):
                user = auth.login(username, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                st.error("Incorrect username or password.")

    with signup_tab:
        with st.form("signup_form"):
            username = st.text_input("Username", help="3-32 characters: letters, numbers, '.', '_' or '-'")
            password = st.text_input("Password", type="password", help=f"At least {auth.MIN_PASSWORD_LENGTH} characters")
            confirm = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account", type="primary"):
                if password != confirm:
                    st.error("Passwords don't match.")
                else:
                    try:
                        st.session_state.user = auth.register(username, password)
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        st.rerun()


if "user" not in st.session_state:
    login_screen()
    st.stop()

user_id = st.session_state.user["id"]

# ---------- Sidebar: account, provider + API key ----------
with st.sidebar:
    st.markdown(f"Signed in as **{st.session_state.user['username']}**")
    if st.button("Log out"):
        st.session_state.clear()  # also drops API keys typed this session
        st.rerun()
    st.divider()

    st.header("⚙️ AI settings")
    provider = st.radio("Provider", [llm.GEMINI, llm.CLAUDE], horizontal=True)
    typed_key = st.text_input(
        f"{provider} API key",
        type="password",
        key=f"api_key_{provider}",
        placeholder="Leave blank to use .local.env",
    )
    api_key = typed_key or env_api_key(provider)
    model = st.text_input("Model", value=llm.DEFAULT_MODELS[provider], key=f"model_{provider}")

    if typed_key:
        st.success("Using the key entered above.")
    elif api_key:
        st.success("Using the key from .local.env.")
    else:
        st.warning(f"Add a {provider} API key to get started.")
    st.caption("Keys entered here live only in this browser session and are never written to disk.")


st.title("🥗 Food Wizard")
st.caption("Turn what's in your kitchen into recipes, and get nutrition advice based on what you actually cook.")

new_tab, history_tab, chat_tab = st.tabs(["🍳 New recipe", "📚 My recipes", "💬 Ask the nutritionist"])

# ---------- New recipe ----------
with new_tab:
    with st.form("recipe_form"):
        ingredients_text = st.text_input("Ingredients you have", placeholder="eggs, spinach, feta, olive oil")
        cuisine = st.text_input("Cuisine (optional)", placeholder="e.g. Mediterranean, Indian, Mexican").strip()
        submitted = st.form_submit_button("Create recipe", type="primary")

    if submitted:
        ingredients = [item.strip() for item in ingredients_text.split(",") if item.strip()]
        if not ingredients:
            st.error("Enter at least one ingredient, separated by commas.")
        elif not api_key:
            st.error(f"Add a {provider} API key in the sidebar first.")
        else:
            with st.spinner("Cooking up a recipe…"):
                try:
                    recipe = llm.create_recipe(provider, api_key, model, ingredients, cuisine or None)
                except Exception as e:
                    st.error(f"Couldn't create a recipe: {e}")
                else:
                    st.session_state.last_recipe_id = db.save_recipe(user_id, recipe.model_dump(), ingredients, provider)

    if "last_recipe_id" in st.session_state:
        last_recipe = db.get_recipe(user_id, st.session_state.last_recipe_id)
        if last_recipe:
            st.success("Saved to My recipes.")
            render_recipe(last_recipe)

# ---------- Previous recipes ----------
with history_tab:
    search = st.text_input("Search recipes", placeholder="Title, cuisine or ingredient").strip()
    recipes = db.list_recipes(user_id, search=search)

    if not recipes:
        st.info("No matching recipes." if search else "No recipes yet. Create one in the New recipe tab.")
    else:
        avg_kcal = sum(r["calories_per_serving"] for r in recipes) / len(recipes)
        avg_protein = sum(r["protein_g"] for r in recipes) / len(recipes)
        stats = st.columns(3)
        stats[0].metric("Recipes", len(recipes))
        stats[1].metric("Avg calories / serving", f"{avg_kcal:.0f} kcal")
        stats[2].metric("Avg protein / serving", f"{avg_protein:.0f} g")

        for r in recipes:
            label = f"{r['title']} · {r['cuisine'] or 'Any cuisine'} · {r['calories_per_serving']} kcal · {r['created_at'][:10]}"
            with st.expander(label):
                render_recipe(r, show_title=False)
                if st.button("Delete recipe", key=f"delete_{r['id']}"):
                    db.delete_recipe(user_id, r["id"])
                    st.rerun()

# ---------- Nutritionist chat ----------
with chat_tab:
    st.caption(
        "Ask about calories, macros, a calorie deficit, meal planning, or anything nutrition-related. "
        f"Answers draw on your {RECIPE_CONTEXT_LIMIT} most recent saved recipes."
    )
    history = db.list_chat_messages(user_id)

    chat_box = st.container(height=450)
    for m in history:
        chat_box.chat_message(m["role"]).markdown(m["content"])

    question = st.chat_input("e.g. Which of my recipes fit a 1,800 kcal deficit day?")
    if question:
        if not api_key:
            st.error(f"Add a {provider} API key in the sidebar first.")
        else:
            conversation = history[-CHAT_CONTEXT_MESSAGES:] + [{"role": "user", "content": question}]
            chat_box.chat_message("user").markdown(question)
            with chat_box.chat_message("assistant"):
                try:
                    reply = st.write_stream(
                        llm.stream_chat(
                            provider, api_key, model, conversation,
                            db.list_recipes(user_id, limit=RECIPE_CONTEXT_LIMIT),
                        )
                    )
                except Exception as e:
                    st.error(f"Couldn't get a reply: {e}")
                else:
                    # Save the question only once it has an answer, so stored history stays in user/assistant pairs
                    new_messages = [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
                    db.add_chat_messages(user_id, new_messages)
                    history += new_messages

    if history and st.button("Clear chat"):
        db.clear_chat(user_id)
        st.rerun()
