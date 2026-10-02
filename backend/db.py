import os

import asyncpg
import psycopg
from psycopg.rows import dict_row

from rules import STATUS_DONE, judge_temp

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
    status text NOT NULL DEFAULT 'unconfirmed',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    confirmed_by text,
    confirmed_at timestamptz,
    processed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_probe_readings_status ON probe_readings (status, id);
CREATE INDEX IF NOT EXISTS idx_probe_readings_unconfirmed
    ON probe_readings (id) WHERE confirmed_by IS NULL;

CREATE TABLE IF NOT EXISTS confirm_flow (
    id serial PRIMARY KEY,
    reading_id integer NOT NULL REFERENCES probe_readings(id),
    action text NOT NULL CHECK (action IN ('created', 'confirmed')),
    actor text NOT NULL,
    detail text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_confirm_flow_reading ON confirm_flow (reading_id, id);
"""


def connect_sync():
    return psycopg.connect(DSN, row_factory=dict_row)


def ensure_schema_sync(conn) -> None:
    conn.execute(SCHEMA_SQL)
    # 兼容在旧库上新增的列/表（CREATE TABLE IF NOT EXISTS 不会补列）
    conn.execute(
        "ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS confirmed_by text"
    )
    conn.execute(
        "ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS confirmed_at timestamptz"
    )


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(DSN, min_size=1, max_size=5)


async def ensure_schema_async(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(
            "ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS confirmed_by text"
        )
        await conn.execute(
            "ALTER TABLE probe_readings ADD COLUMN IF NOT EXISTS confirmed_at timestamptz"
        )


async def seed_if_empty(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM probe_readings")
        if n and n > 0:
            return
        samples = [
            ("探头A01", 4.2, "logger"),
            ("探头B02", 12.5, "logger2"),
        ]
        for probe_id, temp_c, actor in samples:
            verdict, reason = judge_temp(temp_c)
            async with conn.transaction():
                reading_id = await conn.fetchval(
                    """
                    INSERT INTO probe_readings
                        (probe_id, temp_c, verdict, reason, status, created_by,
                         confirmed_by, confirmed_at, processed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, now(), now())
                    RETURNING id
                    """,
                    probe_id,
                    temp_c,
                    verdict,
                    reason,
                    STATUS_DONE,
                    actor,
                    "logger2" if actor == "logger" else "logger",
                )
                await conn.execute(
                    """
                    INSERT INTO confirm_flow (reading_id, action, actor, detail)
                    VALUES ($1, 'created', $2, $3)
                    """,
                    reading_id,
                    actor,
                    f"建单：{probe_id} {temp_c}℃",
                )
                await conn.execute(
                    """
                    INSERT INTO confirm_flow (reading_id, action, actor, detail)
                    VALUES ($1, 'confirmed', $2, $3)
                    """,
                    reading_id,
                    "logger2" if actor == "logger" else "logger",
                    "种子数据确认",
                )


def seed_if_empty_sync(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM probe_readings").fetchone()
    if row["n"] > 0:
        return
    samples = [
        ("探头A01", 4.2, "logger"),
        ("探头B02", 12.5, "logger2",),
    ]
    for probe_id, temp_c, actor in samples:
        verdict, reason = judge_temp(temp_c)
        confirmer = "logger2" if actor == "logger" else "logger"
        with conn.transaction():
            reading_id = conn.execute(
                """
                INSERT INTO probe_readings
                    (probe_id, temp_c, verdict, reason, status, created_by,
                     confirmed_by, confirmed_at, processed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
                RETURNING id
                """,
                (
                    probe_id,
                    temp_c,
                    verdict,
                    reason,
                    STATUS_DONE,
                    actor,
                    confirmer,
                ),
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT INTO confirm_flow (reading_id, action, actor, detail)
                VALUES (%s, 'created', %s, %s)
                """,
                (reading_id, actor, f"建单：{probe_id} {temp_c}℃"),
            )
            conn.execute(
                """
                INSERT INTO confirm_flow (reading_id, action, actor, detail)
                VALUES (%s, 'confirmed', %s, %s)
                """,
                (reading_id, confirmer, "种子数据确认"),
            )
    conn.commit()
