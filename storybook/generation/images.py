from __future__ import annotations

import asyncio
import io

import structlog

from storybook.config import get_settings
from storybook.domain import CharacterSheet, ChildProfile, Gender, ScenePrompt
from storybook.generation import GenResult

log = structlog.get_logger()

# Prices per image (USD) — verify at launch, see architecture.md §7.1
PRICE = {"gemini-3-pro-image-preview": 0.15, "gemini-2.5-flash-image": 0.04, "mock": 0.0}

SHEET_PROMPT = (
    "Create a character reference sheet of the child in the attached photos, rendered in this style: {style}. "
    "Keep the face EXACTLY recognizable: same face shape, eyes, eyebrows, nose, mouth, skin tone, hair color and hairstyle. "
    "Show three views on a plain light background: front portrait, three-quarter view, full body. "
    "The child wears: {outfit}. Age {age}, {gender}. Friendly smile. No text."
)

DESCRIBE_PROMPT = (
    "Describe this child's appearance for an illustrator in one paragraph, in English: face shape, skin tone, "
    "hair color/length/style, eye color and shape, eyebrows, distinctive features (glasses, freckles, dimples). "
    "Do not guess name or ethnicity labels. Plain text only."
)

PAGE_PROMPT = (
    "Illustrate a children's book page in this style: {style}. "
    "The main character is the child from the reference images — keep the face identical to the reference "
    "(appearance: {description}). The child wears: {outfit}. "
    "Scene: {scene}. Mood: {emotion}. Composition leaves a clean area at the bottom for text. "
    "Exactly one child in the image unless the scene says otherwise. No text, no letters, no watermark."
)
STRICT_SUFFIX = " IMPORTANT: the face must match the reference photo much more closely — same eyes, nose, mouth, hair."


def _gender(g: Gender) -> str:
    return "boy" if g == Gender.BOY else "girl"


class MockIllustrationGenerator:
    """Draws placeholder cards with Pillow so the pipeline and PDF can be tested offline."""

    def __init__(self) -> None:
        from PIL import Image, ImageDraw  # noqa: F401

    def _card(self, title: str, body: str, color: tuple[int, int, int]) -> bytes:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (1024, 1024), color)
        d = ImageDraw.Draw(img)
        d.ellipse((362, 200, 662, 500), fill=(255, 224, 189), outline=(90, 60, 40), width=6)  # face
        d.ellipse((430, 300, 470, 340), fill=(40, 40, 40))
        d.ellipse((554, 300, 594, 340), fill=(40, 40, 40))
        d.arc((450, 360, 574, 440), 0, 180, fill=(180, 60, 60), width=8)
        d.text((40, 40), title, fill=(30, 30, 30))
        y = 560
        for line in body.split(";"):
            d.text((40, y), line.strip()[:90], fill=(30, 30, 30))
            y += 28
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    async def make_character_sheet(self, photos, child, style_prompt, outfit) -> tuple[GenResult, str]:
        await asyncio.sleep(0.05)
        img = self._card(f"CHARACTER SHEET: {child.name}", f"outfit: {outfit}", (220, 235, 255))
        return GenResult(img, 0.0, "mock"), f"mock description of {child.name}, {child.age} y.o. {_gender(child.gender)}"

    async def render_page(self, sheet_image, reference_photo, sheet, scene, style_prompt, outfit, child, strict=False) -> GenResult:
        await asyncio.sleep(0.05)
        img = self._card(f"PAGE {scene.n}", scene.scene, (255, 245, 220) if scene.n % 2 else (230, 250, 230))
        return GenResult(img, 0.0, "mock")


class GeminiIllustrationGenerator:
    """Google Gemini image models with multi-reference input (Nano Banana Pro / fallback)."""

    def __init__(self) -> None:
        from google import genai

        st = get_settings()
        self._client = genai.Client(api_key=st.gemini_api_key)
        self._model = st.gemini_image_model
        self._fallback = st.gemini_image_model_fallback
        self._sem = asyncio.Semaphore(st.image_concurrency)

    async def _generate(self, prompt: str, images: list[bytes], model: str) -> GenResult:
        from google.genai import types

        parts = [types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in images] + [prompt]
        async with self._sem:
            r = await self._client.aio.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
        for cand in r.candidates or []:
            for part in cand.content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    return GenResult(part.inline_data.data, PRICE.get(model, 0.1), model)
        raise RuntimeError(f"no image in response (finish_reason={getattr(r.candidates[0], 'finish_reason', None) if r.candidates else None})")

    async def _with_fallback(self, prompt: str, images: list[bytes]) -> GenResult:
        try:
            return await self._generate(prompt, images, self._model)
        except Exception as e:
            log.warning("image_primary_failed", model=self._model, error=str(e))
            return await self._generate(prompt, images, self._fallback)

    async def _describe(self, photo: bytes) -> str:
        from google.genai import types

        r = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_bytes(data=photo, mime_type="image/jpeg"), DESCRIBE_PROMPT],
        )
        return (r.text or "").strip()

    async def make_character_sheet(self, photos, child, style_prompt, outfit) -> tuple[GenResult, str]:
        prompt = SHEET_PROMPT.format(style=style_prompt, outfit=outfit, age=child.age, gender=_gender(child.gender))
        sheet, desc = await asyncio.gather(self._with_fallback(prompt, photos[:3]), self._describe(photos[0]))
        return sheet, desc

    async def render_page(self, sheet_image, reference_photo, sheet, scene, style_prompt, outfit, child, strict=False) -> GenResult:
        prompt = PAGE_PROMPT.format(
            style=style_prompt, description=sheet.description, outfit=outfit, scene=scene.scene, emotion=scene.emotion
        )
        if strict:
            prompt += STRICT_SUFFIX
        return await self._with_fallback(prompt, [sheet_image, reference_photo])
