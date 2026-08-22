"""S3-compatible object storage. Keys: photos/{user}/{uuid}.jpg, sheets/..., pages/{order}/{n}.png, books/{order}.pdf"""
from __future__ import annotations

import io
from typing import Protocol

from storybook.config import get_settings


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def presigned_url(self, key: str, ttl: int = 3600) -> str: ...


class S3Storage:
    def __init__(self) -> None:
        import aioboto3  # lazy: optional in tests

        s = get_settings()
        self._session = aioboto3.Session()
        self._kw = {
            "service_name": "s3",
            "endpoint_url": s.s3_endpoint,
            "aws_access_key_id": s.s3_access_key,
            "aws_secret_access_key": s.s3_secret_key,
            "region_name": s.s3_region,
        }
        self._bucket = s.s3_bucket

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        async with self._session.client(**self._kw) as c:
            await c.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return key

    async def get(self, key: str) -> bytes:
        async with self._session.client(**self._kw) as c:
            r = await c.get_object(Bucket=self._bucket, Key=key)
            async with r["Body"] as body:
                return await body.read()

    async def delete(self, key: str) -> None:
        async with self._session.client(**self._kw) as c:
            await c.delete_object(Bucket=self._bucket, Key=key)

    async def presigned_url(self, key: str, ttl: int = 3600) -> str:
        async with self._session.client(**self._kw) as c:
            return await c.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=ttl
            )


class MemoryStorage:
    """For tests and local scripts."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        self.data[key] = data
        return key

    async def get(self, key: str) -> bytes:
        return self.data[key]

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def presigned_url(self, key: str, ttl: int = 3600) -> str:
        return f"memory://{key}"


def strip_exif_and_resize(data: bytes, max_side: int = 1536) -> bytes:
    """Re-encode uploaded photo: drops EXIF/GPS, normalizes orientation, limits size before sending to AI APIs."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage
