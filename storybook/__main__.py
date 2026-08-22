"""Entrypoints: `python -m storybook bot` (polling) | `python -m storybook api` | `python -m storybook worker`."""
from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from storybook.config import get_settings


def _logging() -> None:
    st = get_settings()
    logging.basicConfig(level=st.log_level, format="%(message)s", stream=sys.stdout)
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level, structlog.processors.JSONRenderer(ensure_ascii=False)],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(st.log_level)),
    )


def main() -> None:
    _logging()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bot"
    if cmd == "bot":
        from storybook.bot import run_polling

        asyncio.run(run_polling())
    elif cmd == "api":
        import uvicorn

        uvicorn.run("storybook.api:app", host="0.0.0.0", port=8000, log_level="info")
    elif cmd == "worker":
        from arq import run_worker

        from storybook.worker.tasks import WorkerSettings

        run_worker(WorkerSettings)
    else:
        print("usage: python -m storybook [bot|api|worker]")
        sys.exit(2)


if __name__ == "__main__":
    main()
