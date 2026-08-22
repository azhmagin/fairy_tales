from __future__ import annotations

import json

import structlog

from storybook.config import get_settings
from storybook.content import PlotTemplate
from storybook.domain import ChildProfile, Gender, ScenePrompt, Story

log = structlog.get_logger()

STORY_SYSTEM = """Ты — детский писатель. Пишешь добрые, тёплые сказки для детей 3–9 лет на русском языке.
Правила:
- Главный герой — реальный ребёнок: {name}, {age} лет, {gender_ru}. Имя склоняй правильно.
- Ровно {pages} страниц. Каждая страница 40–70 слов, простые предложения, 1–2 эмоции, ни одного пугающего образа.
- Имя героя встречается минимум на каждой второй странице.
- Следуй каркасу сцен (beat/setting/action) — порядок и суть менять нельзя, детали — можно.
- Для каждой страницы дай scene_prompt на английском: что нарисовать (композиция, ракурс, действие героя, окружение, настроение). Без имени ребёнка, без текста на картинке. Герой всегда в одежде: {outfit}.
- Финал — дома, спокойный, засыпание.
Отвечай ТОЛЬКО JSON: {{"title": str, "dedication": str, "moral": str, "pages": [{{"n": int, "text": str, "scene_prompt": str, "emotion": str}}]}}"""

REVIEW_SYSTEM = """Ты — редактор детской литературы и специалист по безопасности контента.
Проверь сказку: 1) нет пугающего/насилия/опасных действий, 2) возраст {age} лет, 3) имя {name} склоняется верно,
4) каждая страница 40–70 слов, 5) scene_prompt без имён и текста на картинке.
Если всё хорошо — верни JSON без изменений. Если нет — исправь и верни исправленный JSON той же структуры. Только JSON."""


def _gender_ru(g: Gender) -> str:
    return "мальчик" if g == Gender.BOY else "девочка"


def _parse(raw: str) -> Story:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{") :]
    d = json.loads(raw)
    pages = [ScenePrompt(n=int(p["n"]), text=p["text"].strip(), scene=p["scene_prompt"].strip(), emotion=p.get("emotion", "joy")) for p in d["pages"]]
    pages.sort(key=lambda p: p.n)
    return Story(title=d["title"].strip(), dedication=d.get("dedication", "").strip(), moral=d.get("moral", ""), pages=pages)


class MockStoryGenerator:
    """Deterministic story from the plot skeleton. Lets the whole pipeline run without an LLM."""

    async def generate(self, plot: PlotTemplate, child: ChildProfile, lang: str) -> tuple[Story, float]:
        pages = []
        for s in plot.scenes:
            text = (
                f"{child.name} {s['beat']}. " + f"Это была страница номер {s['n']} удивительного приключения. " * 3
                + f"{child.name} улыбается и идёт дальше, потому что впереди ждёт что-то очень интересное и доброе."
            )
            pages.append(ScenePrompt(n=s["n"], text=text, scene=f"{s['setting']}; {s['action']}", emotion="joy"))
        story = Story(
            title=plot.title.format(name=child.name),
            dedication=f"Для {child.name}, самого смелого героя на свете.",
            moral="Доброта и смелость всегда находят дорогу домой.",
            pages=pages,
        )
        story.validate(plot.pages)
        return story, 0.0


class AnthropicStoryGenerator:
    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        st = get_settings()
        self._client = AsyncAnthropic(api_key=st.anthropic_api_key)
        self._model = st.anthropic_model

    async def _call(self, system: str, user: str) -> tuple[str, float]:
        r = await self._client.messages.create(
            model=self._model, max_tokens=6000, temperature=0.8, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        # rough price estimate, adjust per model at launch
        cost = r.usage.input_tokens * 3e-6 + r.usage.output_tokens * 15e-6
        return text, cost

    async def generate(self, plot: PlotTemplate, child: ChildProfile, lang: str) -> tuple[Story, float]:
        system = STORY_SYSTEM.format(
            name=child.name, age=child.age, gender_ru=_gender_ru(child.gender), pages=plot.pages, outfit=plot.hero_outfit
        )
        skeleton = json.dumps(
            {"title_template": plot.title, "teaser": plot.teaser, "scenes": plot.scenes}, ensure_ascii=False
        )
        raw, c1 = await self._call(system, f"Каркас сюжета:\n{skeleton}")
        story = _parse(raw)
        review_system = REVIEW_SYSTEM.format(age=child.age, name=child.name)
        raw2, c2 = await self._call(review_system, raw)
        try:
            story = _parse(raw2)
        except Exception as e:  # keep v1 if reviewer returned garbage
            log.warning("story_review_parse_failed", error=str(e))
        story.validate(plot.pages)
        return story, c1 + c2
