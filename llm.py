from collections.abc import Iterator

import anthropic
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

GEMINI = "Gemini"
CLAUDE = "Claude"

DEFAULT_MODELS = {
    GEMINI: "gemini-3.5-flash-lite",
    CLAUDE: "claude-sonnet-5-5",
}


class Recipe(BaseModel):
    title: str = Field(description="The name of the recipe")
    cuisine: str = Field(description="The cuisine this recipe belongs to")
    ingredients_needed: list[str] = Field(description="List of ingredients with exact measurements")
    instructions: list[str] = Field(description="Step by step instructions")
    prep_time_minutes: int = Field(description="Estimated preparation time in minutes")
    servings: int = Field(description="Number of servings the recipe makes")
    calories_per_serving: int = Field(description="Estimated calories (kcal) per serving")
    protein_g: float = Field(description="Estimated protein per serving, in grams")
    carbs_g: float = Field(description="Estimated carbohydrates per serving, in grams")
    fat_g: float = Field(description="Estimated fat per serving, in grams")


CHAT_SYSTEM_PROMPT = """You are a friendly, practical nutritionist inside the user's recipe app.

Below is the user's saved recipe history (newest first). Treat it as a record of what they cook and eat. Use it to personalise every answer: reference specific recipes by name, spot patterns (e.g. low protein, high fat, repeated ingredients), estimate how meals fit a calorie or macro target, and suggest concrete swaps or new meal ideas built from ingredients they already use.

Guidelines:
- Nutrition numbers in the history are AI estimates; say so when precision matters.
- If the user hasn't told you their goals, weight, or activity level and the answer depends on it, ask briefly or state the assumption you're making.
- For medical conditions, eating disorders, pregnancy, or medication interactions, give general guidance and recommend seeing a doctor or registered dietitian.
- Keep answers concise and skimmable.

<recipe_history>
{history}
</recipe_history>"""


def _recipe_prompt(ingredients: list[str], cuisine: str | None) -> str:
    prompt = "Give me a recipe for the following ingredients: " + ", ".join(ingredients)
    if cuisine:
        prompt += f"\nThe recipe should be {cuisine} cuisine."
    prompt += (
        "\nYou may assume common pantry staples (salt, pepper, oil, water, basic spices)."
        "\nInclude estimated nutrition per serving."
    )
    return prompt


def create_recipe(provider: str, api_key: str, model: str, ingredients: list[str], cuisine: str | None = None) -> Recipe:
    prompt = _recipe_prompt(ingredients, cuisine)

    if provider == GEMINI:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Recipe,
            ),
        )
        # .parsed is None when the SDK couldn't parse the output; fall back to the raw text
        return response.parsed or Recipe.model_validate_json(response.text)

    # Claude: force a tool call whose input schema is the Recipe model to get structured output
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "name": "save_recipe",
                "description": "Save the generated recipe.",
                "input_schema": Recipe.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "save_recipe"},
    )
    tool_use = next(block for block in response.content if block.type == "tool_use")
    return Recipe.model_validate(tool_use.input)


def format_recipe_history(recipes: list[dict]) -> str:
    if not recipes:
        return "(no saved recipes yet)"
    lines = []
    for r in recipes:
        lines.append(
            f"- [{r['created_at'][:10]}] {r['title']} ({r['cuisine'] or 'unspecified cuisine'}) | "
            f"{r['servings']} servings, {r['prep_time_minutes']} min | per serving: "
            f"{r['calories_per_serving']} kcal, P {r['protein_g']:g}g, C {r['carbs_g']:g}g, F {r['fat_g']:g}g | "
            f"ingredients: {'; '.join(r['ingredients_needed'])}"
        )
    return "\n".join(lines)


def stream_chat(provider: str, api_key: str, model: str, messages: list[dict], recipes: list[dict]) -> Iterator[str]:
    """Stream the nutritionist's reply. `messages` is [{"role": "user"|"assistant", "content": str}, ...]."""
    system = CHAT_SYSTEM_PROMPT.format(history=format_recipe_history(recipes))

    if provider == GEMINI:
        client = genai.Client(api_key=api_key)
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system),
        ):
            if chunk.text:
                yield chunk.text
        return

    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(model=model, max_tokens=2048, system=system, messages=messages) as stream:
        yield from stream.text_stream
