import os

import asyncpg
import psycopg
from psycopg.rows import dict_row

from rules import judge_temp

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54397/coldchain"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS probe_readings (
    id serial PRIMARY KEY,
    probe_id text NOT NULL,
    temp_c double precision NOT NULL,
    verdict text,
    reason text,
    status text NOT NULL DEFAULT 'pending',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    confirmed_by text,
    confirmed_at timestamptz,
    processed_at timestamptz
);
ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS confirmed_by text;
ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS confirmed_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_probe_readings_status ON probe_readings (status, id);

CREATE TABLE IF NOT EXISTS reading_events (
    id serial PRIMARY KEY,
    reading_id int NOT NULL REFERENCES probe_readings (id),
    action text NOT NULL,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reading_events_reading ON reading_events (reading_id, id);
"""


def connect_sync():
    return psycopg.connect(DSN, row_factory=dict_row)


def ensure_schema_sync(conn) -> None:
    conn.execute(SCHEMA_SQL)


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(DSN, min_size=1, max_size=5)


async def ensure_schema_async(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


SEED_SAMPLES = [
    ("探头A01", 4.2),
    ("探头B02", 12.5),
]


async def seed_if_empty(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM probe_readings")
        if n and n > 0:
            return
        async with conn.transaction():
            for probe_id, temp_c in SEED_SAMPLES:
                verdict, reason = judge_temp(temp_c)
                row = await conn.fetchrow(
                    """
                    INSERT INTO probe_readings
                        (probe_id, temp_c, verdict, reason, status,
                         created_by, confirmed_by, confirmed_at, processed_at)
                    VALUES ($1, $2, $3, $4, 'done', 'logger', 'logger2', now(), now())
                    RETURNING id
                    """,
                    probe_id,
                    temp_c,
                    verdict,
                    reason,
                )
                await conn.execute(
                    """
                    INSERT INTO reading_events (reading_id, action, actor)
                    VALUES ($1, 'create', 'logger'), ($1, 'confirm', 'logger2')
                    """,
                    row["id"],
                )


def seed_if_empty_sync(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM probe_readings").fetchone()
    if row["n"] > 0:
        return
    for probe_id, temp_c in SEED_SAMPLES:
        verdict, reason = judge_temp(temp_c)
        cur = conn.execute(
            """
            INSERT INTO probe_readings
                (probe_id, temp_c, verdict, reason, status,
                 created_by, confirmed_by, confirmed_at, processed_at)
            VALUES (%s, %s, %s, %s, 'done', 'logger', 'logger2', now(), now())
            RETURNING id
            """,
            (probe_id, temp_c, verdict, reason),
        )
        reading_id = cur.fetchone()["id"]
        conn.execute(
            """
            INSERT INTO reading_events (reading_id, action, actor)
            VALUES (%s, 'create', 'logger'), (%s, 'confirm', 'logger2')
            """,
            (reading_id, reading_id),
        )
    conn.commit()
