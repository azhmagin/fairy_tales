from __future__ import annotations

import asyncio
import io


class NoopFaceQA:
    async def similarity(self, reference_photo: bytes, generated: bytes) -> float | None:
        return None


class InsightFaceQA:
    """ArcFace embeddings via InsightFace (CPU). Photos never leave the worker. Optional dependency."""

    def __init__(self) -> None:
        from insightface.app import FaceAnalysis

        self._app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=0, det_size=(640, 640))

    def _embed(self, data: bytes):
        import numpy as np
        from PIL import Image

        img = np.array(Image.open(io.BytesIO(data)).convert("RGB"))[:, :, ::-1]
        faces = self._app.get(img)
        if not faces:
            return None, 0
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        return faces[0].normed_embedding, len(faces)

    async def similarity(self, reference_photo: bytes, generated: bytes) -> float | None:
        loop = asyncio.get_running_loop()
        (a, _), (b, n) = await asyncio.gather(
            loop.run_in_executor(None, self._embed, reference_photo),
            loop.run_in_executor(None, self._embed, generated),
        )
        if a is None or b is None:
            return None
        import numpy as np

        score = float(np.dot(a, b))
        return score if n == 1 else score - 0.1  # penalize extra faces
