import asyncpg
import threading
import os
from typing import AsyncGenerator, Optional

class Database:
    _instance: Optional['Database'] = None
    _lock = threading.Lock()

    def __new__(cls, dsn: str):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(Database, cls).__new__(cls)
        return cls._instance

    def __init__(self, dsn: str):
        # Only initialize once
        if hasattr(self, '_dsn'):
            return
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if not self._pool:
            # asyncpg doesn't support "postgresql+asyncpg://" scheme
            dsn = self._dsn.replace("+asyncpg", "")
            
            # Fetch pool settings from environment
            min_size = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
            max_size = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
            
            # Optimized pool size and parameters for production
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=min_size,
                max_size=max_size,
                max_queries=50000,   # Reset connection after 50k queries to prevent leaks
                max_inactive_connection_lifetime=300.0, # Kill connections inactive for 5 min
                command_timeout=60
            )

    async def disconnect(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            # Reset initialized state so it can be re-initialized if needed
            # but usually for a singleton we might not want this.
            # However, if we want to support testing we might need a way to reset.

    async def get_conn(self) -> AsyncGenerator[asyncpg.Connection, None]:
        if not self._pool:
            await self.connect()
        async with self._pool.acquire() as conn:
            yield conn

    async def fetch(self, query: str, *args):
        if not self._pool: await self.connect()
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        if not self._pool: await self.connect()
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        if not self._pool: await self.connect()
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args):
        if not self._pool: await self.connect()
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def executemany(self, query: str, args):
        if not self._pool: await self.connect()
        async with self._pool.acquire() as conn:
            return await conn.executemany(query, args)
