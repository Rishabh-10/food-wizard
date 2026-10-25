# 🥗 Food Wizard

A Streamlit app that acts as your personal AI nutritionist. Tell it what ingredients you have, and it generates a recipe with estimated nutrition, saves it to a local SQLite database, and answers your nutrition questions (calorie deficit, macros, meal ideas) using the recipes you've actually cooked.

Works with **Google Gemini** or **Anthropic Claude**: bring your own API key for either.

## Features

- **Recipe generator**: enter ingredients (and optionally a cuisine) to get a full recipe with measurements, steps, prep time, servings, and estimated calories/protein/carbs/fat per serving.
- **Recipe history**: every recipe is saved to `recipes.db` (SQLite). Search by title, cuisine, or ingredient; see average calories and protein; delete recipes you don't want.
- **Nutritionist chat**: ask questions like *"Which of my recipes fit a 1,800 kcal day?"* or *"How can I get more protein from what I usually cook?"*. Answers are personalised using your saved recipes.
- **Provider choice**: switch between Gemini and Claude in the sidebar and pick the model.

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone <repo-url>
cd food-wizard
uv sync
uv run streamlit run app.py
```

The app opens at http://localhost:8501.

### API keys

You need a key for at least one provider:

- Gemini: https://aistudio.google.com/apikey
- Claude: https://console.anthropic.com/settings/keys

Either paste the key into the app's sidebar (kept only for the current browser session, never written to disk), or put it in a `.local.env` file so you don't have to re-enter it:

```bash
cp .local.env.example .local.env
```

```env
GEMINI_API_KEY=your-gemini-key
ANTHROPIC_API_KEY=your-claude-key
```

A key typed into the sidebar takes precedence over `.local.env`. `GOOGLE_API_KEY` is also accepted for Gemini.

### Default models

| Provider | Default model           |
| -------- | ----------------------- |
| Gemini   | `gemini-3.5-flash-lite` |
| Claude   | `claude-sonnet-5-5`     |

Change the model in the sidebar to use any other model your key has access to.

## How it works

The nutritionist chat uses a simple form of **RAG (retrieval-augmented generation)**: on each question, the app retrieves your 50 most recent recipes from SQLite and includes them (title, cuisine, servings, nutrition per serving, ingredients) in the model's system prompt. The model then answers using your actual eating history rather than generic advice.

At this scale, sending the recent history directly works better than embedding-based search. If the history grows too large for the prompt, the natural next step is to embed each recipe and retrieve only the most relevant ones per question.

## Project structure

```
app.py               Streamlit UI: sidebar settings, recipe form, history, chat
llm.py               Recipe schema + Gemini/Claude calls for recipes and chat
db.py                SQLite storage for recipes (recipes.db)
.local.env.example   Template for API keys
pyproject.toml       Project metadata and dependencies (managed with uv)
```

## Notes

- Nutrition values are AI estimates, not measured data. Treat them as a guide.
- The chat gives general nutrition guidance and isn't a substitute for a doctor or registered dietitian.
- `recipes.db` and `.local.env` are git-ignored, so your data and keys stay local.
