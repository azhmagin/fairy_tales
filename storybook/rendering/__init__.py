"""BookRenderer: Jinja2 HTML -> PDF via Playwright/Chromium. Square 210x210 mm, images embedded as data URIs."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from storybook.content import AI_DISCLOSURE_RU

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


@dataclass
class RenderPage:
    n: int
    text: str
    image_png: bytes


@dataclass
class BookDraft:
    title: str
    child_name: str
    dedication: str
    cover_png: bytes
    pages: list[RenderPage]
    moral: str = ""
    year: int = 2026


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def render_html(book: BookDraft) -> str:
    tpl = _env.get_template("book.html")
    return tpl.render(
        title=book.title,
        child_name=book.child_name,
        dedication=book.dedication,
        moral=book.moral,
        cover=_data_uri(book.cover_png),
        pages=[{"n": p.n, "text": p.text, "img": _data_uri(p.image_png)} for p in book.pages],
        disclosure=AI_DISCLOSURE_RU,
        year=book.year,
    )


async def render_pdf(book: BookDraft, executable_path: str | None = None) -> bytes:
    from playwright.async_api import async_playwright

    html = render_html(book)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=executable_path, args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            pdf = await page.pdf(width="210mm", height="210mm", print_background=True, prefer_css_page_size=True)
        finally:
            await browser.close()
    return pdf
