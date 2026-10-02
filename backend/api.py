import json
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import jwt
from aiohttp import web
from passlib.context import CryptContext

from db import create_pool, ensure_schema_async, seed_if_empty

SECRET = os.environ.get("JWT_SECRET", "coldchain-probe-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

USERS = {
    "logger": {"role": "writer", "password_hash": pwd.hash("log123456")},
    "logger2": {"role": "writer", "password_hash": pwd.hash("log223456")},
    "watcher": {"role": "reader", "password_hash": pwd.hash("watch123456")},
}


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
        raise web.HTTPUnauthorized(text=json.dumps({"detail": "未登录"}, ensure_ascii=False), content_type="application/json")
    return user


def require_writer(request: web.Request, action: str = "提交读数") -> dict:
    user = require_user(request)
    if user["role"] != "writer":
        raise web.HTTPForbidden(
            text=json.dumps({"detail": f"仅记录员可{action}"}, ensure_ascii=False),
            content_type="application/json",
        )
    return user


def _json_error(exc_type, detail: str):
    return exc_type(text=json.dumps({"detail": detail}, ensure_ascii=False), content_type="application/json")


def _reading_json(row) -> dict:
    return {
        "id": row["id"],
        "probe_id": row["probe_id"],
        "temp_c": row["temp_c"],
        "verdict": row["verdict"],
        "reason": row["reason"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"].isoformat() if row["confirmed_at"] else None,
        "processed_at": row["processed_at"].isoformat() if row["processed_at"] else None,
    }


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
        raise web.HTTPUnauthorized(
            text=json.dumps({"detail": "用户名或密码错误"}, ensure_ascii=False),
            content_type="application/json",
        )
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
        """
        SELECT id, probe_id, temp_c, verdict, reason, status,
               created_by, created_at, confirmed_by, confirmed_at, processed_at
        FROM probe_readings
        ORDER BY id DESC
        """
    )
    return web.json_response([_reading_json(r) for r in rows])


async def create_reading(request: web.Request) -> web.Response:
    user = require_writer(request, "提交读数")
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
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO probe_readings (probe_id, temp_c, status, created_by, created_at)
                VALUES ($1, $2, 'pending', $3, now())
                RETURNING id, probe_id, temp_c, verdict, reason, status,
                          created_by, created_at, confirmed_by, confirmed_at, processed_at
                """,
                probe_id,
                temp_c,
                user["username"],
            )
            await conn.execute(
                "INSERT INTO reading_events (reading_id, action, actor) VALUES ($1, 'create', $2)",
                row["id"],
                user["username"],
            )
    return web.json_response(
        {
            **_reading_json(row),
            "message": "已入队并记入流水，待另一名记录员确认后工人才会认领",
        },
        status=201,
    )


async def confirm_reading(request: web.Request) -> web.Response:
    user = require_writer(request, "确认读数")
    try:
        reading_id = int(request.match_info["id"])
    except (KeyError, ValueError) as exc:
        raise _json_error(web.HTTPBadRequest, "单号不合法") from exc

    pool: asyncpg.Pool = request.app["pool"]
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id, created_by, confirmed_by
                FROM probe_readings
                WHERE id = $1
                FOR UPDATE
                """,
                reading_id,
            )
            if not row:
                raise _json_error(web.HTTPNotFound, "读数不存在")
            if row["confirmed_by"]:
                raise _json_error(web.HTTPConflict, "该单已被确认，请勿重复操作")
            if row["created_by"] == user["username"]:
                raise _json_error(web.HTTPForbidden, "建单人不能确认自己的单，请换另一名记录员")
            updated = await conn.fetchrow(
                """
                UPDATE probe_readings
                SET confirmed_by = $1, confirmed_at = now()
                WHERE id = $2
                RETURNING id, probe_id, temp_c, verdict, reason, status,
                          created_by, created_at, confirmed_by, confirmed_at, processed_at
                """,
                user["username"],
                reading_id,
            )
            await conn.execute(
                "INSERT INTO reading_events (reading_id, action, actor) VALUES ($1, 'confirm', $2)",
                reading_id,
                user["username"],
            )
    return web.json_response(
        {**_reading_json(updated), "message": "已确认并记入流水，工人可认领该单"}
    )


async def list_events(request: web.Request) -> web.Response:
    require_user(request)
    pool: asyncpg.Pool = request.app["pool"]
    rows = await pool.fetch(
        """
        SELECT e.id, e.reading_id, e.action, e.actor, e.created_at,
               r.probe_id, r.temp_c
        FROM reading_events e
        JOIN probe_readings r ON r.id = e.reading_id
        ORDER BY e.id DESC
        LIMIT 200
        """
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "reading_id": r["reading_id"],
                "action": r["action"],
                "actor": r["actor"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "probe_id": r["probe_id"],
                "temp_c": r["temp_c"],
            }
        )
    return web.json_response(out)


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
    app.router.add_post("/api/readings/{id}/confirm", confirm_reading)
    app.router.add_get("/api/events", list_events)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8000)
