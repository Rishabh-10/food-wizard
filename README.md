# 🥗 Food Wizard

A Streamlit app that acts as your personal AI nutritionist. Tell it what ingredients you have, and it generates a recipe with estimated nutrition, saves it to your account, and answers your nutrition questions (calorie deficit, macros, meal ideas) using the recipes you've actually cooked.

Works with **Google Gemini** or **Anthropic Claude**: bring your own API key for either.

## Features

- **Google sign-in**: one click, and you stay signed in for 30 days, across refreshes and new tabs. Each user only sees their own recipes and chat history, and the nutritionist only uses that user's data.
- **Recipe generator**: enter ingredients (and optionally a cuisine) to get a full recipe with measurements, steps, prep time, servings, and estimated calories/protein/carbs/fat per serving.
- **Recipe history**: every recipe is saved to the database (hosted Postgres in production, `recipes.db` SQLite locally). Search by title, cuisine, or ingredient; see average calories and protein; delete recipes you don't want.
- **Nutritionist chat**: ask questions like *"Which of my recipes fit a 1,800 kcal day?"* or *"How can I get more protein from what I usually cook?"*. Answers are personalised using your saved recipes, and the conversation is saved to your account.
- **Provider choice**: switch between Gemini and Claude in the sidebar and pick the model.

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone <repo-url>
cd food-wizard
uv sync
uv run streamlit run app.py
```

The app opens at http://localhost:8501. Before you can sign in, set up Google sign-in (below).

### Google sign-in

Sign-in uses Streamlit's built-in `st.login()` with Google as the identity provider. Accounts are keyed by Google's permanent account ID, so the same Google account always gets the same data.

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), go to **APIs & Services → Credentials → Create credentials → OAuth client ID**, and choose **Web application**. (If asked, configure the consent screen first; "External" with yourself as a test user is enough to start.)
2. Under **Authorized redirect URIs**, add `http://localhost:8501/oauth2callback`, plus `https://<your-app>.streamlit.app/oauth2callback` if you deploy. One client can serve several apps.
3. Copy the template and fill in the client ID, client secret and a random `cookie_secret`:

   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```

Locally you can drop the `DATABASE_URL` line: the app then uses `recipes.db` (SQLite).

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

## Deploying to Streamlit Community Cloud

Community Cloud wipes the app's disk whenever it restarts, redeploys or wakes from sleep, so a SQLite file there loses every account and recipe. Use a hosted Postgres instead:

1. Create a free project at [Neon](https://neon.tech) and copy its connection string.
2. Add `https://<your-app>.streamlit.app/oauth2callback` to the Google OAuth client's redirect URIs.
3. In the app's **Settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example` with your values: `DATABASE_URL` set to the Neon string, and `redirect_uri` set to the `streamlit.app` URL above.
4. Reboot the app and sign in once to check it works. The tables are created on first start.

## How it works

The nutritionist chat uses a simple form of **RAG (retrieval-augmented generation)**: on each question, the app retrieves the signed-in user's 50 most recent recipes from the database and includes them (title, cuisine, servings, nutrition per serving, ingredients) in the model's system prompt. The model then answers using your actual eating history rather than generic advice.

At this scale, sending the recent history directly works better than embedding-based search. If the history grows too large for the prompt, the natural next step is to embed each recipe and retrieve only the most relevant ones per question.

## Project structure

```
app.py                          Streamlit UI: Google sign-in, sidebar settings, recipe form, history, chat
llm.py                          Recipe schema + Gemini/Claude calls for recipes and chat
db.py                           SQLAlchemy storage for users, recipes and chat history (Postgres or SQLite)
.local.env.example              Template for API keys
.streamlit/secrets.toml.example Template for the database URL and Google sign-in settings
pyproject.toml       Project metadata and dependencies (managed with uv)
```

## Notes

- Nutrition values are AI estimates, not measured data. Treat them as a guide.
- The chat gives general nutrition guidance and isn't a substitute for a doctor or registered dietitian.
- `recipes.db`, `.local.env` and `.streamlit/secrets.toml` are git-ignored, so your data and keys stay local.
- Sign-ins last 30 days (Streamlit's login cookie). Log out from the sidebar.
- API keys in `.local.env` are shared by everyone using that server. If you host the app for other people, leave `.local.env` empty so each user enters their own key in the sidebar.
- Upgrading from the username/password version: its `recipes.db` can't be reused. Delete it and the app creates a fresh one.
