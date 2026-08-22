"""Plot templates and style prompts, versioned in git. Loaded from YAML next to this file."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PLOTS_DIR = Path(__file__).parent / "plots"

STYLES: dict[str, str] = {
    "soft3d": (
        "soft 3D animated movie style, rounded friendly shapes, warm cinematic lighting, "
        "big expressive eyes, gentle pastel palette, highly detailed, children's book illustration, "
        "no text, no watermark, no captions"
    ),
}

AI_DISCLOSURE_RU = "Текст и иллюстрации этой книги созданы с помощью искусственного интеллекта."


@dataclass(frozen=True)
class PlotTemplate:
    code: str
    title: str
    emoji: str
    teaser: str
    age_range: tuple[int, int]
    hero_outfit: str
    scenes: list[dict]  # [{n, beat, setting, action}]
    version: int = 1

    @property
    def pages(self) -> int:
        return len(self.scenes)


@lru_cache
def load_plots() -> dict[str, PlotTemplate]:
    out: dict[str, PlotTemplate] = {}
    for f in sorted(PLOTS_DIR.glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        out[d["code"]] = PlotTemplate(
            code=d["code"],
            title=d["title"],
            emoji=d.get("emoji", "📖"),
            teaser=d["teaser"],
            age_range=tuple(d.get("age_range", [3, 9])),
            hero_outfit=d["hero_outfit"],
            scenes=d["scenes"],
            version=d.get("version", 1),
        )
    return out


def get_plot(code: str) -> PlotTemplate:
    return load_plots()[code]
