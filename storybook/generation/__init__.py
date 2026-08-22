"""Generation interfaces and factory. Providers are selected by settings; mock runs without any API key."""
from __future__ import annotations

from typing import Protocol

from storybook.config import get_settings
from storybook.content import PlotTemplate
from storybook.domain import CharacterSheet, ChildProfile, ScenePrompt, Story


class GenResult:
    """Bytes + cost, returned by image generators."""

    __slots__ = ("data", "cost_usd", "model")

    def __init__(self, data: bytes, cost_usd: float, model: str):
        self.data, self.cost_usd, self.model = data, cost_usd, model


class StoryGenerator(Protocol):
    async def generate(self, plot: PlotTemplate, child: ChildProfile, lang: str) -> tuple[Story, float]: ...


class IllustrationGenerator(Protocol):
    async def make_character_sheet(
        self, photos: list[bytes], child: ChildProfile, style_prompt: str, outfit: str
    ) -> tuple[GenResult, str]:
        """Returns (sheet image, textual description of the child's appearance)."""
        ...

    async def render_page(
        self, sheet_image: bytes, reference_photo: bytes, sheet: CharacterSheet, scene: ScenePrompt,
        style_prompt: str, outfit: str, child: ChildProfile, strict: bool = False,
    ) -> GenResult: ...


class FaceQA(Protocol):
    async def similarity(self, reference_photo: bytes, generated: bytes) -> float | None:
        """Cosine similarity of the main face vs reference, None if no face found."""
        ...


def story_generator() -> StoryGenerator:
    st = get_settings()
    if st.story_provider == "anthropic":
        from storybook.generation.story import AnthropicStoryGenerator

        return AnthropicStoryGenerator()
    from storybook.generation.story import MockStoryGenerator

    return MockStoryGenerator()


def illustration_generator() -> IllustrationGenerator:
    st = get_settings()
    if st.image_provider == "gemini":
        from storybook.generation.images import GeminiIllustrationGenerator

        return GeminiIllustrationGenerator()
    from storybook.generation.images import MockIllustrationGenerator

    return MockIllustrationGenerator()


def face_qa() -> FaceQA:
    st = get_settings()
    if st.face_qa == "insightface":
        from storybook.generation.faceqa import InsightFaceQA

        return InsightFaceQA()
    from storybook.generation.faceqa import NoopFaceQA

    return NoopFaceQA()
