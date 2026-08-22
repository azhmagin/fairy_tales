import os
import sys
import types

# Tests for pure modules must not require aiogram/sqlalchemy. Provide a tiny structlog shim if missing.
try:
    import structlog  # noqa: F401
except ImportError:  # pragma: no cover
    shim = types.ModuleType("structlog")

    class _L:
        def __getattr__(self, _):
            return lambda *a, **k: None

    shim.get_logger = lambda *a, **k: _L()
    sys.modules["structlog"] = shim

os.environ.setdefault("SB_BOT_TOKEN", "test")
