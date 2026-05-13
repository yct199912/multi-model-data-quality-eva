from redis import asyncio as aioredis
from typing import AsyncGenerator

class RedisClient:
    def __init__(self, url: str):
        self._url = url
        self._client = None

    async def connect(self):
        if not self._client:
            self._client = await aioredis.from_url(self._url)

    async def disconnect(self):
        if self._client:
            await self._client.close()
            self._client = None

    async def get_client(self) -> aioredis.Redis:
        if not self._client:
            await self.connect()
        return self._client
