import json
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import jwt
from aiohttp import web
from passlib.context import CryptContext

from db import create_pool, ensure_schema_async, seed_if_empty
from rules import STATUS_UNCONFIRMED, STATUS_CONFIRMED, ACTION_CREATED, ACTION_CONFIRMED

SECRET = os.environ.get("JWT_SECRET", "coldchain-probe-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 双岗：至少两名记录员，建单人不能确认自己提交的单
USERS = {
    "logger": {"role": "writer", "password_hash": pwd.hash("log123456")},
    "logger2": {"role": "writer", "password_hash": pwd.hash("log2123456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}


def _json_error(cls, detail: str):
    return cls(
        text=json.dumps({"detail": detail}, ensure_ascii=False),
        content_type="application/json",
    )


def _auth_header(request: web.Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _decode_user(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def require_user(request: web.Request) -> dict:
    user = _decode_user(_auth_header(request))
    if not user:
        raise _json_error(web.HTTPUnauthorized, "未登录")
    return user


def require_writer(request: web.Request) -> dict:
    user = require_user(request)
    if user["role"] != "writer":
        raise _json_error(web.HTTPForbidden, "观察岗仅可查看，不可建单或确认")
    return user


def _reading_dict(r) -> dict:
    return {
        "id": r["id"],
        "probe_id": r["probe_id"],
        "temp_c": r["temp_c"],
        "verdict": r["verdict"],
        "reason": r["reason"],
        "status": r["status"],
        "created_by": r["created_by"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "confirmed_by": r["confirmed_by"],
        "confirmed_at": r["confirmed_at"].isoformat() if r["confirmed_at"] else None,
        "processed_at": r["processed_at"].isoformat() if r["processed_at"] else None,
    }


READING_COLS = """
    id, probe_id, temp_c, verdict, reason, status, created_by, created_at,
    confirmed_by, confirmed_at, processed_at
"""


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "coldchain-probe-desk"})


async def login(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        raise _json_error(web.HTTPUnauthorized, "用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp},
        SECRET,
        algorithm="HS256",
    )
    return web.json_response(
        {"access_token": token, "username": username, "role": user["role"]}
    )


async def list_readings(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(
        f"SELECT {READING_COLS} FROM probe_readings ORDER BY id DESC"
    )
    return web.json_response([_reading_dict(r) for r in rows])


async def create_reading(request: web.Request) -> web.Response:
    user = require_writer(request)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    probe_id = str(body.get("probe_id", "")).strip()
    if not probe_id:
        raise _json_error(web.HTTPBadRequest, "探头编号不能为空")
    try:
        temp_c = float(body.get("temp_c"))
    except (TypeError, ValueError) as exc:
        raise _json_error(web.HTTPBadRequest, "温度必须是数字") from exc

    pool: asyncpg.Pool = request.app["pool"]
    # 建单与建单流水同一事务一次写完，禁止半截成功
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                INSERT INTO probe_readings
                    (probe_id, temp_c, status, created_by, created_at)
                VALUES ($1, $2, $3, $4, now())
                RETURNING {READING_COLS}
                """,
                probe_id,
                temp_c,
                STATUS_UNCONFIRMED,
                user["username"],
            )
            await conn.execute(
                """
                INSERT INTO confirm_flow (reading_id, action, actor, detail)
                VALUES ($1, $2, $3, $4)
                """,
                row["id"],
                ACTION_CREATED,
                user["username"],
                f"建单：{probe_id} {temp_c:g}℃，待另一名记录员确认",
            )

    out = _reading_dict(row)
    out["message"] = "已入队待确认，须另一名记录员确认后才可被认领"
    return web.json_response(out, status=201)


async def confirm_reading(request: web.Request) -> web.Response:
    user = require_writer(request)
    try:
        reading_id = int(request.match_info["id"])
    except ValueError as exc:
        raise _json_error(web.HTTPBadRequest, "单据编号无效") from exc

    pool: asyncpg.Pool = request.app["pool"]
    # 状态翻转与确认流水同一事务一次写完，禁止半截成功
    async with pool.acquire() as conn:
        async with conn.transaction():
            reading = await conn.fetchrow(
                "SELECT created_by, confirmed_by FROM probe_readings WHERE id = $1",
                reading_id,
            )
            if not reading:
                raise _json_error(web.HTTPNotFound, "单据不存在")
            if reading["confirmed_by"] is not None:
                raise _json_error(web.HTTPConflict, "该单已确认，无需重复确认")
            if reading["created_by"] == user["username"]:
                raise _json_error(
                    web.HTTPForbidden, "建单人不能确认自己的单，须另一名记录员确认"
                )

            # 条件更新兜底并发：仅当仍未确认时才翻转
            row = await conn.fetchrow(
                f"""
                UPDATE probe_readings
                SET status = $2, confirmed_by = $3, confirmed_at = now()
                WHERE id = $1 AND confirmed_by IS NULL
                RETURNING {READING_COLS}
                """,
                reading_id,
                STATUS_CONFIRMED,
                user["username"],
            )
            if row is None:
                raise _json_error(web.HTTPConflict, "该单刚被其他记录员确认")
            await conn.execute(
                """
                INSERT INTO confirm_flow (reading_id, action, actor, detail)
                VALUES ($1, $2, $3, $4)
                """,
                reading_id,
                ACTION_CONFIRMED,
                user["username"],
                "双岗确认通过，转入待认领队列",
            )

    out = _reading_dict(row)
    out["message"] = "确认通过，该单可被后台工人认领"
    return web.json_response(out)


async def list_flow(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(
        """
        SELECT f.id, f.reading_id, f.action, f.actor, f.detail, f.created_at,
               r.probe_id, r.temp_c
        FROM confirm_flow f
        JOIN probe_readings r ON r.id = f.reading_id
        ORDER BY f.id DESC
        LIMIT 200
        """
    )
    return web.json_response(
        [
            {
                "id": r["id"],
                "reading_id": r["reading_id"],
                "probe_id": r["probe_id"],
                "temp_c": r["temp_c"],
                "action": r["action"],
                "actor": r["actor"],
                "detail": r["detail"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    )


async def on_startup(app: web.Application) -> None:
    pool = await create_pool()
    app["pool"] = pool
    await ensure_schema_async(pool)
    await seed_if_empty(pool)


async def on_cleanup(app: web.Application) -> None:
    pool: asyncpg.Pool = app.get("pool")
    if pool:
        await pool.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/api/readings", list_readings)
    app.router.add_post("/api/readings", create_reading)
    app.router.add_post("/api/readings/{id:\d+}/confirm", confirm_reading)
    app.router.add_get("/api/flow", list_flow)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000)
