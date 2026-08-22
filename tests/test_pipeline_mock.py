"""End-to-end pipeline with in-memory storage and mock generators. Produces a real PDF."""
import os
import uuid
from pathlib import Path

import pytest

from storybook.content import get_plot
from storybook.domain import ChildProfile, Gender
from storybook.generation.faceqa import NoopFaceQA
from storybook.generation.images import MockIllustrationGenerator
from storybook.generation.story import MockStoryGenerator
from storybook.storage import MemoryStorage, strip_exif_and_resize
from storybook.worker.pipeline import PipelineDeps, make_sheet, run_pipeline


def _fake_photo() -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (800, 1000), (200, 180, 160))
    b = io.BytesIO()
    img.save(b, format="JPEG")
    return b.getvalue()


class FlakyFaceQA:
    """Fails the first attempt of page 3 to exercise the retry path."""

    def __init__(self):
        self.calls = {}

    async def similarity(self, ref, gen):
        key = len(gen)  # mock images differ per page by text length; good enough as an id
        self.calls[key] = self.calls.get(key, 0) + 1
        return 0.2 if self.calls[key] == 1 and key % 3 == 0 else 0.9


@pytest.mark.asyncio
async def test_full_pipeline_produces_pdf(tmp_path: Path):
    storage = MemoryStorage()
    await storage.put("photos/1/a.jpg", strip_exif_and_resize(_fake_photo()), "image/jpeg")
    child = ChildProfile(name="Алихан", age=5, gender=Gender.BOY, photo_keys=["photos/1/a.jpg"])
    plot = get_plot("dragon")
    chromium = os.environ.get("CHROMIUM_PATH")
    deps = PipelineDeps(storage=storage, story_gen=MockStoryGenerator(), image_gen=MockIllustrationGenerator(),
                        face_qa=FlakyFaceQA(), face_threshold=0.4, page_max_attempts=2, concurrency=4, chromium_path=chromium)
    order_id = uuid.uuid4()
    sheet, cost = await make_sheet(deps, order_id, child, plot, "soft3d")
    assert sheet.image_key in storage.data

    progress = []

    async def prog(t):
        progress.append(t)

    res = await run_pipeline(deps, order_id, child, plot, "soft3d", sheet, prog, preview_cover_key=sheet.image_key)
    assert len(res.pages) == 12
    assert res.story.title == "Алихан и дракон"
    assert any(p.attempts == 2 for p in res.pages), "retry path not exercised"
    assert res.low_score_pages == []
    pdf = storage.data[res.pdf_key]
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 50_000
    assert progress[0].startswith("✍️") and progress[-1].startswith("📖")
    (tmp_path / "book.pdf").write_bytes(pdf)
