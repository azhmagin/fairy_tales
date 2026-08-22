"""Generation pipeline. Idempotent per order_id; every stage logged in `jobs` with cost.

Stages: story -> pages (parallel, QA + retries) -> pdf -> review|deliver.
The pure orchestration (`run_pipeline`) depends only on protocols, so it is testable with in-memory fakes.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from storybook.content import STYLES, PlotTemplate
from storybook.domain import CharacterSheet, ChildProfile, PageResult, ScenePrompt, Story
from storybook.generation import FaceQA, IllustrationGenerator, StoryGenerator
from storybook.rendering import BookDraft, RenderPage, render_pdf
from storybook.storage import ObjectStorage

log = structlog.get_logger()

Progress = Callable[[str], Awaitable[None]]


@dataclass
class PipelineDeps:
    storage: ObjectStorage
    story_gen: StoryGenerator
    image_gen: IllustrationGenerator
    face_qa: FaceQA
    face_threshold: float = 0.40
    page_max_attempts: int = 3
    concurrency: int = 4
    chromium_path: str | None = None


@dataclass
class PipelineResult:
    story: Story
    pages: list[PageResult]
    pdf_key: str
    cost_usd: float
    low_score_pages: list[int]


async def make_sheet(deps: PipelineDeps, order_id: uuid.UUID, child: ChildProfile, plot: PlotTemplate, style: str) -> tuple[CharacterSheet, float]:
    photos = [await deps.storage.get(k) for k in child.photo_keys]
    res, desc = await deps.image_gen.make_character_sheet(photos, child, STYLES[style], plot.hero_outfit)
    key = f"sheets/{order_id}.png"
    await deps.storage.put(key, res.data, "image/png")
    return CharacterSheet(image_key=key, reference_photo_key=child.photo_keys[0], description=desc, model=res.model), res.cost_usd


async def _render_one(deps: PipelineDeps, order_id: uuid.UUID, sheet: CharacterSheet, sheet_img: bytes, ref: bytes,
                      scene: ScenePrompt, plot: PlotTemplate, style: str, child: ChildProfile) -> PageResult:
    cost = 0.0
    best: tuple[float, bytes] | None = None
    for attempt in range(1, deps.page_max_attempts + 1):
        res = await deps.image_gen.render_page(sheet_img, ref, sheet, scene, STYLES[style], plot.hero_outfit, child, strict=attempt > 1)
        cost += res.cost_usd
        score = await deps.face_qa.similarity(ref, res.data)
        s = score if score is not None else 1.0  # no QA configured -> accept
        if best is None or s > best[0]:
            best = (s, res.data)
        if score is None or score >= deps.face_threshold:
            break
        log.info("page_qa_retry", order_id=str(order_id), page=scene.n, attempt=attempt, score=round(score, 3))
    assert best is not None
    key = f"pages/{order_id}/{scene.n:02d}.png"
    await deps.storage.put(key, best[1], "image/png")
    return PageResult(n=scene.n, image_key=key, face_score=None if best[0] == 1.0 and score is None else best[0], attempts=attempt, cost_usd=cost)


async def run_pipeline(deps: PipelineDeps, order_id: uuid.UUID, child: ChildProfile, plot: PlotTemplate, style: str,
                       sheet: CharacterSheet, progress: Progress, lang: str = "ru",
                       preview_cover_key: str | None = None) -> PipelineResult:
    total = 0.0
    await progress("✍️ Пишем историю…")
    story, c = await deps.story_gen.generate(plot, child, lang)
    total += c

    sheet_img = await deps.storage.get(sheet.image_key)
    ref = await deps.storage.get(sheet.reference_photo_key)
    sem = asyncio.Semaphore(deps.concurrency)
    done = 0
    results: dict[int, PageResult] = {}

    async def one(scene: ScenePrompt):
        nonlocal done
        async with sem:
            r = await _render_one(deps, order_id, sheet, sheet_img, ref, scene, plot, style, child)
        results[scene.n] = r
        done += 1
        await progress(f"🎨 Рисуем иллюстрации… {done}/{len(story.pages)}")

    await asyncio.gather(*(one(p) for p in story.pages))
    pages = [results[p.n] for p in story.pages]
    total += sum(p.cost_usd for p in pages)

    await progress("📖 Собираем книгу…")
    cover_png = await deps.storage.get(preview_cover_key) if preview_cover_key else await deps.storage.get(pages[0].image_key)
    draft = BookDraft(
        title=story.title, child_name=child.name, dedication=story.dedication, cover_png=cover_png, moral=story.moral,
        pages=[RenderPage(n=p.n, text=p.text, image_png=await deps.storage.get(results[p.n].image_key)) for p in story.pages],
    )
    pdf = await render_pdf(draft, executable_path=deps.chromium_path)
    pdf_key = f"books/{order_id}.pdf"
    await deps.storage.put(pdf_key, pdf, "application/pdf")
    low = [p.n for p in pages if p.face_score is not None and p.face_score < deps.face_threshold]
    return PipelineResult(story=story, pages=pages, pdf_key=pdf_key, cost_usd=total, low_score_pages=low)
